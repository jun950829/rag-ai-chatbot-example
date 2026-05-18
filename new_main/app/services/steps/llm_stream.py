from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from app.core.config import get_settings


def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in messages:
        role = str(m.get("role") or "user")
        content = m.get("content")
        if content is None:
            continue
        out.append({"role": role, "content": str(content)})
    if not out:
        raise ValueError("messages is empty")
    return out


async def stream_llm_answer(*, messages: list[dict[str, Any]]) -> AsyncIterator[str]:
    st = get_settings()
    client_kwargs = {"api_key": (st.openai_api_key or "").strip()}
    if (st.openai_base_url or "").strip():
        client_kwargs["base_url"] = (st.openai_base_url or "").strip()
    client = AsyncOpenAI(**client_kwargs)

    msgs = _normalize_messages(messages)
    stream = await client.chat.completions.create(
        model=st.openai_model,
        messages=msgs,
        stream=True,
    )
    async for evt in stream:
        for choice in getattr(evt, "choices", []) or []:
            delta = getattr(choice, "delta", None)
            piece = getattr(delta, "content", None) if delta is not None else None
            if piece:
                yield piece
