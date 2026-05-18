from __future__ import annotations

import re

# ── 공손 표현 (longest-first, 문장 끝에서 제거) ─────────────────

_POLITE_TAILS = (
    "추천해 주세요", "설명해 주세요", "알려 주세요", "보여 주세요", "찾아 주세요",
    "추천해주세요", "설명해주세요", "알려주세요", "보여주세요", "찾아주세요",
    "알고 싶습니다", "알고싶습니다", "알고 싶어요", "알고싶어요",
    "할 수 있나요", "할수있나요", "부탁드립니다", "부탁합니다",
    "추천해 줘", "설명해 줘", "알려 줘", "보여 줘", "찾아 줘",
    "추천해줘", "설명해줘", "알려줘", "보여줘", "찾아줘",
    "궁금합니다", "궁금해요", "있습니까", "있을까요",
    "해 주세요", "해주세요", "있나요", "있어요", "있는지",
    "해 줘", "해줘", "궁금해", "인가요", "뭔가요", "뭘까요",
    "뭐에요", "뭐야", "하나요", "할까요",
    "주세요", "줘요",
)

# ── 조사 (한글 2자 이상 단어 끝에서만) ───────────────────────────

_PARTICLE_RE = re.compile(
    r"^([\uAC00-\uD7A3]{2,}?)"
    r"(에서는|으로는|에서|으로|에게|한테|부터|까지"
    r"|는|은|이|가|을|를|에|로|와|과|의|도|만)$"
)

# ── 명확한 오타 ──────────────────────────────────────────────────

_TYPO_MAP = {
    "참가업채": "참가업체",
    "제풍": "제품",
    "재품": "제품",
    "겁색": "검색",
    "엄체": "업체",
    "업채": "업체",
    "카탈록": "카탈로그",
    "전시품목록": "전시품 목록",
    "젼시회": "전시회",
}

_TYPO_RE = re.compile(
    "|".join(re.escape(k) for k in sorted(_TYPO_MAP, key=len, reverse=True))
)

# ── 띄어쓰기 보정 (붙어쓰기 빈출 패턴) ─────────────────────────

_SPACING_FIXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(참가업체)(목록|리스트|검색|추천|정보|소개)"), r"\1 \2"),
    (re.compile(r"(전시)(제품|업체|품목|기업|장비)"), r"\1 \2"),
    (re.compile(r"(제품)(검색|목록|리스트|추천|정보|소개)"), r"\1 \2"),
    (re.compile(r"(부스)(번호|위치|안내)"), r"\1 \2"),
    (re.compile(r"(전시회)(정보|안내|일정|참가)"), r"\1 \2"),
    (re.compile(r"(카테고리)(목록|검색|리스트)"), r"\1 \2"),
]


def _strip_polite_tail(text: str) -> str:
    for tail in _POLITE_TAILS:
        if text.endswith(tail):
            core = text[: -len(tail)].rstrip()
            if core:
                return core
    return text


def _fix_typos(text: str) -> str:
    return _TYPO_RE.sub(lambda m: _TYPO_MAP[m.group()], text)


def _fix_spacing(text: str) -> str:
    for pat, repl in _SPACING_FIXES:
        text = pat.sub(repl, text)
    return text


def _strip_particles(text: str) -> str:
    out: list[str] = []
    for w in text.split():
        m = _PARTICLE_RE.match(w)
        out.append(m.group(1) if m else w)
    return " ".join(out)


async def normalize_question(text: str) -> str:
    q = " ".join((text or "").strip().split())
    if not q:
        return q
    q = _fix_typos(q)
    q = _strip_polite_tail(q)
    q = _fix_spacing(q)
    q = _strip_particles(q)
    return " ".join(q.split())
