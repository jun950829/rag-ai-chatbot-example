"""FAQ 검색 결과 모델.

API 응답 스펙은 `run_vector_search`에서 유지한다.
이 모듈은 FAQ 검색 엔진 내부 데이터 구조만 정의한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FaqCandidate:
    qna_code: str
    qa_user: str | None
    domain: str | None
    category: str | None
    subcategory: str | None
    quickmenu_label: str | None
    question_sample: str | None
    answer_sample: str | None
    links: str | None
    notes: str | None
    scores: dict[str, float]


@dataclass(frozen=True)
class FaqSearchResult:
    best: FaqCandidate | None
    candidates: list[FaqCandidate]
    trace: dict[str, Any]

