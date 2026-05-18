"""FAQ 게이트 및 ``external_id`` 직접 조회 단락 (벡터 검색 우회)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.core.config import get_settings
from app.core.logger import get_logger
from app.rag.entity_enrichment import enrich_results_with_entity_detail_sync
from app.rag.faq import FaqSearchService
from app.rag.pipeline import build_korean_search_answer, engine as sync_search_db_engine, sanitize_rag_results_for_user
from app.rag.suggestion_cards import build_retrieval_suggestion_cards
from app.orchestration.services.vsearch_answer_llm import (
    ANSWER_OPENAI_MODEL,
    generate_korean_answer_with_openai,
)
from app.orchestration.services.vsearch_bootstrap import resolve_answer_language_for_direct_lookup
from app.orchestration.services.vsearch_direct_db import direct_lookup_results_by_external_id_sync

logger = get_logger(__name__)

_FAQ_ONLY_NO_MATCH_KO = (
    "등록된 FAQ 안내에서 질문과 정확히 맞는 응답을 찾지 못했습니다.\n"
    "상단 카테고리 버튼으로 항목을 선택하거나, 더 구체적인 단어(키워드)를 넣어 다시 검색해 주세요.\n\n"
    "예) 출입증 수령 위치, 주차 요금, 사전등록 방법, 셔틀 운행 시간"
)


async def try_faq_gate_response(
    *,
    query: str,
    faq_only: bool,
    faq_user: str | None,
) -> dict[str, Any] | None:
    enable = bool(faq_only or (faq_user or "").strip())
    if not enable:
        return None
    trace_id = f"faq-{uuid.uuid4().hex[:10]}"
    faq_service = FaqSearchService(engine=sync_search_db_engine)
    faq_payload = await asyncio.to_thread(
        faq_service.search_and_build_payload,
        query=query,
        qa_user=(faq_user or "").strip() or None,
        faq_only=bool(faq_only),
        trace_id=trace_id,
        no_match_message=_FAQ_ONLY_NO_MATCH_KO,
    )
    if faq_payload is not None:
        return faq_payload
    return {
        "query": query,
        "count": 0,
        "results": [],
        "answer": _FAQ_ONLY_NO_MATCH_KO,
        "answer_meta": {"mode": "faq_no_match", "trace_id": trace_id},
        "cards": [],
        "follow_up_questions": [],
        "answer_korean": _FAQ_ONLY_NO_MATCH_KO,
        "suggestion_cards": [],
    }


async def try_direct_external_id_response(
    *,
    query: str,
    ext_marker: str | None,
    payload_typ: str | None,
    payload_lang: str | None,
    top_k: int,
    chunk_type: str,
    answer_mode: str,
    openai_base_url: str,
    key: str,
) -> dict[str, Any] | None:
    if not ext_marker:
        return None
    direct_results = await asyncio.to_thread(
        direct_lookup_results_by_external_id_sync,
        engine=sync_search_db_engine,
        external_id=ext_marker,
    )
    if not direct_results:
        return None
    if payload_typ in {"company", "product"}:
        direct_results = [r for r in direct_results if str(r.get("entity_type") or "") == payload_typ] or direct_results
    dl_lang = resolve_answer_language_for_direct_lookup(query, payload_lang)
    try:
        direct_results = await asyncio.to_thread(
            enrich_results_with_entity_detail_sync,
            engine=sync_search_db_engine,
            results=direct_results,
            language=dl_lang,
        )
    except Exception:
        logger.exception("[ENTITY_ENRICH] direct_lookup enrich failed (continuing)")
    u_floor = float(get_settings().retrieval_user_answer_min_score or 0.0)
    direct_results = sanitize_rag_results_for_user(direct_results, min_best_score=u_floor)
    dl_intent = payload_typ if payload_typ in {"company", "product"} else "general"
    dl_topic = payload_typ if payload_typ in {"company", "product"} else None
    if answer_mode == "openai" and key:
        try:
            answer_korean = await generate_korean_answer_with_openai(
                query=query,
                results=direct_results,
                api_key=key,
                base_url=(openai_base_url or "").strip(),
                model=ANSWER_OPENAI_MODEL,
                intent=dl_intent,
                language=dl_lang,
                retrieval_topic=dl_topic,
                is_dialog_followup=False,
            )
            answer_meta_dl: dict[str, Any] = {
                "mode": "direct_external_id_openai",
                "model": ANSWER_OPENAI_MODEL,
            }
        except Exception as e:  # noqa: BLE001
            logger.exception("[search] direct_lookup openai failed: %s", e)
            answer_korean = build_korean_search_answer(
                query,
                direct_results,
                intent=dl_intent,
                retrieval_topic=dl_topic,
                language=dl_lang,
            )
            answer_meta_dl = {"mode": "direct_external_id_template_fallback", "error": str(e)}
    else:
        answer_korean = build_korean_search_answer(
            query,
            direct_results,
            intent=dl_intent,
            retrieval_topic=dl_topic,
            language=dl_lang,
        )
        answer_meta_dl = {"mode": "direct_external_id"}
    suggestion_cards = await build_retrieval_suggestion_cards(direct_results, language=dl_lang)
    return {
        "query": query,
        "top_k": max(1, int(top_k)),
        "lang": dl_lang,
        "chunk_type": chunk_type,
        "count": len(direct_results),
        "retrieval": {
            "intent": "direct_lookup",
            "retrieval_topic": dl_topic,
            "is_dialog_followup": False,
            "language": dl_lang,
            "planned_queries": [],
            "llm_context": "",
            "rrf_candidates": len(direct_results),
            "step_logs": [],
            "response_mode": "direct_lookup",
            "embedding_remote_base_url": None,
            "openai_usage_summary": {"direct_lookup": True, "answer_mode": answer_mode},
            "tuning_applied": {},
        },
        "answer": answer_korean,
        "answer_meta": answer_meta_dl,
        "results": direct_results,
        "cards": suggestion_cards,
        "follow_up_questions": [],
        "answer_korean": answer_korean,
        "suggestion_cards": suggestion_cards,
    }
