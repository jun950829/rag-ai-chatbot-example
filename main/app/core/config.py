from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Exmatch RAG Template"
    app_env: str = "local"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_reload: bool = False
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=list)

    database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/rag_template"
    redis_url: str = "redis://redis:6379/0"
    llm_queue_name: str = "queue:llm"
    embedding_queue_name: str = "queue:embedding"
    llm_stream_prefix: str = "stream:llm:"
    llm_trace_prefix: str = "trace:llm:"
    chat_cache_prefix: str = "cache:chat:"
    chat_cache_ttl_seconds: int = 600

    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = "gpt-4.1-mini"
    embed_provider: str = "openai"
    embed_api_url: str = ""

    default_embed_dim: int = 1536
    default_retrieval_top_k: int = 5

    # --- RAG 검색 부하·의도 OpenAI (API 폼 미전달 시 기본값) ---
    retrieval_intent_use_openai: bool = True
    retrieval_min_queries: int = 2
    retrieval_max_queries: int = 2
    retrieval_score_cutoff: float = 0.25
    retrieval_evidence_ratio: float = 0.45
    retrieval_rrf_k: int = 60
    retrieval_context_limit: int = 4
    # 쿼리당 상한(속도 우선 기본값)
    retrieval_top_k_per_query: int | None = 4

    # Base URL of the local embedding inference server (host machine), e.g. http://host.docker.internal:8765
    embedding_service_url: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        raise TypeError("CORS_ORIGINS must be a comma-separated string or list.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
