from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _strip_env_assignment_value(raw: str) -> str:
    v = raw.strip()
    if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
        return v[1:-1]
    return v


def _merge_env_file_into_environ(path: Path) -> None:
    """`.env` 를 os.environ 에 합친다.process 환경·Docker `-e` 가 이미 있으면 건드리지 않음.

    Pydantic `env_file=\".env\"` 는 **현재 작업 디렉터리**만 본다.Docker 에서 cwd=/srv/main 인데 레포에서는
    ``main/.env`` 에 두는 경우 로딩되지 않아 OPENAI 가 빈 문자열로 남는 일이 많다.
    """
    if not path.is_file():
        return
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line_raw in content.splitlines():
        line = line_raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key:
            continue
        if (os.environ.get(key) or "").strip():
            continue
        os.environ[key] = _strip_env_assignment_value(val)


_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_merge_env_file_into_environ(Path.cwd() / ".env")
_merge_env_file_into_environ(_SERVICE_ROOT / ".env")


def _env_files_for_settings() -> tuple[Path | str, ...]:
    paths: list[Path] = []
    for cand in (Path.cwd() / ".env", _SERVICE_ROOT / ".env"):
        if cand.is_file():
            rp = cand.resolve()
            if rp not in {p.resolve() for p in paths}:
                paths.append(cand)
    return tuple(paths) if paths else (".env",)


class Settings(BaseSettings):
    app_name: str = "Exmatch RAG Template"
    app_env: str = "local"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_reload: bool = False
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=list)

    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@db:5432/rag_template",
        validation_alias=AliasChoices("DATABASE_URL", "POSTGRES_DSN"),
    )
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
    retrieval_min_queries: int = 4
    retrieval_max_queries: int = 4
    retrieval_score_cutoff: float = 0.25
    retrieval_evidence_ratio: float = 0.45
    retrieval_rrf_k: int = 60
    retrieval_context_limit: int = 4
    # 쿼리당 상한(속도 우선 기본값)
    retrieval_top_k_per_query: int | None = 4

    # Base URL of the local embedding inference server (host machine), e.g. http://host.docker.internal:8765
    embedding_service_url: str = ""

    model_config = SettingsConfigDict(
        env_file=_env_files_for_settings(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
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


def resolve_openai_api_key() -> str:
    """Settings·환경변수 중 비어 있지 않은 값(우선 process env)."""
    s = get_settings()
    env_k = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if env_k:
        return env_k
    return (s.openai_api_key or "").strip()


def resolve_openai_base_url() -> str:
    s = get_settings()
    env_b = (os.environ.get("OPENAI_BASE_URL") or "").strip()
    if env_b:
        return env_b
    return (s.openai_base_url or "").strip()
