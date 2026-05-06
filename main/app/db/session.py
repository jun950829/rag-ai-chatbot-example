"""DB 세션/엔진 관리 (Async).

요구사항:
- async 지원
- 쿼리 최소화, 커넥션 풀 재사용

주의:
- 모듈 import 시점에 AsyncEngine 을 만들지 않는다. ``app.db`` 가 Base/get_session 때문에
  항상 로드되는데, 그때 동기 검색(pipeline) 과 같은 프로세스에서 asyncpg 엔진이 초기화되면
  MissingGreenlet 등이 발생할 수 있다.
"""

from __future__ import annotations

import typing
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.sync_url import to_async_postgres_url


def _create_async_engine() -> AsyncEngine:
    """설정 기반으로 AsyncEngine 생성.

    - SQLAlchemy 2.x + async psycopg (async 드라이버)
    - pool_pre_ping으로 죽은 커넥션 자동 감지
    """

    settings = get_settings()
    return create_async_engine(
        to_async_postgres_url(settings.database_url),
        pool_pre_ping=True,
        echo=False,
    )


_async_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def _ensure_async() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Async 엔진·세션팩토리 단일 초기화."""
    global _async_engine, _async_session_factory
    if _async_session_factory is None:
        _async_engine = _create_async_engine()
        _async_session_factory = async_sessionmaker(
            bind=_async_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    assert _async_engine is not None
    return _async_engine, _async_session_factory


def __getattr__(name: str) -> AsyncEngine | async_sessionmaker[AsyncSession]:
    if name == "async_engine":
        eng, _ = _ensure_async()
        return eng
    if name == "AsyncSessionLocal":
        _, fac = _ensure_async()
        return fac
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 의존성으로 사용할 AsyncSession 제공."""

    _, fac = _ensure_async()
    async with fac() as session:
        yield session


if typing.TYPE_CHECKING:
    async_engine: AsyncEngine
    AsyncSessionLocal: async_sessionmaker[AsyncSession]
