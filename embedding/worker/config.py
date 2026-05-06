from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# pydantic 의 env_file=".env" 는 **프로세스 cwd** 기준이라,
# 레포 루트 등에서 `python -m worker.main` 하면 embedding/.env 가 안 읽히고
# REDIS_URL 기본값(127.0.0.1)으로 붙어 **메인과 다른 Redis 의 빈 queue:llm** 만 BLPOP 하게 된다.
_EMBEDDING_ROOT = Path(__file__).resolve().parent.parent


class WorkerSettings(BaseSettings):
    """워커는 메인(API) Redis 큐를 소비한다. EC2 분리 배포 시 localhost / docker 서비스명이면 큐 미처리."""

    model_config = SettingsConfigDict(
        env_file=(str(_EMBEDDING_ROOT / ".env"),),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    redis_url: str = Field(
        default="redis://127.0.0.1:6379/0",
        description="/chat 가 쌓는 큐와 동일한 Redis (main 앱 REDIS_URL 과 일치)",
    )
    postgres_dsn: str = Field(
        default="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/chatbot",
        description="임베딩 큐 소비용 async DSN",
    )
    api_base_url: str = Field(
        default="http://127.0.0.1:8000",
        description="메인 FastAPI 공개 주소 (검색·챗 UI). docker compose 내부 호스트명 api 는 원격 워커에서 쓰지 말 것",
    )

    llm_queue_name: str = "queue:llm"
    embedding_queue_name: str = "queue:embedding"
    llm_result_prefix: str = "result:llm:"
    llm_stream_prefix: str = "stream:llm:"
    llm_trace_prefix: str = "trace:llm:"
    embed_result_prefix: str = "result:embed:"

    embed_batch_size: int = 32
    max_retry: int = 3
    retrieval_model_id: str = "Qwen/Qwen3-Embedding-0.6B"
    retrieval_device: str = "cpu"
    retrieval_top_k: int = 6
    openai_model: str = Field(
        default="gpt-4o-mini",
        description="메인 검색 폼·워커 fallback 라우팅 OpenAI 라우터 공통 모델",
    )

    openai_api_key: str = ""
    openai_base_url: str = ""
    worker_general_fallback_openai: bool = Field(
        default=True,
        description="휴리스틱이 general 일 때 FAQ 힌트가 없으면 OpenAI로 company/product 등 라우팅 재판",
    )

    # 챗봇 → API 검색 시 Form으로 전달 — False면 검색축 모호 시 OpenAI 재분류(7단계)가 아예 타지 않음
    retrieval_intent_use_openai: bool = True
    retrieval_min_queries: int = 4
    retrieval_max_queries: int = 4
    retrieval_score_cutoff: float = 0.25
    retrieval_evidence_ratio: float = 0.45
    retrieval_rrf_k: int = 60
    retrieval_context_limit: int = 4
    retrieval_top_k_per_query: int | None = 4


settings = WorkerSettings()
