"""FAQ 검색용 문자열 정규화 모듈.

new_main/tests 가 기대하는 API:
- ``normalize_faq_query``
"""

from __future__ import annotations

from app.rag.faq_normalizer import normalize_faq_query as _normalize_faq_query_dict


def normalize_faq_query(text: str) -> str:
    d = _normalize_faq_query_dict(text or "")
    return str(d.get("canonical") or d.get("normalized") or "").strip()


def normalize_faq_text(text: str) -> str:
    return normalize_faq_query(text)

