"""Embedding tool UI + RAG 검색 API.

- **HTML**: ``/tools/embedding``, ``/tools/chatbot`` 등 Jinja 템플릿
- **검색**: ``POST .../api/search`` → ``run_vector_search`` (의도 분류·벡터 검색·선택적 OpenAI 답변)
- **QA 퀵메뉴**: ``GET .../api/qa-quickmenu/...`` → ``kprint_qa_quickmenu`` (CSV 적재 테이블, 카테고리 탐색)
- 임베딩 추론은 별도 ``EMBEDDING_SERVICE_URL`` 서버로 프록시
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import logging
import os
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.db.repositories.kprint_qa_quickmenu_repository import (
    KprintQaQuickmenuRepository,
    quickmenu_row_to_dict,
)
from app.db.session import AsyncSessionLocal
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


# --- QA 퀵메뉴 (kprint_qa_quickmenu): 메인 1차 버튼 + follow 링크 조회 -----------------


@router.get("/tools/embedding/api/qa-quickmenu/landing", include_in_schema=False)
async def qa_quickmenu_landing() -> JSONResponse:
    """Test_AI 랜딩용 메타: 인사 문구 + 허브 3종(참관객 FAQ / 참가업체 FAQ / RAG 검색 시드).

    실제 1차 질문 목록은 ``primary?qa_user=visitor|exhibitor`` 로 가져온다.
    """
    async with AsyncSessionLocal() as db:
        repo = KprintQaQuickmenuRepository(db)
        visitor_n = len(await repo.list_primary_rows(qa_user="visitor"))
        exhibitor_n = len(await repo.list_primary_rows(qa_user="exhibitor"))
    return JSONResponse(
        {
            "greeting": (
                "안녕하세요. Test_AI 입니다. 전시회 정보나 참가기업, 제품이 궁금하시면 "
                "아래에서 주제를 고르거나 직접 질문해 주세요."
            ),
            "visitor_primary_count": visitor_n,
            "exhibitor_primary_count": exhibitor_n,
            "hubs": [
                {
                    "id": "visitor_faq",
                    "title": "참관객 FAQ",
                    "subtitle": "자주 묻는 질문을 확인하세요",
                    "kind": "faq_tree",
                    "qa_user": "visitor",
                },
                {
                    "id": "exhibitor_faq",
                    "title": "참가업체 FAQ",
                    "subtitle": "부스·출입 등 참가사 안내",
                    "kind": "faq_tree",
                    "qa_user": "exhibitor",
                },
                {
                    "id": "company_product_rag",
                    "title": "참가기업/제품 정보",
                    "subtitle": "저장된 안내와 함께, 검색으로 업체·전시품을 찾을 수 있어요",
                    "kind": "rag",
                    "seed_qna_code": "kp_vis_showinfo_003",
                },
            ],
        }
    )


@router.get("/tools/embedding/api/qa-quickmenu/primary", include_in_schema=False)
async def qa_quickmenu_primary(
    qa_user: str | None = Query(default=None, description="CSV user 열과 동일 (예: visitor)"),
    domain: str | None = Query(default=None),
    include_prompt: bool = Query(default=False, description="긴 default_answer_prompt 포함 여부"),
) -> JSONResponse:
    """``primary_question=true`` 행만 반환 — 챗봇 메인 카테고리 버튼 소스."""
    async with AsyncSessionLocal() as db:
        repo = KprintQaQuickmenuRepository(db)
        rows = await repo.list_primary_rows(qa_user=qa_user, domain=domain)
        return JSONResponse(
            {"count": len(rows), "items": [quickmenu_row_to_dict(r, include_prompt=include_prompt) for r in rows]}
        )


@router.get("/tools/embedding/api/qa-quickmenu/by-parent", include_in_schema=False)
async def qa_quickmenu_by_parent(
    parent_id: str = Query(..., description="예: ko1, ko2"),
    include_prompt: bool = Query(default=False),
) -> JSONResponse:
    """같은 ``parent_id`` 그룹 행 — CSV 상 형제/그룹 탐색용."""
    async with AsyncSessionLocal() as db:
        repo = KprintQaQuickmenuRepository(db)
        rows = await repo.list_by_parent_id(parent_id)
        return JSONResponse(
            {"parent_id": parent_id.strip(), "count": len(rows), "items": [quickmenu_row_to_dict(r, include_prompt=include_prompt) for r in rows]}
        )


@router.get("/tools/embedding/api/qa-quickmenu/{qna_code}", include_in_schema=False)
async def qa_quickmenu_one(
    qna_code: str,
    include_prompt: bool = Query(default=True),
) -> JSONResponse:
    """단일 행 상세."""
    async with AsyncSessionLocal() as db:
        repo = KprintQaQuickmenuRepository(db)
        row = await repo.get_row(qna_code)
        if row is None:
            raise HTTPException(status_code=404, detail=f"unknown qna_code: {qna_code}")
        item = quickmenu_row_to_dict(row, include_prompt=include_prompt)
        # follow_question1~4를 실제 row 객체로 해석해 함께 제공 (UI가 라벨/질문을 직접 사용 가능)
        item["follow_questions_resolved"] = await repo.resolve_follow_question_rows(row)
        return JSONResponse({"item": item})


@router.get("/tools/embedding/api/qa-quickmenu/{qna_code}/follow-links", include_in_schema=False)
async def qa_quickmenu_follow_links(
    qna_code: str,
    include_prompt: bool = Query(default=False),
) -> JSONResponse:
    """해당 행의 ``follow_question*`` / ``default_quickmenu`` 에 나온 ``qna_code`` 순서대로 전개."""
    async with AsyncSessionLocal() as db:
        repo = KprintQaQuickmenuRepository(db)
        rows = await repo.list_follow_link_rows(qna_code)
        return JSONResponse(
            {
                "from_qna_code": qna_code.strip(),
                "count": len(rows),
                "items": [quickmenu_row_to_dict(r, include_prompt=include_prompt) for r in rows],
            }
        )
