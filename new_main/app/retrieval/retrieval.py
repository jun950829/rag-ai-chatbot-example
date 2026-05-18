"""Retrieval main — 흐름만 보여주는 explicit pipeline.

원래 프로젝트의 semantic(pgvector) 검색 + RRF + cutoff/context 빌드를 포팅한다.
"""

from __future__ import annotations

from typing import Any

from app.observability.tracing import trace_stage
from app.retrieval.retrieval_steps import (
    apply_cutoff_and_build_context,
    rrf_fuse,
    select_rows_for_suggestion_cards,
    semantic_search_multi_query_async,
)


async def retrieve_context(
    *,
    query: str,
    model_id: str,
    device: str | None,
    embedding_remote_base_url: str | None,
    search_queries: list[str] | None = None,
    top_k_per_query: int = 10,
    final_top_k: int = 8,
    score_cutoff: float = 0.0,
    evidence_ratio: float = 0.35,
    rrf_k: int = 60,
    context_limit: int = 8,
    search_lang: str = "kor",
    entity_scope: str = "all",
) -> tuple[str, list[dict[str, Any]]]:
    async with trace_stage("retrieval.rewrite"):
        rewritten = query.strip()

    async with trace_stage("retrieval.multi_query"):
        if search_queries:
            queries = [str(q or "").strip() for q in search_queries if str(q or "").strip()]
        else:
            queries = []
        if not queries:
            queries = [rewritten] if rewritten else []

    async with trace_stage("retrieval.vector_search"):
        searches = await semantic_search_multi_query_async(
            queries=queries,
            model_id=model_id,
            device=device,
            top_k_per_query=top_k_per_query,
            lang=search_lang,
            evidence_ratio=evidence_ratio,
            embedding_remote_base_url=embedding_remote_base_url,
            entity_scope=entity_scope,
        )

    async with trace_stage("retrieval.rrf"):
        fused = rrf_fuse(searches, rrf_k=rrf_k)

    card_rows = select_rows_for_suggestion_cards(
        fused,
        score_cutoff=score_cutoff,
        final_top_k=final_top_k,
    )

    async with trace_stage("retrieval.cutoff_context"):
        _merged_rows, context = apply_cutoff_and_build_context(
            fused,
            score_cutoff=score_cutoff,
            final_top_k=final_top_k,
            context_limit=context_limit,
        )

    async with trace_stage("retrieval.compress"):
        return context, card_rows
