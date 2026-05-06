"""Ingest 스크립트가 ``app.db`` 를 import 하기 전에 호출한다.

컨테이너 ``DATABASE_URL`` 이 ``postgresql+asyncpg://`` 인 경우 동기 ``SessionLocal`` 이
asyncpg 를 타면서 ``MissingGreenlet`` 이 난다. 이미지에 ``to_sync_postgres_dsn`` 패치가
없어도 동작하도록, pydantic 이 읽기 전에 ``os.environ`` 을 동기 DSN 으로 맞춘다.
환경 변수가 없으면 ``main/.env`` 의 ``DATABASE_URL`` 행을 읽는다.
"""

from __future__ import annotations

import os
from pathlib import Path

_PAIRS: tuple[tuple[str, str], ...] = (
    ("postgresql+asyncpg://", "postgresql+psycopg://"),
    ("postgres+asyncpg://", "postgresql+psycopg://"),
    ("postgresql+psycopg_async://", "postgresql+psycopg://"),
)


def _to_sync(url: str) -> str | None:
    u = url.strip()
    for async_head, sync_head in _PAIRS:
        if u.startswith(async_head):
            return sync_head + u[len(async_head) :]
    return None


def _database_url_from_dotenv(main_root: str) -> str | None:
    p = Path(main_root) / ".env"
    if not p.is_file():
        return None
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def ensure_sync_database_url(*, main_root: str) -> None:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        url = (_database_url_from_dotenv(main_root) or "").strip()
    if not url:
        return
    sync = _to_sync(url)
    if sync is not None:
        os.environ["DATABASE_URL"] = sync
