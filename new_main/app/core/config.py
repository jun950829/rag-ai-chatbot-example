from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _strip_env_assignment_value(raw: str) -> str:
    v = raw.strip()
    if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
        return v[1:-1]
    return v


def _merge_env_file_into_environ(path: Path) -> None:
    """`.env` 를 os.environ 에 합친다. Docker `-e` / 이미 설정된 값은 덮어쓰지 않음.

    Pydantic 기본 `env_file=\".env\"` 는 **cwd** 기준이라, 컨테이너 cwd 와 레포의 `new_main/.env` 가
    어긋나면 `EMBEDDING_SERVICE_URL` 등이 비어 ``RuntimeError`` 가 난다.
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


# app/core/config.py → parents[2] == new_main/ (Docker 에서 코드가 /srv/main/app 이면 /srv/main)
_NEW_MAIN_ROOT = Path(__file__).resolve().parents[2]
_merge_env_file_into_environ(Path.cwd() / ".env")
_merge_env_file_into_environ(_NEW_MAIN_ROOT / ".env")


def _env_files_for_settings() -> tuple[str, ...]:
    seen: set[Path] = set()
    out: list[str] = []
    for cand in (Path.cwd() / ".env", _NEW_MAIN_ROOT / ".env"):
        if cand.is_file():
            rp = cand.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            out.append(str(cand))
    return tuple(out) if out else (".env",)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_files_for_settings(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "chatbot-api"
    app_env: str = "production"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = "gpt-4o-mini"
    intent_use_openai: bool = True

    redis_url: str = ""

    postgres_dsn: str = ""
    embedding_service_url: str = ""
    retrieval_model_id: str = "Qwen/Qwen3-Embedding-0.6B"
    retrieval_device: str = "cpu"
    retrieval_top_k: int = 8
    # 짧거나 휴리스틱으로 축이 안 잡힐 때: LLM으로 3~5개 검색 쿼리 생성 후 RRF
    retrieval_multiquery_min: int = 3
    retrieval_multiquery_max: int = 5
    retrieval_multiquery_short_chars: int = 45
    retrieval_expand_queries_use_openai: bool = True


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
