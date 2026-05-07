from app.rag.faq_synonyms import canonicalize_faq_query


def _canon(q: str) -> str:
    _raw, _norm, canon = canonicalize_faq_query(q)
    return canon


def test_time_canonical() -> None:
    assert _canon("전시 시간") == "관람 시간"
    assert _canon("운영 시간") == "관람 시간"
    assert _canon("행사 시간") == "관람 시간"


def test_shuttle_canonical() -> None:
    assert _canon("셔틀 시간") == "셔틀 운행 시간"
    assert _canon("셔틀버스") == "셔틀 운행 시간"


def test_register_canonical() -> None:
    assert _canon("등록 방법") == "사전등록"
    assert _canon("온라인 등록") == "사전등록"


def test_badge_canonical() -> None:
    assert _canon("배지") == "출입증"
    assert _canon("입장 배지") == "출입증"

