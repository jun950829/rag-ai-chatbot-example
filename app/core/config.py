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

    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    embed_provider: str = "openai"
    embed_api_url: str = ""

    default_embed_dim: int = 1536
    default_retrieval_top_k: int = 5

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
