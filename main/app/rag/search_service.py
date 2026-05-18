"""RAG 벡터 검색 공개 API.

구현·단계별 로직은 ``app.orchestration.vector_search`` 및 ``services/vsearch_*`` 에 있다.
"""

from __future__ import annotations

from typing import Any

from app.orchestration.vector_search import run_vector_search_flow
from app.orchestration.vector_search_context import VectorSearchContext
from app.rag.retrieval.memory import ConversationMemory


async def run_vector_search(
    *,
    query: str,
    model_id: str,
    device: str | None,
    top_k: int,
    chunk_type: str,
    answer_mode: str,
    openai_model: str,
    openai_api_key: str,
    openai_base_url: str,
    embedding_remote_base_url: str | None,
    memory: ConversationMemory | None = None,
    session_id: str | None = None,
    faq_only: bool = False,
    faq_user: str | None = None,
    intent_use_openai: bool | None = None,
    retrieval_min_queries: int | None = None,
    retrieval_max_queries: int | None = None,
    retrieval_score_cutoff: float | None = None,
    retrieval_evidence_ratio: float | None = None,
    retrieval_rrf_k: int | None = None,
    retrieval_context_limit: int | None = None,
    retrieval_top_k_per_query: int | None = None,
) -> dict[str, Any]:
    ctx = VectorSearchContext(
        query=query,
        model_id=model_id,
        device=device,
        top_k=top_k,
        chunk_type=chunk_type,
        answer_mode=answer_mode,
        openai_model=openai_model,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
        embedding_remote_base_url=embedding_remote_base_url,
        memory=memory,
        session_id=session_id,
        faq_only=faq_only,
        faq_user=faq_user,
        intent_use_openai=intent_use_openai,
        retrieval_min_queries=retrieval_min_queries,
        retrieval_max_queries=retrieval_max_queries,
        retrieval_score_cutoff=retrieval_score_cutoff,
        retrieval_evidence_ratio=retrieval_evidence_ratio,
        retrieval_rrf_k=retrieval_rrf_k,
        retrieval_context_limit=retrieval_context_limit,
        retrieval_top_k_per_query=retrieval_top_k_per_query,
    )
    return await run_vector_search_flow(ctx)
