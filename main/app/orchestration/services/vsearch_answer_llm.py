"""검색 답변용 OpenAI 호출 (동기 API를 스레드로 감쌈)."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Any

from app.core.logger import get_logger
from app.llm.openai_chat import sync_chat_completions_text
from app.prompts.retrieval.answer_messages import (
    build_general_openai_messages,
    build_retrieval_openai_messages,
)

logger = get_logger(__name__)
ANSWER_OPENAI_MODEL = "gpt-5-mini"


def answer_base_url_norm(base: str) -> str | None:
    b = (base or "").strip()
    return b or None


async def generate_korean_answer_with_openai(
    *,
    query: str,
    results: list[dict[str, Any]],
    api_key: str,
    base_url: str,
    model: str,
    intent: str,
    language: str,
    retrieval_topic: str | None,
    is_dialog_followup: bool,
) -> str:
    lang = (language or "ko").strip().lower()
    if not results:
        return (
            "No search results; cannot generate an answer."
            if lang == "en"
            else "검색 결과가 없어 답변을 생성할 수 없습니다."
        )

    messages = build_retrieval_openai_messages(
        query=query,
        results=results,
        intent=intent,
        language=language,
        retrieval_topic=retrieval_topic,
        is_dialog_followup=is_dialog_followup,
    )
    ctx_len = len(str(messages[-1].get("content", "")))
    logger.info(
        "[answer] openai_generate(sync via thread) start query_len=%d results=%d context_chars=%s lang=%s",
        len(query or ""),
        len(results),
        ctx_len,
        lang,
    )
    out = await asyncio.to_thread(
        partial(
            sync_chat_completions_text,
            api_key=api_key,
            base_url=answer_base_url_norm(base_url),
            model=model,
            messages=messages,
            max_output_tokens=16384,
        )
    )
    logger.info("[answer] openai_generate done answer_chars=%d", len(out))
    return out


async def generate_general_answer_with_openai(
    *,
    query: str,
    api_key: str,
    base_url: str,
    model: str,
    language: str,
) -> str:
    messages = build_general_openai_messages(query=query, language=language)
    return await asyncio.to_thread(
        partial(
            sync_chat_completions_text,
            api_key=api_key,
            base_url=answer_base_url_norm(base_url),
            model=model,
            messages=messages,
            max_output_tokens=4096,
        )
    )
