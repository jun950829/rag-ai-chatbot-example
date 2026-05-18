from app.rag.faq.reranker import compute_rerank_score


def test_rerank_exact() -> None:
    s = compute_rerank_score("전시 시간", "전시 시간")
    assert s.exact == 1.0
    assert s.total > 0.9


def test_rerank_overlap() -> None:
    s = compute_rerank_score("셔틀 시간", "셔틀 운행 시간")
    assert s.token_overlap > 0.0

