"""FAQ 문자열 기반 Reranker (embedding 금지).

요구사항:
- exact match boost
- substring boost
- token overlap
- levenshtein 유사(외부 의존성 없이 difflib 기반)

주의:
- 이 점수는 DB(Fts/Trgm/Alias) 후보를 "재정렬"하기 위한 보정치다.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from .normalize import normalize_faq_text


def _tokenize_simple(text: str) -> list[str]:
    # 한국어 형태소 분석 등은 의존성/비용이 커서 여기서는 최소 토큰화만 사용
    toks = [t for t in (text or "").split(" ") if len(t) >= 2]
    # 중복 제거(순서 유지)
    seen: set[str] = set()
    out: list[str] = []
    for t in toks:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out[:24]


@dataclass(frozen=True)
class RerankScore:
    exact: float
    substring: float
    token_overlap: float
    seq_ratio: float

    @property
    def total(self) -> float:
        # 가중치는 FAQ에서 "문자열이 거의 동일"할수록 강하게 끌어올리도록 설계
        return (
            (self.exact * 1.0)
            + (self.substring * 0.35)
            + (self.token_overlap * 0.35)
            + (self.seq_ratio * 0.25)
        )


def compute_rerank_score(query: str, candidate_text: str) -> RerankScore:
    q = normalize_faq_text(query)
    c = normalize_faq_text(candidate_text)
    if not q or not c:
        return RerankScore(exact=0.0, substring=0.0, token_overlap=0.0, seq_ratio=0.0)

    exact = 1.0 if q == c else 0.0
    substring = 1.0 if (q in c or c in q) else 0.0

    qt = _tokenize_simple(q)
    ct = _tokenize_simple(c)
    if not qt or not ct:
        token_overlap = 0.0
    else:
        hit = sum(1 for t in qt if t in set(ct))
        token_overlap = hit / max(1, len(qt))

    seq_ratio = float(SequenceMatcher(a=q, b=c).ratio())
    return RerankScore(exact=exact, substring=substring, token_overlap=token_overlap, seq_ratio=seq_ratio)

