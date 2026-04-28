from __future__ import annotations

import logging
from typing import Any

from app.rag.retrieval.intent import (
    INTENT_LABELS,
    LANGUAGE_LABELS,
    _intent_meta_used_openai,
    _norm_text,
    _strip_request_scaffolding,
    build_intent_heuristic_answer,
    classify_intent_v2,
    detect_language,
)
from app.rag.retrieval.logging_utils import append_step, build_openai_usage_summary
from app.rag.retrieval.memory import ConversationMemory
from app.rag.retrieval.planning import generate_search_plan_v2
from app.rag.retrieval.search import apply_cutoff_and_build_context, rrf_fuse, semantic_search_multi_query
from app.rag.retrieval.types import RetrievalConfig

logger = logging.getLogger(__name__)


async def execute_retrieval_pipeline(
    query: str,
    *,
    config: RetrievalConfig | None = None,
    has_history: bool = False,
    openai_client: Any | None = None,
    intent_model: str = "gpt-4o-mini",
    embedding_remote_base_url: str | None = None,
    memory: ConversationMemory | None = None,
) -> dict[str, Any]:
    cfg = config or RetrievalConfig()
    normalized_query = (query or "").strip()
    if not normalized_query:
        raise ValueError("query is empty")
    step_logs: list[dict[str, Any]] = []
    if memory is not None:
        memory.add("user", normalized_query)

    logger.info("[retrieval][step1] intent classification started")
    intent, intent_meta = await classify_intent_v2(
        message=normalized_query,
        has_history=has_history,
        openai_client=openai_client,
        model=intent_model,
        memory=memory,
    )
    if intent not in INTENT_LABELS:
        intent = "general"
    logger.info("[retrieval][step1] intent=%s", intent)
    classification_source = str(intent_meta.get("source", "unknown"))
    used_openai = _intent_meta_used_openai(intent_meta)
    classification_path_text = "OpenAI 기반 분류" if used_openai else "휴리스틱 분류"
    append_step(
        step_logs,
        step=1,
        title="의도 분류",
        detail=f"query 의도를 '{intent}'로 분류 (분류 경로: {classification_path_text}, source={classification_source})",
        data={
            "intent": intent,
            "query": normalized_query,
            "classification_meta": intent_meta,
            "openai_used_for_intent": used_openai,
            "intent_model": intent_model if openai_client is not None else None,
        },
    )

    logger.info("[retrieval][step2] language detection started")
    language = detect_language(normalized_query)
    if language not in LANGUAGE_LABELS:
        language = "ko"
    logger.info("[retrieval][step2] language=%s", language)
    append_step(step_logs, step=2, title="언어 감지", detail=f"입력 언어를 '{language}'로 판정", data={"language": language})

    openai_present = openai_client is not None
    logger.info("[retrieval][step3] query planning started")
    if intent in {"greeting", "not_related", "general"}:
        raw_norm = _norm_text(normalized_query)
        cleaned = _strip_request_scaffolding(raw_norm)
        planning_meta = {
            "skipped": True,
            "skip_reason": "non_search_intent",
            "planner_meta": {"source": "skipped_non_search_intent"},
            "raw_query": raw_norm,
            "cleaned_query": cleaned,
            "base_queries": [],
            "llm_queries": [],
        }
        planned_queries: list[str] = []
        logger.info("[retrieval][step3] query planning skipped intent=%s", intent)
        append_step(
            step_logs,
            step=3,
            title="쿼리 계획 생략",
            detail="비검색 의도로 OpenAI 쿼리 플래너·다중 쿼리 생성을 건너뜀",
            data={"skipped": True, "intent": intent, "query_planner_meta": planning_meta["planner_meta"]},
        )
    else:
        planned_queries, planning_meta = await generate_search_plan_v2(
            message=normalized_query,
            language=language,
            intent=intent,
            openai_client=openai_client,
            openai_model=intent_model,
            min_queries=cfg.min_queries,
            max_queries=cfg.max_queries,
        )
        logger.info("[retrieval][step3] planned_queries=%s", planned_queries)
        planner_src = str((planning_meta.get("planner_meta") or {}).get("source", ""))
        append_step(
            step_logs,
            step=3,
            title="쿼리 계획",
            detail=f"{len(planned_queries)}개 집중 쿼리 생성",
            data={
                "planned_queries": planned_queries,
                "cleaned_query": planning_meta.get("cleaned_query", ""),
                "base_queries": planning_meta.get("base_queries", []),
                "llm_queries": planning_meta.get("llm_queries", []),
                "openai_used_for_query_planning": planner_src == "llm_query_planner",
                "query_planner_meta": planning_meta.get("planner_meta", {}),
            },
        )

    if intent in {"greeting", "not_related", "general"}:
        heuristic_answer = build_intent_heuristic_answer(intent=intent, language=language, query=normalized_query)
        append_step(
            step_logs,
            step=4,
            title="검색 생략",
            detail=f"의도 '{intent}'로 판단되어 다중 쿼리 검색을 수행하지 않음",
            data={"response_mode": "intent_heuristic"},
        )
        openai_usage_summary = build_openai_usage_summary(
            intent_meta=intent_meta,
            planning_meta=planning_meta,
            vector_search_ran=False,
            openai_client_present=openai_present,
        )
        return {
            "intent": intent,
            "language": language,
            "planned_queries": [],
            "per_query_results": [],
            "fused_results": [],
            "final_results": [],
            "llm_context": "",
            "step_logs": step_logs,
            "response_mode": "general_chat" if intent == "general" else "intent_heuristic",
            "heuristic_answer": heuristic_answer,
            "openai_usage_summary": openai_usage_summary,
        }

    search_lang = "kor" if language == "ko" else "eng"
    # intent에 따라 검색 스코프(회사/제품)를 제한한다.
    entity_scope = "all"
    if intent == "company":
        entity_scope = "company"
    elif intent == "product":
        entity_scope = "product"
    searches = semantic_search_multi_query(
        queries=planned_queries,
        model_id=cfg.model_id,
        device=cfg.device,
        top_k_per_query=cfg.top_k_per_query,
        lang=search_lang,
        evidence_ratio=cfg.evidence_ratio,
        embedding_remote_base_url=embedding_remote_base_url,
        entity_scope=entity_scope,
    )
    query_summaries: list[dict[str, Any]] = []
    for bucket in searches:
        rows = bucket["results"]
        query_summaries.append({"query": bucket["query"], "count": len(rows), "top_preview": [r.get("content", "")[:80] for r in rows[:2]]})
    append_step(
        step_logs,
        step=4,
        title="의미 검색",
        detail="쿼리별 profile/evidence 검색 수행",
        data={"query_summaries": query_summaries, "search_lang": search_lang, "entity_scope": entity_scope},
    )

    fused = rrf_fuse(searches, rrf_k=cfg.rrf_k)
    append_step(
        step_logs,
        step=5,
        title="다중 쿼리 융합 (RRF)",
        detail=f"RRF로 {len(fused)}개 후보 생성",
        data={"rrf_k": cfg.rrf_k, "fused_count": len(fused)},
    )
    final_results, llm_context = apply_cutoff_and_build_context(
        fused,
        score_cutoff=cfg.score_cutoff,
        final_top_k=cfg.final_top_k,
        context_limit=cfg.context_limit,
    )
    append_step(
        step_logs,
        step=6,
        title="컷오프 + 컨텍스트 조립",
        detail=f"score_cutoff={cfg.score_cutoff} 적용 후 {len(final_results)}개 결과 유지",
        data={"score_cutoff": cfg.score_cutoff, "final_count": len(final_results), "context_limit": cfg.context_limit},
    )

    openai_usage_summary = build_openai_usage_summary(
        intent_meta=intent_meta,
        planning_meta=planning_meta,
        vector_search_ran=True,
        openai_client_present=openai_present,
    )
    return {
        "intent": intent,
        "language": language,
        "planned_queries": planned_queries,
        "per_query_results": searches,
        "fused_results": fused,
        "final_results": final_results,
        "llm_context": llm_context,
        "step_logs": step_logs,
        "response_mode": "retrieval",
        "heuristic_answer": "",
        "openai_usage_summary": openai_usage_summary,
    }

