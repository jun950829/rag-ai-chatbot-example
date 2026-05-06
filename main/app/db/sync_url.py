"""동기 SQLAlchemy 엔진용 Postgres DSN 정규화."""

from __future__ import annotations

from sqlalchemy.engine.url import URL, make_url


def _url_connect_str(u: URL) -> str:
    """SQLAlchemy 2에서는 ``str(URL)`` 이 비밀번호를 ``***`` 로 치환하므로 접속 문자열에는 쓰지 않는다."""
    return u.render_as_string(hide_password=False)


def to_sync_postgres_dsn(url: str) -> str:
    """async 전용 드라이버 URL을 ``create_engine`` / ``Session`` 이 쓸 수 있게 바꾼다.

    ``DATABASE_URL`` 이 ``postgresql+asyncpg://`` 인 배포에서 ingest 등 동기 경로가
    ``MissingGreenlet`` 없이 붙도록 ``postgresql+psycopg://`` 로 맞춘다.

    1) ``make_url`` 로 파싱해 ``drivername`` 기준 치환(공백·대소문자 변형까지 포착).
    2) 파싱 실패 시 기존 접두 문자열 규칙으로 폴백.
    """
    u = (url or "").strip()
    if not u:
        return u
    try:
        parsed = make_url(u)
        dn_l = parsed.drivername.lower()
        if "+asyncpg" in dn_l or "psycopg_async" in dn_l:
            return _url_connect_str(parsed.set(drivername="postgresql+psycopg"))
    except Exception:
        pass

    lower = u.lower()
    for async_head, sync_head in (
        ("postgresql+asyncpg://", "postgresql+psycopg://"),
        ("postgres+asyncpg://", "postgresql+psycopg://"),
        ("postgresql+psycopg_async://", "postgresql+psycopg://"),
        ("postgres+psycopg_async://", "postgresql+psycopg://"),
    ):
        if lower.startswith(async_head):
            return sync_head + u[len(async_head) :]
    return u


def to_async_postgres_url(url: str) -> str:
    """create_async_engine 전용: 동기 psycopg3 등으로 잘못 잡혀 녹색 스레드가 꼬이지 않게 비동기 드라이버로 맞춘다.

    ``postgresql+psycopg://`` (동기) → ``postgresql+psycopg_async://``
    ``postgresql://`` (드라이버 접두 없음) → ``postgresql+asyncpg://`` (requirements에 포함)
    이미 ``+asyncpg`` / ``+psycopg_async`` 이면 그대로 반환한다.
    """
    u = (url or "").strip()
    if not u:
        return u
    try:
        parsed = make_url(u)
        dn_l = parsed.drivername.lower()
        if not any(dn_l.startswith(p) for p in ("postgresql", "postgres")):
            return _url_connect_str(parsed)
        if "+asyncpg" in dn_l or "+psycopg_async" in dn_l:
            return _url_connect_str(parsed)
        if dn_l.endswith("+psycopg"):
            return _url_connect_str(parsed.set(drivername="postgresql+psycopg_async"))
        # 순수 dialect 이름만 있으면(예: postgresql://…) SQLAlchemy가 sync·greenlet 브리징 타면 MissingGreenlet 날 수 있음
        if dn_l in ("postgresql", "postgres"):
            return _url_connect_str(parsed.set(drivername="postgresql+asyncpg"))
        if dn_l.endswith("+psycopg2"):
            return _url_connect_str(parsed.set(drivername="postgresql+asyncpg"))
        return _url_connect_str(parsed)
    except Exception:
        pass
    lower = u.lower()
    # 파싱 실패·비표준 문자열 폴백
    if "://" in u and "+" not in u.split("://", 1)[0]:
        hl = u.split("://", 1)[0].lower()
        if hl in ("postgresql", "postgres"):
            return "postgresql+asyncpg://" + u.split("://", 1)[1]
    for sync_head, async_head in (
        ("postgresql+psycopg://", "postgresql+psycopg_async://"),
        ("postgres+psycopg://", "postgresql+psycopg_async://"),
    ):
        if lower.startswith(sync_head):
            return async_head + u[len(sync_head) :]
    return u
