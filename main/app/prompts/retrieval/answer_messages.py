"""RAG 검색 답변용 메시지 빌더 — 실제 프롬프트 조립은 ``app.prompt`` 모듈에 위임."""

from app.prompt.general_chat import build_general_openai_messages
from app.prompt.retrieval_answer import build_retrieval_openai_messages

__all__ = ["build_general_openai_messages", "build_retrieval_openai_messages"]
