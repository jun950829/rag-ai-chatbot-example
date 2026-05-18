"""정규화된 질문의 언어를 판별한다 (ko / en).

한글·영어 글자 수 비율로 판별. 영어 비율이 threshold 이상이면 en.
"""

from __future__ import annotations

import re

_HANGUL = re.compile(r"[\uac00-\ud7a3]")
_ENGLISH = re.compile(r"[A-Za-z]")

ENGLISH_THRESHOLD = 0.7


def detect_language(text: str, *, threshold: float = ENGLISH_THRESHOLD) -> str:
    """``'ko'`` 또는 ``'en'`` 을 반환한다."""
    t = (text or "").strip()
    if not t:
        return "ko"
    hangul = len(_HANGUL.findall(t))
    english = len(_ENGLISH.findall(t))
    total = hangul + english
    if total == 0:
        return "ko"
    if english / total >= threshold:
        return "en"
    return "ko"
