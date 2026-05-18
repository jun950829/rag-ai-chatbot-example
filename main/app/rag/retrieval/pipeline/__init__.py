"""의미 검색 파이프라인 — 단계 순서만 명시 (구현은 ``orchestrator``).

추후 ``normalize`` / ``intent`` 등 파일로 쪼갤 때 이 모듈의 ``RETRIEVAL_STAGE_ORDER`` 를 기준으로 한다.
"""

from app.rag.retrieval.orchestrator import execute_retrieval_pipeline

RETRIEVAL_STAGE_ORDER = (
    "normalize_query",
    "classify_intent",
    "detect_language",
    "plan_queries_or_skip",
    "vector_search_or_short_circuit",
    "fuse_rrf",
    "cutoff_and_context",
)

run_retrieval_pipeline = execute_retrieval_pipeline

__all__ = ["RETRIEVAL_STAGE_ORDER", "run_retrieval_pipeline", "execute_retrieval_pipeline"]
