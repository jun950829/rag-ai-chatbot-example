"""Embedding tool UI + search (DB in this process); embed inference proxied to local embedding API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.rag.search_service import run_vector_search

router = APIRouter(tags=["embedding-tool"])

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))


def _embedding_base(settings) -> str:
    return (settings.embedding_service_url or "").strip().rstrip("/")


@router.get("/tools/embedding", include_in_schema=False)
def embedding_tool_page(request: Request):
    # Starlette/FastAPI: first positional arg must be Request (not template name).
    return _TEMPLATES.TemplateResponse(
        request,
        "embedding_tool.html",
        {
            "embedding_service_configured": bool(_embedding_base(get_settings())),
        },
    )


async def _forward_form(method: str, path: str, body: bytes, content_type: str) -> Response:
    settings = get_settings()
    base = _embedding_base(settings)
    if not base:
        raise HTTPException(
            status_code=503,
            detail="EMBEDDING_SERVICE_URL is not configured. Set it to your local embed server, e.g. http://host.docker.internal:8765",
        )
    url = f"{base}{path}"
    async with httpx.AsyncClient(timeout=600.0) as client:
        r = await client.request(method, url, content=body, headers={"Content-Type": content_type})
    return Response(content=r.content, status_code=r.status_code, media_type=r.headers.get("content-type", "application/json"))


@router.post("/tools/embedding/api/embed/job", include_in_schema=False)
async def proxy_embed_job(request: Request) -> Response:
    body = await request.body()
    ct = request.headers.get("content-type", "application/x-www-form-urlencoded")
    return await _forward_form("POST", "/embed/job", body, ct)


@router.get("/tools/embedding/api/embed/job/{job_id}/status", include_in_schema=False)
async def proxy_embed_job_status(job_id: str) -> Response:
    settings = get_settings()
    base = _embedding_base(settings)
    if not base:
        raise HTTPException(status_code=503, detail="EMBEDDING_SERVICE_URL is not configured.")
    url = f"{base}/embed/job/{job_id}/status"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(url)
    return Response(content=r.content, status_code=r.status_code, media_type=r.headers.get("content-type", "application/json"))


@router.post("/tools/embedding/api/search", include_in_schema=False)
async def embedding_tool_search(
    query: str = Form(...),
    model_id: str = Form(...),
    device: str = Form(default="cpu"),
    top_k: int = Form(default=10),
    chunk_type: str = Form(default="all"),
    answer_mode: str = Form(default="template"),
    openai_model: str = Form(default="gpt-4o-mini"),
) -> JSONResponse:
    if not (query or "").strip():
        raise HTTPException(status_code=400, detail="검색어가 비어 있습니다.")
    settings = get_settings()
    remote = _embedding_base(settings) or None
    try:
        payload = await run_vector_search(
            query=query,
            model_id=model_id,
            device=device or None,
            top_k=top_k,
            chunk_type=chunk_type,
            answer_mode=answer_mode,
            openai_model=openai_model,
            openai_api_key=settings.openai_api_key,
            openai_base_url=settings.openai_base_url,
            embedding_remote_base_url=remote,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"임베딩 모델 로드 실패: {e}") from e
    return JSONResponse(payload)
