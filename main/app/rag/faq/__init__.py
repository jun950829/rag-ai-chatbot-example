"""FAQ 전용 검색 엔진 패키지.

주의:
- FAQ 검색에서는 pgvector/embedding/semantic retrieval 를 절대 사용하지 않는다.
- PostgreSQL Full Text Search + pg_trgm + alias + 문자열 기반 rerank 로만 동작한다.
"""

from .service import FaqSearchService

__all__ = ["FaqSearchService"]

