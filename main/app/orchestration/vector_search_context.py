"""벡터 검색 오케스트레이션용 입력 + 런타임 상태."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import uuid

from openai import AsyncOpenAI

from app.rag.retrieval.memory import ConversationMemory


@dataclass
class VectorSearchContext:
    """``run_vector_search`` 와 동일한 입력; 파이프라인이 필드를 채운다."""

    query: str
    model_id: str
    device: str | None
    top_k: int
    chunk_type: str
    answer_mode: str
    openai_model: str
    openai_api_key: str
    openai_base_url: str
    embedding_remote_base_url: str | None
    memory: ConversationMemory | None = None
    session_id: str | None = None
    faq_only: bool = False
    faq_user: str | None = None
    intent_use_openai: bool | None = None
    retrieval_min_queries: int | None = None
    retrieval_max_queries: int | None = None
    retrieval_score_cutoff: float | None = None
    retrieval_evidence_ratio: float | None = None
    retrieval_rrf_k: int | None = None
    retrieval_context_limit: int | None = None
    retrieval_top_k_per_query: int | None = None

    t_search_wall0: float = 0.0
    ext_marker: str | None = None
    payload_typ: str | None = None
    payload_lang: str | None = None
    openai_client: AsyncOpenAI | None = None
    key: str = ""
    db_memory: ConversationMemory | None = None
    has_history: bool = False
    session_uuid_for_save: uuid.UUID | None = None
    fu_state: tuple[bool, float, dict] | None = None
    tuning_meta: dict[str, Any] = field(default_factory=dict)
    i_openai: bool = False
    min_q: int = 1
    max_q: int = 1
    sc: float = 0.0
    er: float = 0.5
    rk: int = 1
    cl: int = 1
    tkpq: int = 6
    retrieval_payload: dict[str, Any] | None = None
    results: list[dict[str, Any]] = field(default_factory=list)
    response_mode: str = ""
    answer_korean: str = ""
    answer_meta: dict[str, Any] = field(default_factory=dict)
    step_logs: list[dict[str, Any]] = field(default_factory=list)
    openai_usage: dict[str, Any] = field(default_factory=dict)
    suggestion_cards: list[dict[str, Any]] = field(default_factory=list)
    followups_rag: list[dict[str, Any]] = field(default_factory=list)
