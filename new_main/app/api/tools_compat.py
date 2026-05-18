"""프론트가 기대하는 ``/tools/embedding/api/...`` 경로 (new_main 전용, StaticFiles보다 먼저 등록)."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import JSONResponse

from app.core.logger import get_logger
from app.rag.faq.pipeline import faq_pipeline
from app.rag.faq.service import FaqSearchService
from app.retrieval.vector_db import get_sync_engine
from app.api import quickmenu_sync as qm

logger = get_logger(__name__)

router = APIRouter(tags=["tools-embedding-compat"])


def _require_db_engine():
    try:
        return get_sync_engine()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


def _form_bool(s: str | None, default: bool = False) -> bool:
    if s is None or not str(s).strip():
        return default
    t = str(s).strip().lower()
    return t in ("1", "true", "yes", "on")


@router.post("/tools/embedding/api/search", include_in_schema=False)
async def embedding_tool_search(
    query: str = Form(...),
    session_id: str | None = Form(default=None),
    model_id: str = Form(...),
    device: str = Form(default="cpu"),
    top_k: int = Form(default=10),
    chunk_type: str = Form(default="all"),
    answer_mode: str = Form(default="template"),
    openai_model: str = Form(default="gpt-5-mini"),
    faq_only: str | None = Form(default=None),
    faq_user: str | None = Form(default=None),
    intent_use_openai: str | None = Form(default=None),
) -> JSONResponse:
    _ = (session_id, model_id, device, chunk_type, answer_mode, openai_model, intent_use_openai)
    if not (query or "").strip():
        raise HTTPException(status_code=400, detail="검색어가 비어 있습니다.")
    if not _form_bool(faq_only, False):
        raise HTTPException(
            status_code=400,
            detail="new_main에서는 RAG/일반 검색은 POST /chat 을 사용하세요. FAQ만 faq_only=true 로 지원합니다.",
        )

    payload = await faq_pipeline(
        query=query.strip(),
        qa_user=(faq_user or "").strip() or None,
        top_k=max(1, top_k),
    )
    logger.info(
        "[tools_compat] faq_pipeline ok query_len=%d mode=%s",
        len((query or "").strip()),
        (payload.get("answer_meta") or {}).get("mode"),
    )
    return JSONResponse(payload)


@router.get("/tools/embedding/api/qa-quickmenu/landing", include_in_schema=False)
async def qa_quickmenu_landing() -> JSONResponse:
    _require_db_engine()
    visitor_n, exhibitor_n = qm.landing_counts()
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
    qa_user: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    include_prompt: bool = Query(default=False),
) -> JSONResponse:
    _require_db_engine()
    rows = qm.list_primary_rows(qa_user=qa_user, domain=domain)
    items = [qm.quickmenu_row_to_dict(dict(r), include_prompt=include_prompt) for r in rows]
    return JSONResponse({"count": len(items), "items": items})


@router.get("/tools/embedding/api/qa-quickmenu/{qna_code}", include_in_schema=False)
async def qa_quickmenu_one(
    qna_code: str,
    include_prompt: bool = Query(default=True),
) -> JSONResponse:
    _require_db_engine()
    row = qm.get_row(qna_code)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown qna_code: {qna_code}")
    item = qm.quickmenu_row_to_dict(row, include_prompt=include_prompt)
    item["follow_questions_resolved"] = qm.resolve_follow_question_rows(row)
    return JSONResponse({"item": item})


@router.get("/tools/embedding/api/qa-quickmenu/{qna_code}/follow-links", include_in_schema=False)
async def qa_quickmenu_follow_links(
    qna_code: str,
    include_prompt: bool = Query(default=False),
) -> JSONResponse:
    _require_db_engine()
    rows = qm.list_follow_link_rows(qna_code)
    return JSONResponse(
        {
            "from_qna_code": qna_code.strip(),
            "count": len(rows),
            "items": [qm.quickmenu_row_to_dict(dict(r), include_prompt=include_prompt) for r in rows],
        }
    )
