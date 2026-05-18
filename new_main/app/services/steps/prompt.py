from __future__ import annotations

from typing import Any

from app.prompt.general_chat import build_general_openai_messages
from app.prompt.retrieval_answer import build_messages_for_rag_stream


async def build_chat_messages(
    *,
    query: str,
    intent: str,
    context: str,
    language: str = "ko",
) -> list[dict[str, Any]]:
    """검색 컨텍스트가 있으면 main 과 동일한 RAG 시스템/유저 메시지, 없으면 일반 대화 프롬프트."""
    ctx = (context or "").strip()
    if not ctx:
        return build_general_openai_messages(query=query, language=language)
    return build_messages_for_rag_stream(query=query, context=ctx, intent=intent, language=language)
