"""DB 세션/엔진 관리 (Async).

요구사항:
- async 지원
- 쿼리 최소화, 커넥션 풀 재사용
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


def _create_async_engine() -> AsyncEngine:
    """설정 기반으로 AsyncEngine 생성.

    - SQLAlchemy 2.x + psycopg3 async 드라이버 사용
    - pool_pre_ping으로 죽은 커넥션 자동 감지
    """

    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        echo=False,
    )


async_engine: AsyncEngine = _create_async_engine()

# 세션 팩토리(의존성 주입으로 재사용)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 의존성으로 사용할 AsyncSession 제공."""

    async with AsyncSessionLocal() as session:
        yield session

