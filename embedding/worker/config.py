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
    retrieval_top_k: int = 8
    openai_model: str = "gpt-4o-mini"


settings = WorkerSettings()
