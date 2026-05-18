"""FAQ 동의어/캐노니컬 토픽 매핑.

new_main/tests 가 기대하는 API:
- ``canonicalize_faq_query``
"""

from __future__ import annotations

import re


FAQ_CANONICAL_MAP: dict[str, str] = {
    # 시간/운영
    "전시 시간": "관람 시간",
    "관람 시간": "관람 시간",
    "운영 시간": "관람 시간",
    "행사 시간": "관람 시간",
    # 셔틀
    "셔틀 시간": "셔틀 운행 시간",
    "셔틀버스": "셔틀 운행 시간",
    "셔틀 버스": "셔틀 운행 시간",
    "셔틀 운행 시간": "셔틀 운행 시간",
    # 등록
    "사전등록": "사전등록",
    "사전 등록": "사전등록",
    "사전등록 방법": "사전등록",
    "등록 방법": "사전등록",
    "온라인 등록": "사전등록",
    "온라인등록": "사전등록",
    # 출입증/배지
    "출입증": "출입증",
    "배지": "출입증",
    "입장 배지": "출입증",
    "입장배지": "출입증",
    "출입증 수령 위치": "출입증 수령 위치",
    "배지 수령 위치": "출입증 수령 위치",
    # 기타
    "오시는 길": "오시는 길",
    "오시는길": "오시는 길",
    "행사 장소": "행사 장소",
    "주차 요금": "주차 요금",
}


_WS_RE = re.compile(r"\s+")
_NON_TEXT_RE = re.compile(r"[^0-9a-z가-힣\s]")


def _basic_normalize(text: str) -> str:
    t = (text or "").strip().lower()
    if not t:
        return ""
    t = _WS_RE.sub(" ", t)
    t = _NON_TEXT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


def canonicalize_faq_query(query: str) -> tuple[str, str, str]:
    raw = query or ""
    normalized = _basic_normalize(raw)
    if not normalized:
        return raw, "", ""

    if normalized in FAQ_CANONICAL_MAP:
        return raw, normalized, _basic_normalize(FAQ_CANONICAL_MAP[normalized])

    if "시간" in normalized:
        if any(k in normalized for k in ("전시", "관람", "운영", "행사")):
            return raw, normalized, _basic_normalize("관람 시간")
        if "셔틀" in normalized:
            return raw, normalized, _basic_normalize("셔틀 운행 시간")
    if any(k in normalized for k in ("사전등록", "사전 등록", "온라인 등록", "등록 방법")):
        return raw, normalized, _basic_normalize("사전등록")
    if any(k in normalized for k in ("배지", "출입증", "입장 배지", "입장배지")):
        if any(k in normalized for k in ("수령", "발급", "교환", "등록대", "위치", "어디")):
            return raw, normalized, _basic_normalize("출입증 수령 위치")
        return raw, normalized, _basic_normalize("출입증")

    return raw, normalized, normalized

