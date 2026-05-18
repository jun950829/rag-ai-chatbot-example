"""임베딩 서버(또는 로컬 모델) 호출 진입점. 구현은 ``app.rag.pipeline`` 에 위임."""

from __future__ import annotations

from app.rag.pipeline import embed_queries_text as embed_queries_text
from app.rag.pipeline import embed_query_text as embed_query_text

__all__ = ["embed_query_text", "embed_queries_text"]
