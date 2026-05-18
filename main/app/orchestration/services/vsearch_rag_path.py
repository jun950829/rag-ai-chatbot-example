"""세션 hydrate → tuning → 의미 검색 실행 → 후처리 → 답안 스켈레톤."""

from __future__ import annotations

import asyncio
from functools import partial
from time import perf_counter
from typing import Any

from app.core.config import get_settings
from app.core.logger import get_logger
from app.db.conversation_sync_store import sync_load_memory_for_session
from app.orchestration.services.vsearch_answer_llm import (
    ANSWER_OPENAI_MODEL,
    generate_general_answer_with_openai,
    generate_korean_answer_with_openai,
)
from app.orchestration.services.vsearch_bootstrap import clamp01
from app.orchestration.vector_search_context import VectorSearchContext
from app.rag.entity_enrichment import enrich_results_with_entity_detail_sync, merged_entity_context
from app.rag.pipeline import build_korean_search_answer, engine as sync_search_db_engine, sanitize_rag_results_for_user
from app.rag.retrieval import RetrievalConfig, execute_retrieval_pipeline
from app.rag.retrieval.search import apply_cutoff_and_build_context
from app.rag.suggestion_cards import build_retrieval_suggestion_cards

from app.rag.retrieval.memory import ConversationMemory

logger = get_logger(__name__)
_DEFAULT_MEMORY = ConversationMemory(max_turns=5)


async def hydrate_session_branch(ctx: VectorSearchContext) -> None:
    if not ctx.session_id:
        ctx.db_memory = ctx.memory
        ctx.has_history = False
        ctx.session_uuid_for_save = None
        ctx.fu_state = None
        return
    from app.services import is_followup_v2

    db_memory, session_uuid_for_save = await asyncio.to_thread(
        partial(
            sync_load_memory_for_session,
            engine=sync_search_db_engine,
            browser_session_id=ctx.session_id,
            limit=5,
        )
    )
    ctx.db_memory = db_memory
    ctx.session_uuid_for_save = session_uuid_for_save
    ctx.has_history = len(db_memory.get_recent()) > 0
    hist_texts = [m.get("message", "") for m in db_memory.get_recent()][-5:]
    is_fu, fu_conf, fu_meta = is_followup_v2(current=ctx.query, history=hist_texts)
    ctx.fu_state = (is_fu, fu_conf, fu_meta)


def resolve_retrieval_tuning(ctx: VectorSearchContext) -> None:
    st = get_settings()
    ctx.i_openai = st.retrieval_intent_use_openai if ctx.intent_use_openai is None else ctx.intent_use_openai
    min_q = st.retrieval_min_queries if ctx.retrieval_min_queries is None else int(ctx.retrieval_min_queries)
    max_q = st.retrieval_max_queries if ctx.retrieval_max_queries is None else int(ctx.retrieval_max_queries)
    ctx.min_q = max(1, min_q)
    ctx.max_q = max(ctx.min_q, max_q)
    ctx.sc = float(st.retrieval_score_cutoff if ctx.retrieval_score_cutoff is None else ctx.retrieval_score_cutoff)
    ctx.er = clamp01(float(st.retrieval_evidence_ratio if ctx.retrieval_evidence_ratio is None else ctx.retrieval_evidence_ratio))
    ctx.rk = max(1, int(st.retrieval_rrf_k if ctx.retrieval_rrf_k is None else ctx.retrieval_rrf_k))
    ctx.cl = max(1, int(st.retrieval_context_limit if ctx.retrieval_context_limit is None else ctx.retrieval_context_limit))
    tkpq_raw = st.retrieval_top_k_per_query if ctx.retrieval_top_k_per_query is None else ctx.retrieval_top_k_per_query
    ctx.tkpq = max(6, int(ctx.top_k)) if tkpq_raw is None else max(1, int(tkpq_raw))
    ctx.tuning_meta = {
        "intent_use_openai": ctx.i_openai,
        "min_queries": ctx.min_q,
        "max_queries": ctx.max_q,
        "score_cutoff": ctx.sc,
        "evidence_ratio": ctx.er,
        "rrf_k": ctx.rk,
        "context_limit": ctx.cl,
        "top_k_per_query": ctx.tkpq,
        "final_top_k": max(1, int(ctx.top_k)),
    }


async def run_retrieval_and_postprocess(ctx: VectorSearchContext) -> None:
    mem = ctx.db_memory or _DEFAULT_MEMORY
    payload = await execute_retrieval_pipeline(
        ctx.query,
        config=RetrievalConfig(
            model_id=ctx.model_id,
            device=ctx.device or None,
            top_k_per_query=ctx.tkpq,
            final_top_k=max(1, int(ctx.top_k)),
            score_cutoff=ctx.sc,
            evidence_ratio=ctx.er,
            min_queries=ctx.min_q,
            max_queries=ctx.max_q,
            rrf_k=ctx.rk,
            context_limit=ctx.cl,
        ),
        openai_client=ctx.openai_client,
        intent_model=ctx.openai_model,
        intent_use_openai=ctx.i_openai,
        embedding_remote_base_url=ctx.embedding_remote_base_url,
        has_history=ctx.has_history,
        memory=mem,
    )
    ctx.retrieval_payload = payload
    results = payload["final_results"]
    try:
        results = await asyncio.to_thread(
            enrich_results_with_entity_detail_sync,
            engine=sync_search_db_engine,
            results=results,
            language=str(payload.get("language") or "ko"),
        )
    except Exception:
        logger.exception("[ENTITY_ENRICH] failed (answer still returned)")

    st = get_settings()
    u_floor = float(st.retrieval_user_answer_min_score or 0.0)
    results = sanitize_rag_results_for_user(results, min_best_score=u_floor)
    payload["final_results"] = results
    payload["merged_entities"] = merged_entity_context(results)
    try:
        _, payload["llm_context"] = apply_cutoff_and_build_context(
            results,
            score_cutoff=0.0,
            final_top_k=max(1, len(results)),
            context_limit=max(1, ctx.cl),
        )
    except Exception:
        logger.exception("[rag_sanitize] llm_context 재구성 실패 (기존 컨텍스트 유지)")
    ctx.results = results


def log_retrieval_completed(ctx: VectorSearchContext) -> None:
    rp = ctx.retrieval_payload
    assert rp is not None
    ctx.response_mode = rp.get("response_mode", "retrieval")
    logger.info(
        "[retrieval] done mode=%s intent=%s topic=%s followup=%s language=%s queries=%d results=%d",
        ctx.response_mode,
        rp["intent"],
        rp.get("retrieval_topic"),
        rp.get("is_dialog_followup"),
        rp["language"],
        len(rp["planned_queries"]),
        len(ctx.results),
    )


async def build_answer_and_meta(ctx: VectorSearchContext) -> None:
    rp = ctx.retrieval_payload
    assert rp is not None
    results = ctx.results
    response_mode = ctx.response_mode
    if response_mode == "intent_heuristic":
        ctx.answer_korean = rp.get("heuristic_answer") or "요청 의도에 맞춘 안내 응답입니다."
        ctx.answer_meta = {"mode": "intent_heuristic"}
    elif response_mode == "general_chat":
        ctx.answer_korean = rp.get("heuristic_answer") or "일반 대화로 이해했습니다."
        ctx.answer_meta = {"mode": "general_chat_template"}
    else:
        ctx.answer_korean = build_korean_search_answer(
            ctx.query,
            results,
            intent=str(rp["intent"]),
            retrieval_topic=rp.get("retrieval_topic"),
            language=str(rp.get("language") or "ko"),
        )
        ctx.answer_meta = {"mode": "template"}

    if response_mode == "retrieval" and ctx.answer_mode == "openai":
        if not ctx.key:
            logger.warning("[search] openai requested but OPENAI_API_KEY missing → template")
            ctx.answer_meta = {
                "mode": "template_fallback",
                "error": "OPENAI_API_KEY is not set",
                "requested_mode": "openai",
            }
        else:
            try:
                ctx.answer_korean = await generate_korean_answer_with_openai(
                    query=ctx.query,
                    results=results,
                    api_key=ctx.key,
                    base_url=(ctx.openai_base_url or "").strip(),
                    model=ANSWER_OPENAI_MODEL,
                    intent=rp["intent"],
                    language=rp["language"],
                    retrieval_topic=rp.get("retrieval_topic"),
                    is_dialog_followup=bool(rp.get("is_dialog_followup", False)),
                )
                ctx.answer_meta = {"mode": "openai", "model": ANSWER_OPENAI_MODEL}
            except Exception as e:  # noqa: BLE001
                logger.exception("[search] openai answer generation failed: %s", e)
                ctx.answer_korean = build_korean_search_answer(
                    ctx.query,
                    results,
                    intent=str(rp["intent"]),
                    retrieval_topic=rp.get("retrieval_topic"),
                    language=str(rp.get("language") or "ko"),
                )
                ctx.answer_meta = {"mode": "template_fallback", "error": str(e), "requested_mode": "openai"}
    elif response_mode == "general_chat":
        if not ctx.key:
            ctx.answer_meta = {
                "mode": "general_chat_template_fallback",
                "error": "OPENAI_API_KEY is not set",
                "requested_mode": "openai_for_general",
            }
        else:
            try:
                logger.info("[answer] general_chat openai …")
                ctx.answer_korean = await generate_general_answer_with_openai(
                    query=ctx.query,
                    api_key=ctx.key,
                    base_url=(ctx.openai_base_url or "").strip(),
                    model=ANSWER_OPENAI_MODEL,
                    language=rp["language"],
                )
                ctx.answer_meta = {"mode": "general_chat_openai", "model": ANSWER_OPENAI_MODEL}
                logger.info("[answer] general_chat openai done chars=%d", len(ctx.answer_korean or ""))
            except Exception as e:  # noqa: BLE001
                logger.exception("[answer] general_chat openai failed: %s", e)
                ctx.answer_meta = {
                    "mode": "general_chat_template_fallback",
                    "error": str(e),
                    "requested_mode": "openai_for_general",
                }


def append_answer_step_log(ctx: VectorSearchContext) -> None:
    rp = ctx.retrieval_payload
    assert rp is not None
    openai_usage = dict(rp.get("openai_usage_summary") or {})
    openai_usage["answer_generation_used_openai"] = ctx.answer_meta.get("mode") in (
        "openai",
        "general_chat_openai",
    )
    openai_usage["answer_generation_mode"] = ctx.answer_meta.get("mode")
    if ctx.answer_meta.get("model"):
        openai_usage["answer_generation_model"] = ctx.answer_meta.get("model")
    answer_step_log = {
        "step": 99,
        "title": "최종 답변 생성",
        "detail": (
            f"answer_mode={ctx.answer_mode}, response_mode={ctx.response_mode}, "
            f"applied_mode={ctx.answer_meta.get('mode', 'unknown')}"
        ),
        "data": {
            "requested_answer_mode": ctx.answer_mode,
            "response_mode": ctx.response_mode,
            "answer_meta": ctx.answer_meta,
            "openai_usage_summary": openai_usage,
            "search_wall_ms": int((perf_counter() - ctx.t_search_wall0) * 1000),
        },
    }
    step_logs = list(rp.get("step_logs", []))
    step_logs.append(answer_step_log)
    ctx.step_logs = step_logs
    ctx.openai_usage = openai_usage


async def build_suggestion_cards(ctx: VectorSearchContext) -> None:
    rp = ctx.retrieval_payload
    assert rp is not None
    if ctx.response_mode == "retrieval" and ctx.results:
        try:
            ctx.suggestion_cards = await build_retrieval_suggestion_cards(
                ctx.results, language=str(rp.get("language") or "ko")
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[search] suggestion_cards skipped: %s", e)
            ctx.suggestion_cards = []
        ctx.followups_rag = []
    else:
        ctx.suggestion_cards = []
        ctx.followups_rag = []
