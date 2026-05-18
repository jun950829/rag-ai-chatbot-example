"""카드(external_id) 클릭 시 LLM 메시지 — 일반 RAG와 동일한 ``build_messages_for_rag_stream`` 사용."""

from __future__ import annotations

from typing import Any

from app.prompt.retrieval_answer import build_messages_for_rag_stream


def build_card_detail_messages(
    *, evidence: str, entity_kind: str | None, language: str = "ko"
) -> list[dict[str, Any]]:
    """DB에서 모은 발췌문을 ``context`` 로 두고, 검색 응답과 같은 시스템·형식 규칙을 적용한다."""
    kind = (entity_kind or "").strip().lower()
    intent = "product_query" if kind == "exhibit_item" else "company_query"
    lang = (language or "ko").strip().lower()
    if lang == "en":
        query = (
            "The user selected this item from the search result cards. "
            "Introduce and summarise it based solely on the reference material."
        )
    else:
        query = (
            "사용자가 검색 결과 카드에서 이 항목을 선택했다. "
            "참고 자료만 근거로 항목을 소개·요약해 줘."
        )
    return build_messages_for_rag_stream(query=query, context=evidence, intent=intent, language=lang)
