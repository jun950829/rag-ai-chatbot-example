from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Optional

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import StreamingResponse

from app.core.logger import logger
from app.rag.faq.pipeline import faq_pipeline
from app.services.chat_pipeline import chat_stream
from app.services.steps.make_cards import stream_card_detail
from app.streaming.sse import sse_event, sse_yield_chat_stream

router = APIRouter(tags=["chat"])

_FAQ_MODES = {"faq_visitor", "faq_exhibitor"}
_FAQ_USER_MAP = {"faq_visitor": "visitor", "faq_exhibitor": "exhibitor"}


async def _faq_sse(query: str, qa_user: str | None) -> AsyncIterator[str]:
    payload = await faq_pipeline(query=query, qa_user=qa_user, top_k=5)
    meta = payload.get("answer_meta") or {}
    show_switch = bool(meta.get("show_catalog_mode_switcher", False))
    logger.info(
        "[chat] faq_sse qa_user=%s answer_meta.mode=%s intent=%s show_catalog_mode_switcher=%s query_preview=%r",
        qa_user or "-",
        meta.get("mode", "-"),
        meta.get("intent", "-"),
        show_switch,
        (query or "").replace("\n", " ")[:120],
    )
    yield sse_event("final", {
        "answer": payload.get("answer", ""),
        "message_id": str(uuid.uuid4()),
        "cards": payload.get("cards") or [],
        "show_catalog_mode_switcher": show_switch,
    })


@router.post("/chat")
async def chat(
    session_id: str = Form(...),
    message: str = Form(...),
    session_mode: str = Form(default="catalog"),
) -> StreamingResponse:
    if not (message or "").strip():
        raise HTTPException(status_code=400, detail="message is empty")

    if session_mode in _FAQ_MODES:
        qa_user = _FAQ_USER_MAP.get(session_mode)
        return StreamingResponse(
            _faq_sse(query=message.strip(), qa_user=qa_user),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    cards, token_it = await chat_stream(session_id=session_id, message=message)

    return StreamingResponse(
        sse_yield_chat_stream(cards=cards or None, text_stream=token_it),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/card-detail")
async def chat_card_detail(
    session_id: str = Form(...),
    external_id: str = Form(...),
    entity_kind: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
) -> StreamingResponse:
    if not (external_id or "").strip():
        raise HTTPException(status_code=400, detail="external_id is empty")

    _cards, token_it = await stream_card_detail(
        session_id=session_id,
        external_id=external_id.strip(),
        entity_kind=(entity_kind or "").strip() or None,
        language=(language or "ko").strip().lower(),
    )

    return StreamingResponse(
        sse_yield_chat_stream(cards=None, text_stream=token_it),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
