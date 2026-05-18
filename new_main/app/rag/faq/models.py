"""FAQ 검색 결과 모델 (내부용)."""

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
    question_sample_eng: str | None = None
    answer_sample_eng: str | None = None


@dataclass(frozen=True)
class FaqSearchResult:
    best: FaqCandidate | None
    candidates: list[FaqCandidate]
    trace: dict[str, Any]
