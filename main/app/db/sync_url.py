"""동기 SQLAlchemy 엔진용 Postgres DSN 정규화."""

from __future__ import annotations


def to_sync_postgres_dsn(url: str) -> str:
    """async 전용 드라이버 URL을 ``create_engine`` / ``Session`` 이 쓸 수 있게 바꾼다.

    ``DATABASE_URL`` 이 ``postgresql+asyncpg://`` 인 배포에서 ingest 등 동기 경로가
    ``MissingGreenlet`` 없이 붙도록 ``postgresql+psycopg://`` 로 맞춘다.
    """
    u = url.strip()
    for async_head, sync_head in (
        ("postgresql+asyncpg://", "postgresql+psycopg://"),
        ("postgres+asyncpg://", "postgresql+psycopg://"),
        ("postgresql+psycopg_async://", "postgresql+psycopg://"),
    ):
        if u.startswith(async_head):
            return sync_head + u[len(async_head) :]
    return u
