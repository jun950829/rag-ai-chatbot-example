"""메모리 턴 기록·세션 DB 저장·최종 HTTP dict 조립."""

from __future__ import annotations

import asyncio
from functools import partial

from app.core.logger import get_logger
from app.db.conversation_sync_store import sync_save_assistant_message, sync_save_user_message
from app.orchestration.services.vsearch_rag_path import _DEFAULT_MEMORY
from app.orchestration.vector_search_context import VectorSearchContext
from app.rag.pipeline import engine as sync_search_db_engine

logger = get_logger(__name__)


def append_assistant_to_memory(ctx: VectorSearchContext) -> None:
    if ctx.memory is None:
        _DEFAULT_MEMORY.add("assistant", ctx.answer_korean)
    else:
        ctx.memory.add("assistant", ctx.answer_korean)


async def persist_session_messages(ctx: VectorSearchContext) -> None:
    if ctx.session_uuid_for_save is None:
        return
    rp = ctx.retrieval_payload
    assert rp is not None
    pip_intent = str(rp["intent"])
    pip_fu = bool(rp.get("is_dialog_followup", False))
    pip_topic = rp.get("retrieval_topic")
    if pip_topic is None:
        pip_topic = "all"
    pip_topic = str(pip_topic).strip().lower()
    if ctx.fu_state is not None:
        _heu_fu, fu_conf, _ = ctx.fu_state
        conf = float(max(fu_conf, 0.55 if pip_fu else 0.35))
    else:
        conf = 0.85

    try:
        await asyncio.to_thread(
            partial(
                sync_save_user_message,
                engine=sync_search_db_engine,
                session_pk=ctx.session_uuid_for_save,
                content=ctx.query,
                intent=pip_intent,
                is_followup=pip_fu,
                confidence=conf,
                retrieval_topic=pip_topic,
            )
        )
    except Exception:
        logger.exception("[search] sync_save_user_message failed (answer still returned)")

    try:
        await asyncio.to_thread(
            partial(
                sync_save_assistant_message,
                engine=sync_search_db_engine,
                session_pk=ctx.session_uuid_for_save,
                content=ctx.answer_korean,
            )
        )
    except Exception:
        logger.exception("[search] sync_save_assistant_message failed (answer still returned)")


def build_vector_search_response_dict(ctx: VectorSearchContext) -> dict:
    rp = ctx.retrieval_payload
    assert rp is not None
    return {
        "query": ctx.query,
        "top_k": max(1, int(ctx.top_k)),
        "lang": rp["language"],
        "chunk_type": ctx.chunk_type,
        "count": len(ctx.results),
        "retrieval": {
            "intent": rp["intent"],
            "retrieval_topic": rp.get("retrieval_topic"),
            "is_dialog_followup": rp.get("is_dialog_followup"),
            "language": rp["language"],
            "planned_queries": rp["planned_queries"],
            "llm_context": rp["llm_context"],
            "rrf_candidates": len(rp["fused_results"]),
            "step_logs": ctx.step_logs,
            "response_mode": ctx.response_mode,
            "embedding_remote_base_url": (ctx.embedding_remote_base_url or "").strip() or None,
            "openai_usage_summary": ctx.openai_usage,
            "tuning_applied": ctx.tuning_meta,
        },
        "answer": ctx.answer_korean,
        "answer_meta": ctx.answer_meta,
        "results": ctx.results,
        "cards": ctx.suggestion_cards,
        "follow_up_questions": ctx.followups_rag,
        "answer_korean": ctx.answer_korean,
        "suggestion_cards": ctx.suggestion_cards,
    }
