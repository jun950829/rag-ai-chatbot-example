import asyncio
import logging
import sys
from urllib.parse import urlparse

from redis.asyncio import Redis

from worker.config import settings
from worker.consumers import embedding_consumer, llm_consumer


_worker_logging_configured = False


def _configure_worker_logging() -> None:
    global _worker_logging_configured
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    logging.getLogger("worker").setLevel(logging.INFO)
    if _worker_logging_configured:
        return
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(h)
    _worker_logging_configured = True


async def run_worker() -> None:
    _configure_worker_logging()
    log = logging.getLogger("worker")
    ru = urlparse(settings.redis_url)
    log.info(
        "worker start redis_host=%s redis_port=%s queue=%s api_base=%s",
        ru.hostname or "",
        ru.port or "",
        settings.llm_queue_name,
        settings.api_base_url.rstrip("/"),
    )
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        await redis.ping()
    except Exception as exc:
        log.error(
            "Redis 연결 실패(%s). .env 의 REDIS_URL 을 메인(API) 과 동일한 인스턴스로 두었는지, "
            "보안그룹 6379 인바운드를 확인하세요.",
            exc,
        )
        raise SystemExit(1) from exc
    try:
        # 하나의 워커 프로세스에서 LLM 큐와 임베딩 큐를 동시 소비한다.
        await asyncio.gather(
            llm_consumer(redis),
            embedding_consumer(redis),
        )
    finally:
        await redis.close()


if __name__ == "__main__":
    asyncio.run(run_worker())
