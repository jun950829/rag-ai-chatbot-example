"""동기 Chat Completions (AsyncOpenAI 와 같은 루프에서 DB를 섞을 때 MissingGreenlet 방지)."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from openai import OpenAI

logger = get_logger(__name__)


def sync_chat_completions_text(
    *,
    api_key: str,
    base_url: str | None,
    model: str,
    messages: list[dict[str, Any]],
    max_output_tokens: int = 16384,
) -> str:
    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=max_output_tokens,
        )
    except Exception:
        resp = client.chat.completions.create(model=model, messages=messages, max_tokens=min(max_output_tokens, 8192))
    choice = resp.choices[0]
    finish = getattr(choice, "finish_reason", None)
    if finish == "length":
        logger.warning(
            "[answer] OpenAI finish_reason=length model=%s — 출력 토큰 상한에 도달했을 수 있어 답변이 잘릴 수 있음",
            model,
        )
    return ((choice.message.content) or "").strip() or "LLM이 빈 답변을 반환했습니다."
