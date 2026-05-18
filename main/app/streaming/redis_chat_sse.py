"""Redis LLM 스트림 → SSE 텍스트 청크 (라우터에서 분리)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from redis.asyncio import Redis


async def iter_redis_stream_as_sse(
    redis: Redis,
    *,
    stream_key: str,
    poll_interval_s: float = 0.05,
    max_empty_polls: int = 12000,
) -> AsyncIterator[str]:
    """워커가 ``stream_key`` 에 push 한 JSON 줄을 SSE 프레임으로 변환한다."""

    empty_polls = 0
    while True:
        raw = await redis.lpop(stream_key)
        if not raw:
            empty_polls += 1
            if empty_polls >= max_empty_polls:
                break
            await asyncio.sleep(poll_interval_s)
            continue
        empty_polls = 0
        payload: dict[str, Any] = json.loads(raw)
        event = payload.get("event", "message")
        data = payload.get("data", "")
        yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        if event in {"done", "error"}:
            return
    yield "event: done\ndata: [DONE]\n\n"
