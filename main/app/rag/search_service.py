"""RAG 검색 오케스트레이션 (API 프로세스 내 동기 DB + 선택적 원격 임베딩).

흐름 요약:
1. ``session_id`` 가 있으면 Async DB에서 ``ConversationMemory`` 적재·히스토리 여부 계산
2. ``execute_retrieval_pipeline`` — 의도/검색축 분류(선택적 OpenAI) → 휴리스틱 다중 쿼리 계획 → pgvector 검색 → RRF·컷오프
3. 세션 모드에서는 **분류·검색이 끝난 뒤** ``MessageService.save_user_message`` 로 intent·``retrieval_topic``·follow-up 메타 저장
4. 답변: 템플릿 또는 OpenAI (``answer_mode``)

검색 부하·의도 OpenAI 여부는 ``get_settings()`` 및 ``run_vector_search(..., intent_use_openai=..., retrieval_*=...)`` 로 조정.

자세한 구조는 저장소 루트 ``docs/CHATBOT_ARCHITECTURE.md`` 참고.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from functools import partial
from typing import Any

from openai import AsyncOpenAI, OpenAI

from app.core.config import get_settings
from app.db.conversation_sync_store import (
    sync_load_memory_for_session,
    sync_save_assistant_message,
    sync_save_user_message,
)
from app.rag.pipeline import (
    build_korean_search_answer,
    engine as _sync_search_db_engine,
    format_search_results_for_llm_context,
)
from app.rag.retrieval.memory import ConversationMemory
from app.rag.retrieval import RetrievalConfig, execute_retrieval_pipeline
from app.rag.suggestion_cards import build_retrieval_suggestion_cards
from app.rag.faq import FaqSearchService

logger = logging.getLogger(__name__)
_DEFAULT_MEMORY = ConversationMemory(max_turns=5)
_ANSWER_OPENAI_MODEL = "gpt-5-mini"

# FAQ 전용 모드(kimeschat visitor/exhibitor): DB 매칭 실패 시 LLM·RAG로 넘기지 않고 이 안내만 반환
_FAQ_ONLY_NO_MATCH_KO = (
    "등록된 FAQ 안내에서 질문과 정확히 맞는 응답을 찾지 못했습니다.\n"
    "상단 카테고리 버튼으로 항목을 선택하거나, 더 구체적인 단어(키워드)를 넣어 다시 검색해 주세요.\n\n"
    "예) 출입증 수령 위치, 주차 요금, 사전등록 방법, 셔틀 운행 시간"
)

"""
FAQ 검색은 `app.rag.faq` 로 분리됐다.

중요 정책:
- FAQ 검색에서는 pgvector/embedding/semantic retrieval 금지
- FAQ 모드(faq_only)는 DB 미매칭 시에도 절대 LLM/RAG로 fallback 하지 않는다.
"""

_EXTERNAL_ID_MARKER_RE = re.compile(r"\(\s*external_id\s*:\s*([^)]+?)\s*\)", re.IGNORECASE)


def _extract_external_id_marker(query: str) -> tuple[str, str | None]:
    """질문 문자열에서 (external_id:...) 마커를 추출한다."""

    q = str(query or "")
    m = _EXTERNAL_ID_MARKER_RE.search(q)
    if not m:
        return q.strip(), None
    ext = (m.group(1) or "").strip()
    clean = _EXTERNAL_ID_MARKER_RE.sub("", q).strip()
    clean = re.sub(r"\s{2,}", " ", clean).strip()
    return clean, (ext or None)


def _direct_lookup_results_by_external_id_sync(*, engine, external_id: str) -> list[dict[str, Any]]:
    """external_id로 업체/제품을 직접 조회해 profile chunk 결과를 만든다."""

    from sqlalchemy import text

    ext = (external_id or "").strip()
    if not ext:
        return []

    exhib_sql = text(
        """
        SELECT external_id,
               company_name_kor, company_name_eng, homepage,
               exhibition_category_label, booth_number, exhibit_hall_label_kor,
               country_label_kor, company_address_kor,
               exhibition_manager_tel,
               company_description_kor
          FROM kprint_exhibitor
         WHERE external_id = :ext
         LIMIT 1
        """
    )
    item_sql = text(
        """
        SELECT external_id,
               product_name_kor, product_name_eng,
               manufacturer_kor, model_name,
               item_main_category_label_kor, item_sub_category_label_kor,
               exhibition_category_label, exhibit_hall_label_kor,
               company_name_kor,
               product_description_kor
          FROM kprint_exhibit_item
         WHERE external_id = :ext
         LIMIT 1
        """
    )

    def _kv(**kwargs: Any) -> str:
        lines: list[str] = []
        for k, v in kwargs.items():
            if v is None:
                continue
            s = str(v).strip()
            if not s:
                continue
            lines.append(f"{k}: {s}")
        return "\n".join(lines).strip()

    out: list[dict[str, Any]] = []
    with engine.connect() as conn:
        r1 = conn.execute(exhib_sql, {"ext": ext}).mappings().first()
        if r1:
            content = _kv(
                company_name_kor=r1.get("company_name_kor"),
                company_name_eng=r1.get("company_name_eng"),
                booth_number=r1.get("booth_number"),
                exhibit_hall_label_kor=r1.get("exhibit_hall_label_kor"),
                exhibition_category_label=r1.get("exhibition_category_label"),
                homepage=r1.get("homepage"),
                country_label_kor=r1.get("country_label_kor"),
                company_address_kor=r1.get("company_address_kor"),
                exhibition_manager_tel=r1.get("exhibition_manager_tel"),
                company_description_kor=r1.get("company_description_kor"),
            )
            out.append(
                {
                    "table_name": "kprint_exhibitor",
                    "external_id": ext,
                    "lang": "ko",
                    "model": "direct",
                    "chunk_typ": "profile",
                    "source_field": "direct_lookup",
                    "chunk_index": 0,
                    "content": content,
                    "distance": 0.0,
                    "score": 1.0,
                }
            )
        try:
            r2 = conn.execute(item_sql, {"ext": ext}).mappings().first()
            if r2:
                content = _kv(
                    product_name_kor=r2.get("product_name_kor"),
                    product_name_eng=r2.get("product_name_eng"),
                    manufacturer_kor=r2.get("manufacturer_kor"),
                    model_name=r2.get("model_name"),
                    item_main_category_label_kor=r2.get("item_main_category_label_kor"),
                    item_sub_category_label_kor=r2.get("item_sub_category_label_kor"),
                    exhibition_category_label=r2.get("exhibition_category_label"),
                    exhibit_hall_label_kor=r2.get("exhibit_hall_label_kor"),
                    company_name_kor=r2.get("company_name_kor"),
                    product_description_kor=r2.get("product_description_kor"),
                )
                out.append(
                    {
                        "table_name": "kprint_exhibit_item",
                        "external_id": ext,
                        "lang": "ko",
                        "model": "direct",
                        "chunk_typ": "profile",
                        "source_field": "direct_lookup",
                        "chunk_index": 0,
                        "content": content,
                        "distance": 0.0,
                        "score": 1.0,
                    }
                )
        except Exception as e:  # noqa: BLE001
            # item 테이블 스키마/데이터가 없는 경우에도 exhibitor direct lookup은 계속 가능해야 함
            logger.warning("[direct_lookup] exhibit_item lookup skipped ext=%s err=%s", ext, e)
    return out


def _rag_followups_from_context(*, query: str, intent: str, cards: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """일반 질문도 FAQ와 같은 follow-up 버튼 UI를 붙이기 위한 기본 followups."""
    title = ""
    if isinstance(cards, list) and cards:
        title = str((cards[0] or {}).get("title") or "").strip()
    subj = title or (query or "").strip()
    if intent in {"company"}:
        return [
            {"label": "부스 위치", "ask": f"{subj} 부스 위치 알려줘"},
            {"label": "연락처", "ask": f"{subj} 담당자 연락처/이메일 알려줘"},
            {"label": "대표 제품", "ask": f"{subj} 대표 제품(전시품) 3개 알려줘"},
            {"label": "상세 소개", "ask": f"{subj} 회사 소개를 더 자세히 알려줘"},
        ]
    if intent in {"product"}:
        return [
            {"label": "제조사/업체", "ask": f"{subj} 제조사/참가업체가 어디야?"},
            {"label": "스펙", "ask": f"{subj} 주요 스펙/특징 정리해줘"},
            {"label": "가격/구매", "ask": f"{subj} 가격대나 구매/문의 방법 알려줘"},
            {"label": "비교", "ask": f"{subj} 비슷한 제품 3개와 차이점 비교해줘"},
        ]
    # fallback
    return [
        {"label": "핵심 요약", "ask": f"{subj} 핵심만 요약해줘"},
        {"label": "관련 항목", "ask": f"{subj} 관련 업체/제품 더 찾아줘"},
        {"label": "조건 추가", "ask": f"{subj} 조건을 넣어서 다시 찾아줘"},
    ]

def _sync_chat_completions_text(
    *,
    api_key: str,
    base_url: str | None,
    model: str,
    messages: list[dict[str, Any]],
) -> str:
    """동기 OpenAI 클라이언트(Chat Completions). AsyncOpenAI 는 같은 이벤트 루프에서 SQLAlchemy 와 섞일 때 MissingGreenlet 이 날 수 있어 스레드에서 이 경로만 쓴다."""

    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)
    resp = client.chat.completions.create(model=model, messages=messages)
    return ((resp.choices[0].message.content) or "").strip() or "LLM이 빈 답변을 반환했습니다."


def _answer_base_url_norm(base: str) -> str | None:
    b = (base or "").strip()
    return b or None


def _answer_style_hints(
    *,
    intent: str,
    retrieval_topic: str | None,
    is_dialog_followup: bool,
) -> str:
    """시스템 프롬프트에만 쓰는 짧은 톤 힌트 (사용자 메시지에는 넣지 않음)."""
    rt = (retrieval_topic or "all").strip().lower()
    parts: list[str] = []
    if is_dialog_followup:
        parts.append("직전 대화 맥락을 이어 받은 질문일 수 있으니, 생략된 주어를 자연스럽게 보완해도 된다.")
    if intent == "product" or rt == "product":
        parts.append("전시품·제품 정보 위주로 정리한다.")
    elif intent == "company" or rt == "company":
        parts.append("참가업체(회사) 정보 위주로 정리한다.")
    else:
        parts.append("회사와 제품 정보를 균형 있게 다룬다.")
    return " ".join(parts)


async def _generate_korean_answer_with_openai(
    *,
    query: str,
    results: list[dict[str, Any]],
    api_key: str,
    base_url: str,
    model: str,
    intent: str,
    language: str,
    retrieval_topic: str | None,
    is_dialog_followup: bool,
) -> str:
    if not results:
        return "검색 결과가 없어 답변을 생성할 수 없습니다."

    context_text = format_search_results_for_llm_context(results)
    language_rule = "한국어로 답변" if language == "ko" else "기본은 한국어, 필요 시 핵심 영문 키워드 병기"
    style = _answer_style_hints(
        intent=intent,
        retrieval_topic=retrieval_topic,
        is_dialog_followup=is_dialog_followup,
    )
    logger.info(
        "[answer] openai_generate(sync via thread) start query_len=%d results=%d context_chars=%d",
        len(query or ""),
        len(results),
        len(context_text),
    )
    messages = [
        {
            "role": "system",
            "content": (
                "너는 전시회 참가기업·전시품 안내를 하는 챗봇이다. "
                f"{language_rule}. "
                "아래에 주어진 '프로필'과 '추가 근거'만 사실의 근거로 사용한다. 없는 정보는 지어내지 말고 부족하다고 말한다. "
                f"{style} "
                "답변 형식: 긴 산문 대신 **정리형**으로 쓴다. "
                "예) 첫 줄에 한 줄 요약, 다음은 '·' 불릿으로 핵심만, 필요하면 짧은 소제목(한글) 뒤에 불릿. "
                "문단 사이에는 반드시 빈 줄(\\n\\n)을 넣어 가독성을 높인다. "
                "의도 분류·검색 점수·내부 메타데이터 이름을 사용자에게 노출하지 않는다. "
                "목록에 있는 업체/제품 이름은 아래 카드로 따로 보여 줄 예정이므로, 본문에서는 이름만 언급하고 긴 표 형태 나열은 피한다."
            ),
        },
        {
            "role": "user",
            "content": (
                f"사용자 질문:\n{query}\n\n"
                f"참고 자료 (검색 DB에서 가져온 내용):\n{context_text}\n\n"
                "위 자료만 바탕으로 질문에 답해 줘. "
                "불릿·소제목·빈 줄을 써서 스크롤 없이도 구조가 보이게 정리해 줘."
            ),
        },
    ]
    out = await asyncio.to_thread(
        partial(
            _sync_chat_completions_text,
            api_key=api_key,
            base_url=_answer_base_url_norm(base_url),
            model=model,
            messages=messages,
        )
    )
    logger.info("[answer] openai_generate done answer_chars=%d", len(out))
    return out


async def _generate_general_answer_with_openai(
    *,
    query: str,
    api_key: str,
    base_url: str,
    model: str,
    language: str,
) -> str:
    language_rule = "한국어로 자연스럽게 답변" if language == "ko" else "기본은 한국어, 필요 시 영어 병기"
    messages = [
        {
            "role": "system",
            "content": (
                "너는 사용자 입력에 친절하게 반응하는 도우미다. "
                f"{language_rule}. "
                "짧게, **정리형**으로: 필요하면 첫 줄 요약 후 '·' 불릿. 문단 사이에는 빈 줄을 넣는다."
            ),
        },
        {
            "role": "user",
            "content": f"사용자 입력: {query}\n이 메시지 의도에 맞게 간단히 응답해줘.",
        },
    ]
    return await asyncio.to_thread(
        partial(
            _sync_chat_completions_text,
            api_key=api_key,
            base_url=_answer_base_url_norm(base_url),
            model=model,
            messages=messages,
        )
    )


def _clamp01(x: float) -> float:
    return max(0.05, min(0.95, float(x)))


def _clamp01(x: float) -> float:
    return max(0.05, min(0.95, float(x)))


async def run_vector_search(
    *,
    query: str,
    model_id: str,
    device: str | None,
    top_k: int,
    chunk_type: str,
    answer_mode: str,
    openai_model: str,
    openai_api_key: str,
    openai_base_url: str,
    embedding_remote_base_url: str | None,
    memory: ConversationMemory | None = None,
    session_id: str | None = None,
    faq_only: bool = False,
    faq_user: str | None = None,
    intent_use_openai: bool | None = None,
    retrieval_min_queries: int | None = None,
    retrieval_max_queries: int | None = None,
    retrieval_score_cutoff: float | None = None,
    retrieval_evidence_ratio: float | None = None,
    retrieval_rrf_k: int | None = None,
    retrieval_context_limit: int | None = None,
    retrieval_top_k_per_query: int | None = None,
) -> dict[str, Any]:
    if chunk_type not in {"all", "profile", "evidence"}:
        raise ValueError("chunk_type must be one of: all, profile, evidence")
    if answer_mode not in {"template", "openai"}:
        raise ValueError("answer_mode must be one of: template, openai")

    # carousel '자세히 보기'에서 전달되는 (external_id:...) 마커 처리:
    # - 화면에는 노출되지 않지만 서버 요청에는 포함된다.
    # - 이 마커가 있으면 벡터 검색 대신 DB direct lookup으로 정확도를 보장한다.
    clean_query, ext_marker = _extract_external_id_marker(query)
    query = clean_query or query

    openai_client: AsyncOpenAI | None = None
    key = (openai_api_key or "").strip()
    if key:
        client_kwargs: dict[str, Any] = {"api_key": key}
        if (openai_base_url or "").strip():
            client_kwargs["base_url"] = (openai_base_url or "").strip()
        openai_client = AsyncOpenAI(**client_kwargs)

    # --- 단계 0: 세션이 있으면 DB에서 메모리만 적재하고, 사용자 메시지 저장은 파이프라인 이후로 미룬다 ---
    # (이유: intent·retrieval_topic·is_dialog_followup은 classify 이후에야 확정되므로 한 번에 저장한다.)
    db_memory = memory
    has_history = False
    session_uuid_for_save: uuid.UUID | None = None
    fu_state: tuple[bool, float, dict] | None = None
    logger.info(
        "[search] start query_preview=%s top_k=%s chunk_type=%s answer_mode=%s session=%s",
        (query or "")[:120],
        top_k,
        chunk_type,
        answer_mode,
        (session_id or "")[:32] or "-",
    )

    # --- FAQ 게이트 ---
    # 운영 UI에서 "FAQ 모드"일 때만 FAQ 검색 엔진을 탄다.
    # (RAG 모드에서는 FAQ 안내/차단 메시지가 절대 나오면 안 됨)
    enable_faq_gate = bool(faq_only or (faq_user or "").strip())
    if enable_faq_gate:
        trace_id = f"faq-{uuid.uuid4().hex[:10]}"
        faq_service = FaqSearchService(engine=_sync_search_db_engine)
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
        # FAQ 모드(게이트 진입)인데 매칭 실패: 절대 RAG/LLM로 넘기지 않는다.
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

    # --- RAG direct lookup (external_id가 있는 경우) ---
    if ext_marker:
        direct_results = await asyncio.to_thread(
            _direct_lookup_results_by_external_id_sync,
            engine=_sync_search_db_engine,
            external_id=ext_marker,
        )
        if direct_results:
            answer_korean = build_korean_search_answer(query, direct_results)
            suggestion_cards = await build_retrieval_suggestion_cards(direct_results)
            return {
                "query": query,
                "top_k": max(1, int(top_k)),
                "lang": "ko",
                "chunk_type": chunk_type,
                "count": len(direct_results),
                "retrieval": {
                    "intent": "direct_lookup",
                    "retrieval_topic": None,
                    "is_dialog_followup": False,
                    "language": "ko",
                    "planned_queries": [],
                    "llm_context": "",
                    "rrf_candidates": len(direct_results),
                    "step_logs": [],
                    "response_mode": "direct_lookup",
                    "embedding_remote_base_url": None,
                    "openai_usage_summary": {"direct_lookup": True},
                    "tuning_applied": {},
                },
                "answer": answer_korean,
                "answer_meta": {"mode": "direct_external_id"},
                "results": direct_results,
                "cards": suggestion_cards,
                "follow_up_questions": _rag_followups_from_context(query=query, intent="company", cards=suggestion_cards),
                "answer_korean": answer_korean,
                "suggestion_cards": suggestion_cards,
            }

    if session_id:
        from app.services import is_followup_v2

        # AsyncSession 피해서 동기 psycopg 엔진으로만 처리 (임베딩 검색과 같은 DB).
        db_memory, session_uuid_for_save = await asyncio.to_thread(
            partial(
                sync_load_memory_for_session,
                engine=_sync_search_db_engine,
                browser_session_id=session_id,
                limit=5,
            )
        )
        has_history = len(db_memory.get_recent()) > 0
        hist_texts = [m.get("message", "") for m in db_memory.get_recent()][-5:]
        is_fu, fu_conf, fu_meta = is_followup_v2(current=query, history=hist_texts)
        fu_state = (is_fu, fu_conf, fu_meta)

    st = get_settings()
    i_openai = st.retrieval_intent_use_openai if intent_use_openai is None else intent_use_openai
    min_q = st.retrieval_min_queries if retrieval_min_queries is None else int(retrieval_min_queries)
    max_q = st.retrieval_max_queries if retrieval_max_queries is None else int(retrieval_max_queries)
    min_q = max(1, min_q)
    max_q = max(min_q, max_q)
    sc = float(st.retrieval_score_cutoff if retrieval_score_cutoff is None else retrieval_score_cutoff)
    er = _clamp01(float(st.retrieval_evidence_ratio if retrieval_evidence_ratio is None else retrieval_evidence_ratio))
    rk = max(1, int(st.retrieval_rrf_k if retrieval_rrf_k is None else retrieval_rrf_k))
    cl = max(1, int(st.retrieval_context_limit if retrieval_context_limit is None else retrieval_context_limit))
    tkpq_raw = st.retrieval_top_k_per_query if retrieval_top_k_per_query is None else retrieval_top_k_per_query
    tkpq = max(6, int(top_k)) if tkpq_raw is None else max(1, int(tkpq_raw))

    tuning_meta = {
        "intent_use_openai": i_openai,
        "min_queries": min_q,
        "max_queries": max_q,
        "score_cutoff": sc,
        "evidence_ratio": er,
        "rrf_k": rk,
        "context_limit": cl,
        "top_k_per_query": tkpq,
        "final_top_k": max(1, int(top_k)),
    }
    logger.info("[search] retrieval_pipeline ... tuning=%s", tuning_meta)

    st = get_settings()
    i_openai = st.retrieval_intent_use_openai if intent_use_openai is None else intent_use_openai
    min_q = st.retrieval_min_queries if retrieval_min_queries is None else int(retrieval_min_queries)
    max_q = st.retrieval_max_queries if retrieval_max_queries is None else int(retrieval_max_queries)
    min_q = max(1, min_q)
    max_q = max(min_q, max_q)
    sc = float(st.retrieval_score_cutoff if retrieval_score_cutoff is None else retrieval_score_cutoff)
    er = _clamp01(float(st.retrieval_evidence_ratio if retrieval_evidence_ratio is None else retrieval_evidence_ratio))
    rk = max(1, int(st.retrieval_rrf_k if retrieval_rrf_k is None else retrieval_rrf_k))
    cl = max(1, int(st.retrieval_context_limit if retrieval_context_limit is None else retrieval_context_limit))
    tkpq_raw = st.retrieval_top_k_per_query if retrieval_top_k_per_query is None else retrieval_top_k_per_query
    tkpq = max(6, int(top_k)) if tkpq_raw is None else max(1, int(tkpq_raw))

    tuning_meta = {
        "intent_use_openai": i_openai,
        "min_queries": min_q,
        "max_queries": max_q,
        "score_cutoff": sc,
        "evidence_ratio": er,
        "rrf_k": rk,
        "context_limit": cl,
        "top_k_per_query": tkpq,
        "final_top_k": max(1, int(top_k)),
    }
    logger.info("[search] retrieval_pipeline ... tuning=%s", tuning_meta)

    retrieval_payload = await execute_retrieval_pipeline(
        query,
        config=RetrievalConfig(
            model_id=model_id,
            device=device or None,
            top_k_per_query=tkpq,
            final_top_k=max(1, int(top_k)),
            score_cutoff=sc,
            evidence_ratio=er,
            min_queries=min_q,
            max_queries=max_q,
            rrf_k=rk,
            context_limit=cl,
        ),
        openai_client=openai_client,
        intent_model=openai_model,
        intent_use_openai=i_openai,
        embedding_remote_base_url=embedding_remote_base_url,
        has_history=has_history,
        memory=db_memory or _DEFAULT_MEMORY,
    )

    results = retrieval_payload["final_results"]
    response_mode = retrieval_payload.get("response_mode", "retrieval")
    logger.info(
        "[retrieval] done mode=%s intent=%s topic=%s followup=%s language=%s queries=%d results=%d",
        response_mode,
        retrieval_payload["intent"],
        retrieval_payload.get("retrieval_topic"),
        retrieval_payload.get("is_dialog_followup"),
        retrieval_payload["language"],
        len(retrieval_payload["planned_queries"]),
        len(results),
    )

    if response_mode == "intent_heuristic":
        answer_korean = retrieval_payload.get("heuristic_answer") or "요청 의도에 맞춘 안내 응답입니다."
        answer_meta: dict[str, Any] = {"mode": "intent_heuristic"}
    elif response_mode == "general_chat":
        answer_korean = retrieval_payload.get("heuristic_answer") or "일반 대화로 이해했습니다."
        answer_meta = {"mode": "general_chat_template"}
    else:
        answer_korean = build_korean_search_answer(query, results)
        answer_meta = {"mode": "template"}

    if response_mode == "retrieval" and answer_mode == "openai":
        if not key:
            logger.warning("[search] openai requested but OPENAI_API_KEY missing → template")
            answer_meta = {"mode": "template_fallback", "error": "OPENAI_API_KEY is not set", "requested_mode": "openai"}
        else:
            try:
                answer_korean = await _generate_korean_answer_with_openai(
                    query=query,
                    results=results,
                    api_key=key,
                    base_url=(openai_base_url or "").strip(),
                    model=_ANSWER_OPENAI_MODEL,
                    intent=retrieval_payload["intent"],
                    language=retrieval_payload["language"],
                    retrieval_topic=retrieval_payload.get("retrieval_topic"),
                    is_dialog_followup=bool(retrieval_payload.get("is_dialog_followup", False)),
                )
                answer_meta = {"mode": "openai", "model": _ANSWER_OPENAI_MODEL}
            except Exception as e:
                logger.exception("[search] openai answer generation failed: %s", e)
                answer_korean = build_korean_search_answer(query, results)
                answer_meta = {"mode": "template_fallback", "error": str(e), "requested_mode": "openai"}
    elif response_mode == "general_chat":
        # general intent는 answer_mode와 무관하게 LLM 응답을 우선 시도한다.
        if not key:
            answer_meta = {
                "mode": "general_chat_template_fallback",
                "error": "OPENAI_API_KEY is not set",
                "requested_mode": "openai_for_general",
            }
        else:
            try:
                logger.info("[answer] general_chat openai …")
                answer_korean = await _generate_general_answer_with_openai(
                    query=query,
                    api_key=key,
                    base_url=(openai_base_url or "").strip(),
                    model=_ANSWER_OPENAI_MODEL,
                    language=retrieval_payload["language"],
                )
                answer_meta = {"mode": "general_chat_openai", "model": _ANSWER_OPENAI_MODEL}
                logger.info("[answer] general_chat openai done chars=%d", len(answer_korean or ""))
            except Exception as e:
                logger.exception("[answer] general_chat openai failed: %s", e)
                answer_meta = {
                    "mode": "general_chat_template_fallback",
                    "error": str(e),
                    "requested_mode": "openai_for_general",
                }

    openai_usage = dict(retrieval_payload.get("openai_usage_summary") or {})
    openai_usage["answer_generation_used_openai"] = answer_meta.get("mode") in (
        "openai",
        "general_chat_openai",
    )
    openai_usage["answer_generation_mode"] = answer_meta.get("mode")
    if answer_meta.get("model"):
        openai_usage["answer_generation_model"] = answer_meta.get("model")
    answer_step_log = {
        "step": 99,
        "title": "최종 답변 생성",
        "detail": (
            f"answer_mode={answer_mode}, response_mode={response_mode}, "
            f"applied_mode={answer_meta.get('mode', 'unknown')}"
        ),
        "data": {
            "requested_answer_mode": answer_mode,
            "response_mode": response_mode,
            "answer_meta": answer_meta,
            "openai_usage_summary": openai_usage,
        },
    }
    step_logs = list(retrieval_payload.get("step_logs", []))
    step_logs.append(answer_step_log)

    suggestion_cards: list[dict[str, Any]] = []
    followups_rag: list[dict[str, Any]] = []
    if response_mode == "retrieval" and results:
        try:
            suggestion_cards = await build_retrieval_suggestion_cards(results)
        except Exception as e:
            logger.warning("[search] suggestion_cards skipped: %s", e)
        # 카드 유무와 intent에 따라 후속질문 버튼을 구성 (카테고리 질문 UI와 동일한 형태로 노출)
        followups_rag = _rag_followups_from_context(
            query=query,
            intent=str(retrieval_payload.get("intent") or ""),
            cards=suggestion_cards,
        )
    else:
        followups_rag = _rag_followups_from_context(
            query=query,
            intent=str(retrieval_payload.get("intent") or ""),
            cards=suggestion_cards,
        )

    if memory is None:
        _DEFAULT_MEMORY.add("assistant", answer_korean)
    else:
        memory.add("assistant", answer_korean)

    # 세션 DB 저장: 답변·제안 카드까지 성공한 뒤에 수행 (중간 실패 시에도 OpenAI 답변은 반환되게).
    if session_uuid_for_save is not None:
        pip_intent = str(retrieval_payload["intent"])
        pip_fu = bool(retrieval_payload.get("is_dialog_followup", False))
        pip_topic = retrieval_payload.get("retrieval_topic")
        if pip_topic is None:
            pip_topic = "all"
        pip_topic = str(pip_topic).strip().lower()
        if fu_state is not None:
            _heu_fu, fu_conf, _ = fu_state
            conf = float(max(fu_conf, 0.55 if pip_fu else 0.35))
        else:
            conf = 0.85

        try:
            await asyncio.to_thread(
                partial(
                    sync_save_user_message,
                    engine=_sync_search_db_engine,
                    session_pk=session_uuid_for_save,
                    content=query,
                    intent=pip_intent,
                    is_followup=pip_fu,
                    confidence=conf,
                    retrieval_topic=pip_topic,
                )
            )
        except Exception:
            logger.exception("[search] sync_save_user_message failed (answer still returned)")

        try:
            await asyncio.to_thread(
                partial(
                    sync_save_assistant_message,
                    engine=_sync_search_db_engine,
                    session_pk=session_uuid_for_save,
                    content=answer_korean,
                )
            )
        except Exception:
            logger.exception("[search] sync_save_assistant_message failed (answer still returned)")

    return {
        "query": query,
        "top_k": max(1, int(top_k)),
        "lang": retrieval_payload["language"],
        "chunk_type": chunk_type,
        "count": len(results),
        "retrieval": {
            "intent": retrieval_payload["intent"],
            "retrieval_topic": retrieval_payload.get("retrieval_topic"),
            "is_dialog_followup": retrieval_payload.get("is_dialog_followup"),
            "language": retrieval_payload["language"],
            "planned_queries": retrieval_payload["planned_queries"],
            "llm_context": retrieval_payload["llm_context"],
            "rrf_candidates": len(retrieval_payload["fused_results"]),
            "step_logs": step_logs,
            "response_mode": response_mode,
            "embedding_remote_base_url": (embedding_remote_base_url or "").strip() or None,
            "openai_usage_summary": openai_usage,
            "tuning_applied": tuning_meta,
        },
        # UI 호환
        "answer": answer_korean,
        "answer_meta": answer_meta,
        "results": results,
        "cards": suggestion_cards,
        "follow_up_questions": followups_rag,
        # worker 호환
        "answer_korean": answer_korean,
        "suggestion_cards": suggestion_cards,
    }
