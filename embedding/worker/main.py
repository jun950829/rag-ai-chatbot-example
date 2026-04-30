import asyncio
import logging
import sys

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
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
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
