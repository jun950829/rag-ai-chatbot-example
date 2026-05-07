"""FAQ 검색용 문자열 정규화 모듈.

중요:
- FAQ는 임베딩/pgvector/LLM 없이, PostgreSQL 검색 + deterministic normalize로만 처리한다.
- 사용자 표현 다양성은 canonical topic으로 압축한다(`app.rag.faq_synonyms`).
"""

from __future__ import annotations

from app.rag.faq_normalizer import normalize_faq_query as _normalize_faq_query_dict


def normalize_faq_query(text: str) -> str:
    """FAQ 검색용 쿼리 정규화.

    - 소문자화
    - 특수문자 제거(공백 치환)
    - 연속 공백 정리
    - canonical mapping 적용
    """

    d = _normalize_faq_query_dict(text or "")
    return str(d.get("canonical") or d.get("normalized") or "").strip()


def normalize_faq_text(text: str) -> str:
    """DB 문서(FAQ 질문/alias) 정규화용.

    현재는 query와 동일 규칙을 사용한다.
    """

    return normalize_faq_query(text)

