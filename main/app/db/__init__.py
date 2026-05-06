"""DB 패키지 진입점.

중요:
- 과거 코드가 `from app.db import Base, engine, get_session` 형태를 사용하므로 호환을 유지한다.
- 신규 프로덕션 레이어는 `app.db.session`의 AsyncSession을 사용한다.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import Base
from app.db.sync_url import to_sync_postgres_dsn

settings = get_settings()

# 레거시 동기 엔진 (기존 ingest/파이프라인 호환)
engine = create_engine(
    to_sync_postgres_dsn(settings.database_url),
    future=True,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


def get_session() -> Generator[Session, None, None]:
    """동기 Session 제공 (레거시 경로 호환)."""

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def __getattr__(name: str):
    """Async 세션/async 엔진은 지연 로드.

    ``from app.db import Base`` 만으로 AsyncEngine 이 생성되지 않게 한다
    (동기 RAG 검색 경로와의 greenlet 충돌 방지).
    """
    if name in ("AsyncSessionLocal", "async_engine", "get_async_session"):
        import app.db.session as _session_mod

        return getattr(_session_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # ORM base
    "Base",
    # legacy sync
    "engine",
    "get_session",
    # async (production)
    "async_engine",
    "AsyncSessionLocal",
    "get_async_session",
]

