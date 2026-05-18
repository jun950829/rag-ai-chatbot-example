from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.retrieval.retrieval import retrieve_context


def intent_to_entity_scope(intent: str) -> str:
    """의도 라벨 → pgvector 검색 범위 (company / product / all)."""
    i = (intent or "").strip().lower()
    if i in ("company_query", "company", "exhibitor"):
        return "company"
    if i in ("product_query", "product", "item"):
        return "product"
    return "all"


def _language_to_search_lang(language: str) -> str:
    return "eng" if (language or "").strip().lower() == "en" else "kor"


async def retrieve_answer_context(
    *,
    query: str,
    intent: str,
    session_id: str,
    search_queries: list[str] | None = None,
    language: str = "ko",
) -> tuple[str, list[dict[str, Any]]]:
    """(LLM용 컨텍스트 문자열, 제안 카드용 검색 행)."""
    _ = session_id
    st = get_settings()
    entity_scope = intent_to_entity_scope(intent)
    return await retrieve_context(
        query=query,
        search_queries=search_queries,
        model_id=st.retrieval_model_id,
        device=st.retrieval_device,
        embedding_remote_base_url=st.embedding_service_url or None,
        final_top_k=st.retrieval_top_k,
        entity_scope=entity_scope,
        search_lang=_language_to_search_lang(language),
    )
