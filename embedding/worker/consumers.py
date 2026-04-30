import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from worker.config import settings
from worker.embedding import build_embeddings_batch
from worker.llm import classify_intent_heuristic, stream_text_tokens
from worker.queue import WorkerQueue

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True, echo=False)


async def _trace(
    redis: Redis,
    *,
    request_id: str,
    stage: str,
    status: str,
    detail: str,
    data: dict[str, Any] | None = None,
) -> None:
    trace_key = f"{settings.llm_trace_prefix}{request_id}"
    payload = {
        "time": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "status": status,
        "detail": detail,
    }
    if data:
        payload["data"] = data
    await redis.rpush(trace_key, json.dumps(payload, ensure_ascii=False))
    await redis.expire(trace_key, 3600)


async def _answer_retrieval(redis: Redis, *, request_id: str, session_id: str, message: str) -> dict[str, Any]:
    endpoint = f"{settings.api_base_url.rstrip('/')}/tools/embedding/api/search"
    form_data = {
        "session_id": session_id,
        "query": message,
        "model_id": settings.retrieval_model_id,
        "device": settings.retrieval_device,
        "top_k": str(settings.retrieval_top_k),
        "chunk_type": "all",
        "answer_mode": "openai",
        "openai_model": settings.openai_model,
    }
    logger.info("[worker] retrieval POST %s session_id=%s", endpoint, (session_id or "")[:40])
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(endpoint, data=form_data)
    try:
        payload = response.json() if response.content else {}
    except json.JSONDecodeError:
        body_preview = (response.text or "")[:300]
        raise RuntimeError(f"retrieval non-json response: status={response.status_code}, body={body_preview}") from None
    if not response.is_success:
        detail = payload.get("detail") if isinstance(payload, dict) else response.text
        raise RuntimeError(f"retrieval failed: {detail}")

    logger.info(
        "[worker] retrieval OK answer_chars=%d",
        len(str(payload.get("answer_korean") or "")),
    )

    # API가 생성한 step_logs(검색/ RRF/ OpenAI 등)를 워커 trace로 펼쳐서 저장한다.
    try:
        retrieval = payload.get("retrieval") if isinstance(payload, dict) else None
        step_logs = (retrieval or {}).get("step_logs") if isinstance(retrieval, dict) else None
        if isinstance(step_logs, list):
            for s in step_logs:
                if not isinstance(s, dict):
                    continue
                step = s.get("step")
                title = str(s.get("title", "") or "-")
                detail = str(s.get("detail", "") or "")
                await _trace(
                    redis,
                    request_id=request_id,
                    stage=f"retrieval_step_{step}",
                    status="done",
                    detail=f"{title} · {detail}",
                    data={"step": step, "title": title, "detail": detail},
                )
    except Exception:
        # 로깅 실패는 본 흐름을 막지 않는다.
        pass
    return payload


def _heuristic_answer(intent: str) -> str:
    if intent == "greeting":
        return "안녕하세요. 전시 참가업체 챗봇입니다. 찾고 싶은 업체나 제품을 말씀해 주세요."
    if intent == "follow_up":
        return "좋아요. 이전 맥락을 이어서 도와드릴게요. 어떤 조건을 더 확인할까요?"
    if intent == "not_related":
        return "현재는 전시 참가업체/제품 관련 질문만 답변할 수 있어요."
    if intent == "general":
        return "전시·참가업체와 무관한 일반 대화로 보입니다. 전시나 업체·제품에 대해 물어봐 주시면 더 잘 도와드릴 수 있어요."
    return "요청을 처리했습니다."


async def llm_consumer(redis: Redis) -> None:
    queue = WorkerQueue(redis)
    while True:
        job = await queue.pop(settings.llm_queue_name)
        if not job:
            await asyncio.sleep(0.1)
            continue

        request_id = job["request_id"]
        stream_key = f"{settings.llm_stream_prefix}{request_id}"
        cache_key = job["cache_key"]
        retries = int(job.get("retries", 0))
        session_id = str(job.get("session_id", "")).strip()
        session_intent_key = f"chat:session:{session_id}:last_intent" if session_id else ""

        try:
            logger.info("[worker] job start request_id=%s retry=%s", request_id, retries)
            await _trace(
                redis,
                request_id=request_id,
                stage="worker_consume",
                status="started",
                detail=f"워커가 큐 메시지 수신 (retry={retries})",
            )
            prev_intent = await redis.get(session_intent_key) if session_intent_key else None
            intent = classify_intent_heuristic(job["message"], previous_intent=prev_intent)
            logger.info("[worker] heuristic intent=%s (prev=%s)", intent, prev_intent or "-")
            await _trace(
                redis,
                request_id=request_id,
                stage="intent_classification",
                status="done",
                detail=f"분류 결과: {intent} (previous_intent={prev_intent or '-'})",
            )

            suggestion_cards: list[Any] = []
            if intent in {"company", "product", "follow_up"}:
                await _trace(
                    redis,
                    request_id=request_id,
                    stage="retrieval",
                    status="started",
                    detail="검색 → RRF → OpenAI 단계 시작",
                )
                payload = await _answer_retrieval(redis, request_id=request_id, session_id=session_id, message=job["message"])
                answer = str(payload.get("answer_korean") or "검색 결과 기반 답변을 생성하지 못했습니다.")
                raw_cards = payload.get("suggestion_cards")
                suggestion_cards = raw_cards if isinstance(raw_cards, list) else []
                logger.info(
                    "[worker] retrieval path done request_id=%s cards=%d",
                    request_id,
                    len(suggestion_cards),
                )
                await _trace(
                    redis,
                    request_id=request_id,
                    stage="retrieval",
                    status="done",
                    detail="검색 → RRF → OpenAI 단계 완료",
                )
            else:
                answer = _heuristic_answer(intent)
                logger.info("[worker] heuristic-only answer request_id=%s", request_id)
                await _trace(
                    redis,
                    request_id=request_id,
                    stage="heuristic_response",
                    status="done",
                    detail=f"{intent} 규칙 응답 완료",
                )

            # 최종 답변을 토큰 단위로 흘려 SSE로 전달한다.
            await _trace(
                redis,
                request_id=request_id,
                stage="sse_stream",
                status="started",
                detail="SSE 토큰 스트리밍 시작",
            )
            async for token in stream_text_tokens(answer):
                await redis.rpush(stream_key, json.dumps({"event": "token", "data": token}, ensure_ascii=False))

            if suggestion_cards:
                await redis.rpush(
                    stream_key,
                    json.dumps({"event": "cards", "data": suggestion_cards}, ensure_ascii=False),
                )

            await redis.set(cache_key, answer, ex=600)
            if session_intent_key:
                await redis.set(session_intent_key, intent, ex=3600)
            await redis.rpush(stream_key, json.dumps({"event": "done", "data": "[DONE]"}, ensure_ascii=False))
            await redis.expire(stream_key, 600)
            await _trace(
                redis,
                request_id=request_id,
                stage="sse_stream",
                status="done",
                detail="응답 완료 이벤트 전송",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("[worker] job failed request_id=%s: %s", request_id, exc)
            await _trace(
                redis,
                request_id=request_id,
                stage="worker_error",
                status="error",
                detail=f"{type(exc).__name__}: {exc}",
            )
            if retries < settings.max_retry:
                job["retries"] = retries + 1
                await queue.requeue(settings.llm_queue_name, job)
            else:
                await redis.rpush(stream_key, json.dumps({"event": "error", "data": str(exc)}, ensure_ascii=False))
                await redis.rpush(stream_key, json.dumps({"event": "done", "data": "[DONE]"}, ensure_ascii=False))


async def _upsert_embeddings(document_id: str, chunks: list[str], vectors: list[list[float]]) -> None:
    async with engine.begin() as conn:
        for idx, (chunk, vector) in enumerate(zip(chunks, vectors, strict=False)):
            # pgvector는 문자열 표현('[0.1,0.2,...]')으로도 삽입 가능하다.
            vector_text = "[" + ",".join(f"{v:.8f}" for v in vector) + "]"
            await conn.execute(
                text(
                    """
                    INSERT INTO document_chunks (document_id, chunk_index, chunk_text, embedding)
                    VALUES (:document_id, :chunk_index, :chunk_text, CAST(:embedding AS vector))
                    ON CONFLICT (document_id, chunk_index)
                    DO UPDATE SET
                        chunk_text = EXCLUDED.chunk_text,
                        embedding = EXCLUDED.embedding,
                        updated_at = NOW()
                    """
                ),
                {
                    "document_id": document_id,
                    "chunk_index": idx,
                    "chunk_text": chunk,
                    "embedding": vector_text,
                },
            )


async def embedding_consumer(redis: Redis) -> None:
    queue = WorkerQueue(redis)
    pending_jobs: list[dict[str, Any]] = []
    while True:
        job = await queue.pop(settings.embedding_queue_name, timeout=1)
        if job:
            pending_jobs.append(job)

        if not pending_jobs:
            await asyncio.sleep(0.05)
            continue

        # 단일 워커에서 배치(기본 32)로 모아 처리해 모델 호출 횟수를 줄인다.
        batch_jobs = pending_jobs[: settings.embed_batch_size]
        pending_jobs = pending_jobs[settings.embed_batch_size :]

        try:
            for embed_job in batch_jobs:
                chunks = embed_job.get("chunks", [])
                vectors = build_embeddings_batch(chunks)
                await _upsert_embeddings(embed_job["document_id"], chunks, vectors)
                result_key = f"{settings.embed_result_prefix}{embed_job['request_id']}"
                await redis.set(result_key, json.dumps({"status": "done"}, ensure_ascii=False), ex=600)
        except Exception as exc:  # noqa: BLE001
            for embed_job in batch_jobs:
                retries = int(embed_job.get("retries", 0))
                if retries < settings.max_retry:
                    embed_job["retries"] = retries + 1
                    await queue.requeue(settings.embedding_queue_name, embed_job)
                else:
                    result_key = f"{settings.embed_result_prefix}{embed_job['request_id']}"
                    await redis.set(
                        result_key,
                        json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False),
                        ex=600,
                    )
