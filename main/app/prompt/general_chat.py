"""일반 대화(greeting/general 등) 보조 응답용 프롬프트."""

from __future__ import annotations

from typing import Any


def build_general_openai_messages(*, query: str, language: str) -> list[dict[str, Any]]:
    lang = (language or "ko").strip().lower()
    if lang == "en":
        language_rule = "Respond in clear, natural English."
        sys_c = (
            "You are a helpful assistant. "
            f"{language_rule} "
            "Be concise: optional one-line summary, then '·' bullets. Use blank lines between paragraphs."
        )
        usr = f"User message: {query}\nReply briefly in a helpful way."
    else:
        language_rule = "한국어로 자연스럽게 답변"
        sys_c = (
            "너는 사용자 입력에 친절하게 반응하는 도우미다. "
            f"{language_rule}. "
            "짧게, **정리형**으로: 필요하면 첫 줄 요약 후 '·' 불릿. 문단 사이에는 빈 줄을 넣는다."
        )
        usr = f"사용자 입력: {query}\n이 메시지 의도에 맞게 간단히 응답해줘."
    return [
        {"role": "system", "content": sys_c},
        {"role": "user", "content": usr},
    ]
