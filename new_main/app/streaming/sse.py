"""SSE 스트리밍 유틸.

오케스트레이터는 여기의 writer/serializer만 사용하고, 상세 포맷은 이 모듈에 가둔다.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any


def sse_event(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def sse_yield_text_deltas(text_stream: AsyncIterator[str]) -> AsyncIterator[str]:
    """토큰 스트림을 SSE로보낸다.

    파이프라인 중 예외가 나도 마지막에 ``done`` 을 보내 프록시/브라우저가
    ``ERR_INCOMPLETE_CHUNKED_ENCODING`` 으로 끊기지 않게 한다.
    """
    try:
        async for token in text_stream:
            yield sse_event("delta", token)
    except Exception as e:  # noqa: BLE001 — 스트림 경계에서 사용자에게 전달
        yield sse_event("error", str(e) or type(e).__name__)
    finally:
        yield sse_event("done", "[DONE]")


async def sse_yield_chat_stream(
    *,
    cards: list[Any] | None,
    text_stream: AsyncIterator[str],
) -> AsyncIterator[str]:
    """먼저 ``delta`` 토큰을 모두 보낸 뒤, 있으면 ``cards`` 한 번, 마지막에 ``done``."""
    try:
        async for token in text_stream:
            yield sse_event("delta", token)
        if cards:
            yield sse_event("cards", cards)
    except Exception as e:  # noqa: BLE001
        yield sse_event("error", str(e) or type(e).__name__)
    finally:
        yield sse_event("done", "[DONE]")
