"""한국어 FAQ 질문 정규화기.

요구사항:
- 조사/어미/불용어 제거
- 질문을 canonical intent로 압축
- deterministic (embedding/LLM 금지)
"""

from __future__ import annotations

import logging
import re

from app.rag.faq_canonical import FAQ_CANONICAL_MAP

logger = logging.getLogger(__name__)


FAQ_STOPWORDS: set[str] = {
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "에",
    "에서",
    "인가요",
    "언제인가요",
    "가능한가요",
    "알려주세요",
    "해주세요",
    "궁금해요",
    "어떻게",
    "방법",
    "관련",
    "문의",
    "좀",
    "혹시",
    "대한",
}

_WS_RE = re.compile(r"\s+")
_NON_TEXT_RE = re.compile(r"[^0-9a-z가-힣\s]")

# 문장 끝 패턴(어미/요청형) 제거
_END_PATTERNS = [
    r"(인가요)\s*$",
    r"(언제인가요)\s*$",
    r"(알려\s*주세요)\s*$",
    r"(부탁드립니다)\s*$",
    r"(가능한가요)\s*$",
    r"(있나요)\s*$",
    r"(해\s*주세요)\s*$",
]


def _basic_normalize(text: str) -> str:
    t = (text or "").strip().lower()
    if not t:
        return ""
    t = _WS_RE.sub(" ", t)
    t = _NON_TEXT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


def _strip_endings(text: str) -> tuple[str, list[str]]:
    """문장 끝 어미/요청형을 제거하고 제거된 패턴을 반환."""

    removed: list[str] = []
    t = text
    for pat in _END_PATTERNS:
        nt = re.sub(pat, "", t).strip()
        if nt != t:
            removed.append(pat)
            t = nt
    return t, removed


def _tokenize_ko(text: str) -> list[str]:
    """아주 단순 토큰화 + 불용어 제거.

    형태소 분석은 금지(의존성/비용). 대신 FAQ intent 수준에서 충분한 정규화만 수행.
    """

    toks = [t for t in (text or "").split(" ") if t]
    out: list[str] = []
    removed: set[str] = set()
    for tok in toks:
        if tok in FAQ_STOPWORDS:
            removed.add(tok)
            continue
        # 1글자 조사는 제거
        if len(tok) == 1 and tok in FAQ_STOPWORDS:
            removed.add(tok)
            continue
        out.append(tok)
    # 중복 제거(순서 유지)
    seen: set[str] = set()
    dedup: list[str] = []
    for t in out:
        if t in seen:
            continue
        seen.add(t)
        dedup.append(t)
    return dedup[:24]


def _canonicalize(normalized: str, tokens: list[str]) -> str:
    """exact/contains 기반 canonical 매핑."""

    if not normalized:
        return ""
    if normalized in FAQ_CANONICAL_MAP:
        return FAQ_CANONICAL_MAP[normalized]

    # contains match
    blob = " " + normalized + " "
    # 가장 중요한 intent부터 체크(입장/시간/기간/시작/등록/셔틀/무료)
    if "입장" in blob and "시간" in blob:
        if "가능" in blob or "마감" in blob:
            return "입장 시간"
        return "관람 시간"
    if "기간" in blob:
        return "기간"
    if "시작" in blob or "시작일" in blob:
        return "시작일"
    if "셔틀" in blob:
        return "셔틀 운행 시간" if "시간" in blob or "운행" in blob or "버스" in blob else "셔틀 운행 시간"
    if "등록" in blob:
        return "사전등록"
    if "무료" in blob or "입장료" in blob or "비용" in blob:
        return "입장료"
    if "배지" in blob or "출입증" in blob:
        if any(x in blob for x in ("수령", "발급", "등록대", "위치", "어디")):
            return "출입증 수령 위치"
        return "출입증"
    if "오시는" in blob or "교통" in blob or "대중교통" in blob or "지하철" in blob:
        return "오시는 길"
    if "주차" in blob and ("요금" in blob or "비용" in blob or "얼마" in blob or "주차비" in blob):
        return "주차 요금"

    # token 기반 fallback
    if "기간" in tokens:
        return "기간"
    if "무료" in tokens:
        return "입장료"
    return normalized


def normalize_faq_query(query: str) -> dict:
    """한국어 FAQ 정규화 결과를 dict로 반환.

    반환 예시:
    {
      raw, normalized, canonical, tokens, removed_stopwords, removed_endings
    }
    """

    raw = query or ""
    base = _basic_normalize(raw)
    base2, removed_endings = _strip_endings(base)
    tokens = _tokenize_ko(base2)

    # 불필요 단어 제거 후 normalized 문자열 재구성
    removed_stopwords = [t for t in (base2.split(" ")) if t in FAQ_STOPWORDS]
    normalized = " ".join([t for t in tokens if t not in FAQ_STOPWORDS]).strip()

    canonical = _canonicalize(normalized, tokens)

    logger.info(
        "[faq_normalize] raw=%s normalized=%s canonical=%s tokens=%s removed_endings=%s",
        raw[:80],
        normalized[:80],
        canonical[:80],
        tokens[:12],
        len(removed_endings),
    )

    return {
        "raw": raw,
        "normalized": normalized,
        "canonical": canonical,
        "tokens": [t for t in tokens if t and t not in FAQ_STOPWORDS],
        "removed_stopwords": removed_stopwords,
        "removed_endings": removed_endings,
    }

