from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    # 워커는 별도 EC2에서 실행되므로 동일 Redis/Postgres 접속 정보만 공유한다.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    redis_url: str = "redis://localhost:6379/0"
    postgres_dsn: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/chatbot"
    api_base_url: str = "http://api:8000"

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
    openai_model: str = "gpt-4o-mini"

    # 챗봇 → API 검색 시 Form으로 전달 (미설정 시 API 쪽 환경 기본)
    # retrieval_intent_use_openai: bool = True
    retrieval_intent_use_openai: bool = False
    retrieval_min_queries: int = 2
    retrieval_max_queries: int = 2
    retrieval_score_cutoff: float = 0.25
    retrieval_evidence_ratio: float = 0.45
    retrieval_rrf_k: int = 60
    retrieval_context_limit: int = 4
    retrieval_top_k_per_query: int | None = 4


settings = WorkerSettings()
