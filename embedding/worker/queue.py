import json
from typing import Any

from redis.asyncio import Redis


class WorkerQueue:
    """워커 전용 Redis 큐 래퍼 (BLPOP + 재적재)."""

    def __init__(self, redis: Redis):
        self.redis = redis

    async def pop(self, queue_name: str, timeout: int = 3) -> dict[str, Any] | None:
        item = await self.redis.blpop(queue_name, timeout=timeout)
        if not item:
            return None
        _, raw = item
        return json.loads(raw)

    async def requeue(self, queue_name: str, payload: dict[str, Any]) -> None:
        await self.redis.rpush(queue_name, json.dumps(payload, ensure_ascii=False))
