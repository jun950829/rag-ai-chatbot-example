from app.rag.faq.normalize import normalize_faq_query


def test_normalize_basic() -> None:
    assert normalize_faq_query("  전시   시간?? ") == "전시 시간"


def test_normalize_synonym_badge() -> None:
    # 최소 동의어 치환: 배지/입장 배지 → 출입증
    assert "출입증" in normalize_faq_query("배지 수령 위치")

