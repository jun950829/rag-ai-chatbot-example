"""Embedding tool UI + search (DB in this process); embed inference proxied to local embedding API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import logging
import os
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.rag.search_service import run_vector_search

router = APIRouter(tags=["embedding-tool"])
logger = logging.getLogger(__name__)

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))


def _embedding_base(settings) -> str:
    base = (settings.embedding_service_url or "").strip().rstrip("/")
    if not base:
        return ""

    # In Docker, `127.0.0.1`/`localhost` points to the container itself.
    # If user configured host-local URL, map it to Docker Desktop host gateway.
    in_container = os.path.exists("/.dockerenv") or os.path.exists("/app/.dockerenv")
    if in_container:
        base = base.replace("http://127.0.0.1:", "http://host.docker.internal:")
        base = base.replace("http://localhost:", "http://host.docker.internal:")
        base = base.replace("https://127.0.0.1:", "https://host.docker.internal:")
        base = base.replace("https://localhost:", "https://host.docker.internal:")

    return base


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


@router.get("/tools/chatbot", include_in_schema=False)
def chatbot_tool_page(request: Request):
    # 챗봇 전용 템플릿 분리.
    return _TEMPLATES.TemplateResponse(
        request,
        "chatbot.html",
        {
            "embedding_service_configured": bool(_embedding_base(get_settings())),
        },
    )


@router.get("/tools/chatbot-queue", include_in_schema=False)
def chatbot_queue_page(request: Request):
    return _TEMPLATES.TemplateResponse(
        request,
        "chatbot_queue.html",
        {
            "embedding_service_configured": bool(_embedding_base(get_settings())),
        },
    )


@router.get("/tools/chatbot-debug", include_in_schema=False)
def chatbot_debug_page(request: Request):
    return _TEMPLATES.TemplateResponse(
        request,
        "chatbot_debug.html",
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
    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            r = await client.request(method, url, content=body, headers={"Content-Type": content_type})
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Embedding service 연결 실패: {url} ({type(exc).__name__}: {exc})",
        ) from exc
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
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(url)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Embedding service 연결 실패: {url} ({type(exc).__name__}: {exc})",
        ) from exc
    return Response(content=r.content, status_code=r.status_code, media_type=r.headers.get("content-type", "application/json"))


@router.post("/tools/embedding/api/search", include_in_schema=False)
async def embedding_tool_search(
    query: str = Form(...),
    session_id: str | None = Form(default=None),
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
            session_id=session_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"임베딩 모델 로드 실패: {e}") from e
    except Exception as e:  # noqa: BLE001
        logger.exception("embedding_tool_search failed")
        raise HTTPException(status_code=500, detail=f"검색 처리 실패: {type(e).__name__}: {e}") from e
    return JSONResponse(payload)
