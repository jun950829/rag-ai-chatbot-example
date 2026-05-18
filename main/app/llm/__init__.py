"""OpenAI 등 답변 생성(동기 Chat Completions 래퍼)."""

from app.llm.openai_chat import sync_chat_completions_text

__all__ = ["sync_chat_completions_text"]
