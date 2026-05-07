"""FAQ 동의어/캐노니컬 토픽 매핑.

목표:
- FAQ 검색은 "문장을 그대로 찾는 것"이 아니라,
  사용자 표현을 하나의 대표 토픽(canonical topic)으로 압축하는 시스템이어야 한다.
- 제품/업체 RAG(pgvector/embedding/LLM)에는 영향이 없어야 한다.
"""

from __future__ import annotations

import re


# 사용자 표현 → 대표 토픽(canonical)
# - 과도한 규칙 증식을 막기 위해 "짧고 빈번한" 토픽만 우선 커버한다.
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
    """공백/특수문자/대소문자 수준의 기본 정규화."""

    t = (text or "").strip().lower()
    if not t:
        return ""
    t = _WS_RE.sub(" ", t)
    t = _NON_TEXT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


def canonicalize_faq_query(query: str) -> tuple[str, str, str]:
    """FAQ 검색용 정규화 + 캐노니컬 토픽 매핑.

    반환:
    - raw: 원문
    - normalized: 기본 정규화 결과
    - canonical: canonical 토픽(없으면 normalized)
    """

    raw = query or ""
    normalized = _basic_normalize(raw)
    if not normalized:
        return raw, "", ""

    # 1) 완전일치 매핑
    if normalized in FAQ_CANONICAL_MAP:
        return raw, normalized, _basic_normalize(FAQ_CANONICAL_MAP[normalized])

    # 2) 포함 기반(짧은 질의 대응) — "전시/관람/운영" + "시간"처럼 조합형을 캐치
    #    휴리스틱을 과도하게 늘리지 않기 위해 핵심 토픽만 처리한다.
    if "시간" in normalized:
        if any(k in normalized for k in ("전시", "관람", "운영", "행사")):
            return raw, normalized, _basic_normalize("관람 시간")
        if "셔틀" in normalized:
            return raw, normalized, _basic_normalize("셔틀 운행 시간")
    if any(k in normalized for k in ("사전등록", "사전 등록", "온라인 등록", "등록 방법")):
        return raw, normalized, _basic_normalize("사전등록")
    if any(k in normalized for k in ("배지", "출입증", "입장 배지", "입장배지")):
        # "수령/발급/교환/등록대/위치"가 함께 있으면 '수령 위치'로 올린다.
        if any(k in normalized for k in ("수령", "발급", "교환", "등록대", "위치", "어디")):
            return raw, normalized, _basic_normalize("출입증 수령 위치")
        return raw, normalized, _basic_normalize("출입증")

    return raw, normalized, normalized

