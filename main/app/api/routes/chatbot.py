"""챗봇 큐 API + SSE 스트림 엔드포인트."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from redis.asyncio import Redis

from app.core.config import get_settings

router = APIRouter(tags=["chatbot"])


def _cache_key(prefix: str, message: str) -> str:
    digest = hashlib.sha256(message.strip().encode("utf-8")).hexdigest()
    return f"{prefix}{digest}"


async def _push_trace(
    redis: Redis,
    *,
    trace_key: str,
    stage: str,
    status: str,
    detail: str,
) -> None:
    payload = {
        "stage": stage,
        "status": status,
        "detail": detail,
    }
    await redis.rpush(trace_key, json.dumps(payload, ensure_ascii=False))
    await redis.expire(trace_key, 3600)


@router.post("/chat", include_in_schema=True)
async def enqueue_chat(
    session_id: str = Form(...),
    message: str = Form(...),
) -> JSONResponse:
    """API는 LLM을 직접 호출하지 않고 Redis 큐에 작업만 등록한다."""
    if not (message or "").strip():
        raise HTTPException(status_code=400, detail="message is empty")

    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    request_id = str(uuid.uuid4())
    stream_key = f"{settings.llm_stream_prefix}{request_id}"
    trace_key = f"{settings.llm_trace_prefix}{request_id}"
    cache_key = _cache_key(settings.chat_cache_prefix, message)

    try:
        await _push_trace(
            redis,
            trace_key=trace_key,
            stage="api_enqueue",
            status="started",
            detail="질문 수신 후 캐시/큐 처리 시작",
        )
        cached = await redis.get(cache_key)
        if cached:
            await redis.rpush(stream_key, json.dumps({"event": "token", "data": cached}, ensure_ascii=False))
            await redis.rpush(stream_key, json.dumps({"event": "done", "data": "[DONE]"}, ensure_ascii=False))
            await redis.expire(stream_key, settings.chat_cache_ttl_seconds)
            await _push_trace(
                redis,
                trace_key=trace_key,
                stage="api_enqueue",
                status="done",
                detail="캐시 히트로 즉시 응답",
            )
            return JSONResponse({"request_id": request_id, "status": "queued", "cached": True})

        payload = {
            "request_id": request_id,
            "session_id": session_id,
            "message": message,
            "cache_key": cache_key,
        }
        await redis.rpush(settings.llm_queue_name, json.dumps(payload, ensure_ascii=False))
        await _push_trace(
            redis,
            trace_key=trace_key,
            stage="api_enqueue",
            status="queued",
            detail=f"LLM 큐 적재 완료 ({settings.llm_queue_name})",
        )
        return JSONResponse({"request_id": request_id, "status": "queued", "cached": False})
    finally:
        await redis.close()


@router.get("/stream/{request_id}", include_in_schema=True)
async def stream_chat(request_id: str) -> StreamingResponse:
    """워커가 쓴 Redis 토큰 이벤트를 SSE로 전달한다."""
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    stream_key = f"{settings.llm_stream_prefix}{request_id}"

    async def event_generator() -> AsyncIterator[str]:
        try:
            for _ in range(600):
                raw = await redis.lpop(stream_key)
                if not raw:
                    await asyncio.sleep(0.5)
                    continue
                payload = json.loads(raw)
                event = payload.get("event", "message")
                data = payload.get("data", "")
                yield f"event: {event}\ndata: {data}\n\n"
                if event in {"done", "error"}:
                    return
            yield "event: done\ndata: [DONE]\n\n"
        finally:
            await redis.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/chat/queue/status", include_in_schema=True)
async def queue_status() -> JSONResponse:
    """LLM 큐 적재 현황을 모니터링 화면에서 폴링하기 위한 상태 API."""
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        llm_queue_len = await redis.llen(settings.llm_queue_name)
        embedding_queue_len = await redis.llen(settings.embedding_queue_name)
        llm_head = await redis.lrange(settings.llm_queue_name, 0, 4)

        preview: list[dict[str, str]] = []
        for raw in llm_head:
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            preview.append(
                {
                    "request_id": str(item.get("request_id", "")),
                    "session_id": str(item.get("session_id", "")),
                    "message_preview": str(item.get("message", ""))[:120],
                }
            )

        return JSONResponse(
            {
                "llm_queue_name": settings.llm_queue_name,
                "embedding_queue_name": settings.embedding_queue_name,
                "llm_queue_length": llm_queue_len,
                "embedding_queue_length": embedding_queue_len,
                "llm_queue_head_preview": preview,
            }
        )
    finally:
        await redis.close()


@router.get("/chat/trace/{request_id}", include_in_schema=True)
async def chat_trace(request_id: str) -> JSONResponse:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    trace_key = f"{settings.llm_trace_prefix}{request_id}"
    try:
        raw_items = await redis.lrange(trace_key, 0, -1)
        items: list[dict[str, str]] = []
        for raw in raw_items:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            items.append(
                {
                    "stage": str(payload.get("stage", "")),
                    "status": str(payload.get("status", "")),
                    "detail": str(payload.get("detail", "")),
                }
            )
        return JSONResponse({"request_id": request_id, "trace": items})
    finally:
        await redis.close()
