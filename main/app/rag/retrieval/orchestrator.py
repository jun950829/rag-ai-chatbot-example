from __future__ import annotations

import asyncio
import logging
from functools import partial
from time import perf_counter
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
    entity_scope_from_retrieval_topic,
    normalize_user_query,
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
    intent_use_openai: bool = True,
    embedding_remote_base_url: str | None = None,
    memory: ConversationMemory | None = None,
) -> dict[str, Any]:
    cfg = config or RetrievalConfig()
    raw_query = (query or "")
    normalized_query = normalize_user_query(raw_query)
    if not normalized_query:
        raise ValueError("query is empty")
    step_logs: list[dict[str, Any]] = []
    t0 = perf_counter()
    t_prev = t0

    def _append_step(*, step: int, title: str, detail: str, data: dict[str, Any] | None = None) -> None:
        nonlocal t_prev
        now = perf_counter()
        step_ms = int((now - t_prev) * 1000)
        total_ms = int((now - t0) * 1000)
        payload = dict(data or {})
        payload["step_elapsed_ms"] = step_ms
        payload["pipeline_elapsed_ms"] = total_ms
        append_step(
            step_logs,
            step=step,
            title=title,
            detail=f"{detail} ({step_ms}ms, total={total_ms}ms)",
            data=payload,
        )
        t_prev = now

    _append_step(
        step=0,
        title="입력 정규화",
        detail="공백/특수문자를 정리해 의도분류·플래너 공통 입력으로 변환",
        data={"raw_query": raw_query, "normalized_query": normalized_query},
    )
    if memory is not None:
        memory.add("user", normalized_query)

    logger.info("[retrieval][step1] intent classification started (intent_use_openai=%s)", intent_use_openai)
    intent_client = openai_client if intent_use_openai else None
    intent, intent_meta = await classify_intent_v2(
        message=normalized_query,
        has_history=has_history,
        openai_client=intent_client,
        model=intent_model,
        memory=memory,
    )
    if intent not in INTENT_LABELS:
        intent = "general"
    # --- 단계 1-b: 검색 축·후행 플래그 추출 (응답·DB·플래너에서 공통 사용) ---
    _rt_raw = intent_meta.get("retrieval_topic")
    retrieval_topic = (
        str(_rt_raw).strip().lower()
        if isinstance(_rt_raw, str) and str(_rt_raw).strip().lower() in {"company", "product", "all"}
        else "all"
    )
    is_dialog_followup = bool(intent_meta.get("is_dialog_followup", False))
    classification_source = str(intent_meta.get("source", "unknown"))
    used_openai = _intent_meta_used_openai(intent_meta)
    # 휴리스틱 단계에서 바로 확정됐는지 vs OpenAI 7단계까지 갔는지 (trace/UI에서 구분)
    intent_decider: str = "openai" if used_openai else "heuristic"

    llm_path_note = ""
    if not intent_use_openai:
        llm_path_note = (
            " LLM의도분류: 요청 설정(intent_use_openai=false)으로 Chat Completions 호출 없음 — 휴리스틱·규칙만 사용."
        )
    elif intent_client is None:
        llm_path_note = (
            " LLM의도분류: 설정은 켜져 있으나 OpenAI 클라이언트 없음(예: OPENAI_API_KEY 미설정) — 휴리스틱만 사용."
        )
    elif used_openai:
        if classification_source.startswith("openai_rescue"):
            llm_path_note = (
                f" LLM의도분류(구제): 휴리스틱이 general/not_related/FAQ 로 보낼 뻔했으나 "
                f"OpenAI가 검색 의도로 보정함 ({classification_source}, model={intent_model})."
            )
        else:
            llm_path_note = (
                f" LLM의도분류: OpenAI로 intent/topic 한 줄 파싱 적용됨 (model={intent_model})."
            )
    else:
        llm_path_note = (
            " LLM의도분류: 클라이언트는 있으나 휴리스틱 단계에서 의도가 확정되어 "
            "(또는 OpenAI 재시도 필요 없음으로) 검색 분류용 Chat 호출 없음."
        )

    classification_kind = "heuristic"
    if used_openai:
        classification_kind = (
            "openai_rescue" if classification_source.startswith("openai_rescue") else "openai_fallback"
        )

    decider_ko = "OpenAI(Chat API)" if used_openai else "휴리스틱(규칙·키워드)"
    detail_step1 = (
        f"intent={intent}, 검색축={retrieval_topic or '-'}, 후행={is_dialog_followup}. "
        f"최종판정={decider_ko}, 내부 source={classification_source}.{llm_path_note}"
    )

    logger.info(
        "[retrieval][step1] intent=%s retrieval_topic=%s followup=%s decider=%s source=%s intent_use_openai=%s client=%s",
        intent,
        retrieval_topic,
        is_dialog_followup,
        intent_decider,
        classification_source,
        intent_use_openai,
        "yes" if intent_client is not None else "no",
    )
    _append_step(
        step=1,
        title="의도 분류",
        detail=detail_step1,
        data={
            "intent": intent,
            "retrieval_topic": retrieval_topic,
            "is_dialog_followup": is_dialog_followup,
            "query": normalized_query,
            "classification_meta": intent_meta,
            "intent_decider": intent_decider,
            "classification_source": classification_source,
            "classification_kind": classification_kind,
            "openai_used_for_intent": used_openai,
            "intent_model": intent_model if intent_client is not None else None,
            "intent_use_openai_param": intent_use_openai,
            "openai_client_available": intent_client is not None,
        },
    )

    logger.info("[retrieval][step2] language detection started")
    language = detect_language(normalized_query)
    if language not in LANGUAGE_LABELS:
        language = "ko"
    logger.info("[retrieval][step2] language=%s", language)
    _append_step(step=2, title="언어 감지", detail=f"입력 언어를 '{language}'로 판정", data={"language": language})

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
        _append_step(
            step=3,
            title="쿼리 계획 생략",
            detail="비검색 의도로 OpenAI 쿼리 플래너·다중 쿼리 생성을 건너뜀",
            data={"skipped": True, "intent": intent, "query_planner_meta": planning_meta["planner_meta"]},
        )
    else:
        # --- 단계 3-b: 플래너에는 검색 축(retrieval_topic)을 넘겨 follow-up+제품 확장을 태운다 ---
        rt_for_plan = retrieval_topic if retrieval_topic in {"company", "product", "all"} else "all"
        planned_queries, planning_meta = await generate_search_plan_v2(
            message=normalized_query,
            language=language,
            intent=intent,
            retrieval_topic=rt_for_plan,
            is_dialog_followup=is_dialog_followup,
            openai_client=openai_client,
            openai_model=intent_model,
            min_queries=cfg.min_queries,
            max_queries=cfg.max_queries,
        )
        logger.info("[retrieval][step3] planned_queries=%s", planned_queries)
        planner_src = str((planning_meta.get("planner_meta") or {}).get("source", ""))
        _append_step(
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
        _append_step(
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
            "retrieval_topic": retrieval_topic,  # 항상 company|product|all 문자열
            "is_dialog_followup": is_dialog_followup,
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
    # --- 단계 4: entity_scope는 라우팅 intent가 아니라 retrieval_topic 기준으로 결정한다 ---
    entity_scope = entity_scope_from_retrieval_topic(retrieval_topic)
    # asyncio 루프 스레드에서 동기 psycopg2/pipeline 검색을 직접 호출하면 MissingGreenlet 이 날 수 있어 워커 스레드로 격리
    searches = await asyncio.to_thread(
        partial(
            semantic_search_multi_query,
            queries=planned_queries,
            model_id=cfg.model_id,
            device=cfg.device,
            top_k_per_query=cfg.top_k_per_query,
            lang=search_lang,
            evidence_ratio=cfg.evidence_ratio,
            embedding_remote_base_url=embedding_remote_base_url,
            entity_scope=entity_scope,
        )
    )
    query_summaries: list[dict[str, Any]] = []
    for bucket in searches:
        rows = bucket["results"]
        query_summaries.append({"query": bucket["query"], "count": len(rows), "top_preview": [r.get("content", "")[:80] for r in rows[:2]]})
    _append_step(
        step=4,
        title="의미 검색",
        detail="쿼리별 profile/evidence 검색 수행",
        data={"query_summaries": query_summaries, "search_lang": search_lang, "entity_scope": entity_scope},
    )

    fused = rrf_fuse(searches, rrf_k=cfg.rrf_k)
    _append_step(
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
    _append_step(
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
        "retrieval_topic": retrieval_topic,
        "is_dialog_followup": is_dialog_followup,
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

