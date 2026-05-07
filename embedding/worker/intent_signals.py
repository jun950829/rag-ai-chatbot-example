"""메인 ``app/rag/retrieval/intent.py`` 의 ``_GENERAL_FAQ_HINTS`` 와 동일한 규칙.

워커 라우팅에서 FAQ 매칭 시 OpenAI 라우팅 재판을 건너뛸 때만 사용한다.
"""

from __future__ import annotations

import re

_GENERAL_FAQ_HINTS = (
    "hours",
    "schedule",
    "time",
    "ticket",
    "tickets",
    "location",
    "venue",
    "parking",
    "shuttle",
    "badge",
    "faq",
    "개막",
    "운영시간",
    "입장",
    "장소",
    "전시회 정보",
    "전시 정보",
    # kprint QA bot CSV 기반 키워드 (현장 FAQ가 general로 분류될 때 메인 API FAQ 게이트로 보내기 위함)
    "출입증",
    "배지",
    "등록",
    "사전등록",
    "주차",
    "주차장",
    "셔틀",
    "환불",
    "참관확인서"
)


def norm_worker_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def looks_like_general_faq(message: str) -> bool:
    n = norm_worker_text(message)
    return any(h in n for h in _GENERAL_FAQ_HINTS)
