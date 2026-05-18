"""벡터 검색 오케스트레이션 — 단계 호출만 나열 (구현은 ``services/vsearch_*``)."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from app.core.logger import get_logger
from app.observability.tracing import trace_stage
from app.orchestration.services import vsearch_rag_path as _rag
from app.orchestration.services.vsearch_bootstrap import (
    build_async_openai_client,
    parse_query_markers,
    validate_vector_search_inputs,
)
from app.orchestration.services.vsearch_gates import (
    try_direct_external_id_response,
    try_faq_gate_response,
)
from app.orchestration.services.vsearch_persist_response import (
    append_assistant_to_memory,
    build_vector_search_response_dict,
    persist_session_messages,
)
from app.orchestration.vector_search_context import VectorSearchContext

logger = get_logger(__name__)


async def run_vector_search_flow(ctx: VectorSearchContext) -> dict[str, Any]:
    validate_vector_search_inputs(chunk_type=ctx.chunk_type, answer_mode=ctx.answer_mode)
    ctx.t_search_wall0 = perf_counter()
    async with trace_stage("vector_search.normalize_query"):
        q, ext, typ, lang = parse_query_markers(ctx.query)
        ctx.query, ctx.ext_marker, ctx.payload_typ, ctx.payload_lang = q, ext, typ, lang
    async with trace_stage("vector_search.openai_client"):
        ctx.openai_client, ctx.key = build_async_openai_client(
            openai_api_key=ctx.openai_api_key, openai_base_url=ctx.openai_base_url
        )
    logger.info(
        "[search] start query_preview=%s top_k=%s chunk_type=%s answer_mode=%s session=%s",
        (ctx.query or "")[:120],
        ctx.top_k,
        ctx.chunk_type,
        ctx.answer_mode,
        (ctx.session_id or "")[:32] or "-",
    )
    async with trace_stage("vector_search.faq_gate"):
        early_faq = await try_faq_gate_response(query=ctx.query, faq_only=ctx.faq_only, faq_user=ctx.faq_user)
    if early_faq is not None:
        return early_faq
    async with trace_stage("vector_search.direct_lookup"):
        early_direct = await try_direct_external_id_response(
            query=ctx.query,
            ext_marker=ctx.ext_marker,
            payload_typ=ctx.payload_typ,
            payload_lang=ctx.payload_lang,
            top_k=ctx.top_k,
            chunk_type=ctx.chunk_type,
            answer_mode=ctx.answer_mode,
            openai_base_url=ctx.openai_base_url,
            key=ctx.key,
        )
    if early_direct is not None:
        return early_direct
    async with trace_stage("vector_search.session_hydrate"):
        await _rag.hydrate_session_branch(ctx)
    async with trace_stage("vector_search.retrieval_tuning"):
        _rag.resolve_retrieval_tuning(ctx)
    logger.info("[search] retrieval_pipeline ... tuning=%s", ctx.tuning_meta)
    async with trace_stage("vector_search.retrieval_execute"):
        await _rag.run_retrieval_and_postprocess(ctx)
    _rag.log_retrieval_completed(ctx)
    async with trace_stage("vector_search.answer"):
        await _rag.build_answer_and_meta(ctx)
    _rag.append_answer_step_log(ctx)
    async with trace_stage("vector_search.suggestions"):
        await _rag.build_suggestion_cards(ctx)
    append_assistant_to_memory(ctx)
    async with trace_stage("vector_search.persist"):
        await persist_session_messages(ctx)
    return build_vector_search_response_dict(ctx)
