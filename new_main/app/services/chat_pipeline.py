"""메인 챗봇 파이프라인 — chat_stream 하나로 흐름을 한 눈에 본다.

1) 질문 정규화
2) 언어 감지 (한글 ↔ 영어)
3) 답변 캐시 조회
4) 의도 분류 + early exit (greeting / empty)
5) retrieval+cards 캐시 조회
6) 검색용 다중 쿼리 계획
7) pgvector 검색 + RRF
8) 카드 생성 + 카탈로그 hydrate
9) 리스트형 → LLM 생략, retrieval+cards 캐시 저장
10) 프롬프트 조립 → LLM 스트리밍
11) 답변 캐시 저장
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.observability.tracing import trace_stage
from app.services.steps.cache import (
    get_cached_answer,
    get_retrieval_cards_cache,
    save_cached_answer,
    save_retrieval_cards_cache,
)
from app.services.steps.intent import (
    classify_intent,
    is_list_response,
    list_short_answer,
    resolve_early_exit,
)
from app.services.steps.language import detect_language
from app.services.steps.llm_stream import stream_llm_answer
from app.services.steps.make_cards import make_cards
from app.services.steps.normalize import normalize_question
from app.services.steps.prompt import build_chat_messages
from app.services.steps.retrieval import retrieve_answer_context
from app.services.steps.search_queries import plan_retrieval_search_queries


async def chat_stream(
    *, session_id: str, message: str,
) -> tuple[list[dict[str, Any]], AsyncIterator[str]]:
    """(제안 카드 리스트, LLM 토큰 스트림)."""

    # 1) 정규화
    async with trace_stage("chat.normalize"):
        normalized = await normalize_question(message)

    if not (normalized or "").strip():
        async def _empty() -> AsyncIterator[str]:
            yield "질문이 비어 있습니다."
        return [], _empty()

    # 2) 언어 감지
    async with trace_stage("chat.detect_language"):
        language = detect_language(normalized)

    # 3) 답변 캐시
    async with trace_stage("chat.cache_check"):
        cached = await get_cached_answer(normalized)
    if cached is not None:
        async def _cached_answer() -> AsyncIterator[str]:
            yield cached
        return [], _cached_answer()

    # 4) 의도 분류 + early exit
    async with trace_stage("chat.intent"):
        intent = await classify_intent(normalized)

    early = resolve_early_exit(intent, normalized, language)
    if early is not None:
        return early

    # 5) retrieval+cards 캐시
    async with trace_stage("chat.retrieval_cards_cache"):
        rc_cached = await get_retrieval_cards_cache(normalized)
    if rc_cached is not None:
        async def _cached_list() -> AsyncIterator[str]:
            yield rc_cached["short_answer"]
        return rc_cached["cards"], _cached_list()

    # 6) 검색 쿼리
    async with trace_stage("chat.search_queries"):
        search_queries = await plan_retrieval_search_queries(
            normalized, intent, language=language,
        )

    # 7) 검색
    async with trace_stage("chat.retrieval"):
        ctx, rows = await retrieve_answer_context(
            query=normalized, intent=intent, session_id=session_id,
            search_queries=search_queries, language=language,
        )

    # 8) 카드 + 카탈로그 hydrate
    async with trace_stage("chat.make_cards"):
        cards, enriched_ctx = await make_cards(
            rows=rows, context=ctx, query=normalized, language=language,
        )

    # 9) 리스트형 → LLM 생략, 캐시 저장
    if is_list_response(intent, len(cards)):
        short = list_short_answer(intent, language)
        async with trace_stage("chat.retrieval_cards_cache_save"):
            await save_retrieval_cards_cache(
                normalized, intent=intent, cards=cards, context=enriched_ctx,
                short_answer=short, language=language,
            )
        async def _list_answer() -> AsyncIterator[str]:
            yield short
        return cards, _list_answer()

    # 10) 프롬프트 → LLM
    async with trace_stage("chat.prompt"):
        messages = await build_chat_messages(
            query=normalized, intent=intent, context=enriched_ctx, language=language,
        )

    full_text: dict[str, str] = {"v": ""}

    # 11) 스트리밍 + 답변 캐시 저장
    async def _tokens() -> AsyncIterator[str]:
        try:
            async with trace_stage("chat.llm_stream"):
                async for piece in stream_llm_answer(messages=messages):
                    full_text["v"] += piece
                    yield piece
        finally:
            async with trace_stage("chat.cache_save"):
                if full_text["v"]:
                    await save_cached_answer(normalized, full_text["v"])

    return cards, _tokens()
