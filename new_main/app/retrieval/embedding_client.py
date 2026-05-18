"""임베딩 서버 HTTP 클라이언트 (/v1/embed/query, /v1/embed/queries)."""

from __future__ import annotations

import json
from urllib import request as urllib_request
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings


def _embed_base(remote_base_url: str | None) -> str:
    st = get_settings()
    base = (remote_base_url or "").strip() or (st.embedding_service_url or "").strip()
    if not base:
        raise RuntimeError("EMBEDDING_SERVICE_URL is not set (new_main requires embedding API)")
    return base.rstrip("/")


def embed_query_text(query: str, *, model_id: str, device: str | None, remote_base_url: str | None = None) -> list[float]:
    q = (query or "").strip()
    if not q:
        raise ValueError("query is empty")
    endpoint = _embed_base(remote_base_url) + "/v1/embed/query"
    body = urlencode({"query": q, "model_id": model_id, "device": (device or "").strip()}).encode("utf-8")
    req = urllib_request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    vec = payload.get("embedding")
    if not isinstance(vec, list) or not vec:
        raise RuntimeError("remote embed returned empty embedding")
    return [float(x) for x in vec]


def embed_queries_text(
    queries: list[str], *, model_id: str, device: str | None, remote_base_url: str | None = None
) -> list[list[float]]:
    cleaned = [(q or "").strip() for q in queries]
    if not cleaned:
        return []
    endpoint = _embed_base(remote_base_url) + "/v1/embed/queries"
    body = urlencode(
        {"queries": json.dumps(cleaned, ensure_ascii=False), "model_id": model_id, "device": (device or "").strip()}
    ).encode("utf-8")
    req = urllib_request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    rows = payload.get("embeddings")
    if not isinstance(rows, list) or len(rows) != len(cleaned):
        raise RuntimeError("remote embed/queries returned invalid payload")
    out: list[list[float]] = []
    for row in rows:
        if not isinstance(row, list) or not row:
            raise RuntimeError("remote embed/queries returned empty row")
        out.append([float(x) for x in row])
    return out


async def embed_queries_text_async(
    queries: list[str], *, model_id: str, device: str | None, remote_base_url: str | None = None
) -> list[list[float]]:
    """멀티 쿼리 임베딩을 임베딩 서버에 비동기(httpx)로 요청한다."""
    cleaned = [(q or "").strip() for q in queries]
    if not cleaned:
        return []
    endpoint = _embed_base(remote_base_url) + "/v1/embed/queries"
    data = {
        "queries": json.dumps(cleaned, ensure_ascii=False),
        "model_id": model_id,
        "device": (device or "").strip(),
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        r = await client.post(endpoint, data=data)
        r.raise_for_status()
        payload = r.json()
    rows = payload.get("embeddings")
    if not isinstance(rows, list) or len(rows) != len(cleaned):
        raise RuntimeError("remote embed/queries returned invalid payload")
    out: list[list[float]] = []
    for row in rows:
        if not isinstance(row, list) or not row:
            raise RuntimeError("remote embed/queries returned empty row")
        out.append([float(x) for x in row])
    return out
