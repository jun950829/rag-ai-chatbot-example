import asyncio
import logging
import sys
import time
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
    _h = (ru.hostname or "").lower()
    if _h == "redis":
        log.warning(
            "REDIS_URL 호스트가 'redis'(Compose 내부 이름)입니다. 임베딩 EC2에서는 풀이되지 않을 수 있습니다. "
            "메인(EC2-1)의 Redis 가 바인딩된 IP(사설 IP 권장)와 보안그룹 6379 인바운드를 사용하세요."
        )
    if _h in {"127.0.0.1", "localhost"}:
        log.warning(
            "REDIS_URL 가 localhost 입니다. 메인(API) Redis 가 다른 호스트면 큐 소비 없이 무한 대기합니다. embedding/.env 를 확인하세요."
        )
    # 원격 Redis 는 유휴/중간 장비에 의해 연결이 끊기는 경우가 있어 keepalive·주기 PING 을 켠다.
    redis = Redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        health_check_interval=30,
        socket_keepalive=True,
    )
    try:
        await redis.ping()
        qlen = await redis.llen(settings.llm_queue_name)
        log.info(
            "redis ping OK · list %s current length=%s (같은 Redis 를 쓰면 API 가 /chat 적재 후 여기 숫자가 늘어야 함)",
            settings.llm_queue_name,
            qlen,
        )
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
    # BLPOP 장시간 대기 등으로 끊긴 뒤 프로세스가 죽으면 큐가 쌓인다. 설정 오류(SystemExit) 외에는 재기동.
    while True:
        try:
            asyncio.run(run_worker())
            break
        except KeyboardInterrupt:
            raise
        except SystemExit:
            raise
        except BaseException:
            logging.getLogger("worker").exception("워커 예외 종료 · 5초 후 재시작")
            time.sleep(5)
