import asyncio

from redis.asyncio import Redis

from worker.config import settings
from worker.consumers import embedding_consumer, llm_consumer


async def run_worker() -> None:
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
