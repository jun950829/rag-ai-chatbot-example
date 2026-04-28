from __future__ import annotations

from dataclasses import dataclass

from app.rag.pipeline import DEFAULT_EMBEDDING_DEVICE, DEFAULT_EMBEDDING_MODEL_ID


@dataclass(frozen=True)
class RetrievalConfig:
    model_id: str = DEFAULT_EMBEDDING_MODEL_ID
    device: str | None = DEFAULT_EMBEDDING_DEVICE
    top_k_per_query: int = 12
    final_top_k: int = 10
    score_cutoff: float = 0.22
    evidence_ratio: float = 0.6
    min_queries: int = 3
    max_queries: int = 5
    rrf_k: int = 60
    context_limit: int = 6
