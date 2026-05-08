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
    infer_answer_focus,
    sanitize_rag_results_for_user,
)
from app.rag.retrieval.search import apply_cutoff_and_build_context
from app.rag.retrieval.memory import ConversationMemory
from app.rag.retrieval import RetrievalConfig, execute_retrieval_pipeline
from app.rag.retrieval.intent import detect_language
from app.rag.suggestion_cards import build_retrieval_suggestion_cards
from app.rag.faq import FaqSearchService
from app.rag.entity_enrichment import enrich_results_with_entity_detail_sync, merged_entity_context, infer_entity_type_from_table

logger = logging.getLogger(__name__)
_DEFAULT_MEMORY = ConversationMemory(max_turns=5)
_ANSWER_OPENAI_MODEL = "gpt-5-mini"
# entity_detail.description 상한(비정상적으로 긴 필드 방지, 사실상 전문 노출)
_ENTITY_DESC_FULL_MAX = 50000


def _entity_description_full(raw: Any) -> str | None:
    """DB 소개 필드를 전문(상한 내)으로 정규화한다."""
    s = str(raw or "").strip()
    if not s:
        return None
    if len(s) > _ENTITY_DESC_FULL_MAX:
        s = s[:_ENTITY_DESC_FULL_MAX].rstrip() + "…"
    return s

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
# 카드/후행 UI가 붙이는 한국어 스캐폴딩 때문에 detect_language 가 en→ko 로 뒤집히는 것을 완화
_DL_LANG_STRIP_KO_TAIL_RE = re.compile(
    r"[,.]?\s*("
    r"에\s*대한\s*정보를\s*알려\s*줘|"
    r"에\s*대해\s*알려\s*줘|"
    r"에\s*대해\s*자세히\s*알려\s*줘|"
    r"에\s*대한\s*자세한\s*정보를\s*알려\s*줘|"
    r"자세히\s*알려\s*줘|"
    r"자세히\s*보기"
    r")\s*\Z",
    re.IGNORECASE,
)


def _norm_payload_language(raw: Any) -> str | None:
    s = str(raw or "").strip().lower()
    if s in {"en", "english"}:
        return "en"
    if s in {"ko", "korean", "kr"}:
        return "ko"
    return None


def _text_for_answer_language_detection(query: str) -> str:
    """카드 JSON/후행 한국어 문구를 제외하고 사용자·주제 언어를 판별할 때 사용."""

    t = str(query or "").strip()
    t = _DL_LANG_STRIP_KO_TAIL_RE.sub("", t).strip()
    return t


def _resolve_answer_language(query: str, payload_lang: str | None) -> str:
    """direct lookup 등에서 enrichment·답변 로케일. payload.language 가 있으면 최우선."""

    pl = _norm_payload_language(payload_lang)
    if pl in {"en", "ko"}:
        return pl
    return detect_language(_text_for_answer_language_detection(query))


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


def _extract_entity_payload(query: str) -> tuple[str, str | None, str | None, str | None]:
    """카드 클릭에서 보내는 JSON payload를 지원한다.

    입력 예:
    {"query":"ABC에 대한 정보를 알려줘","entity_type":"company","external_id":"...","language":"en"}
    """

    q = str(query or "").strip()
    if not (q.startswith("{") and q.endswith("}")):
        return q, None, None, None
    try:
        import json

        obj = json.loads(q)
        if not isinstance(obj, dict):
            return q, None, None, None
        clean = str(obj.get("query") or "").strip() or q
        ext = str(obj.get("external_id") or "").strip() or None
        typ = str(obj.get("entity_type") or "").strip().lower() or None
        if typ not in {None, "company", "product"}:
            typ = None
        lang = _norm_payload_language(obj.get("language") or obj.get("lang"))
        return clean, ext, typ, lang
    except Exception:
        return q, None, None, None


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

    def _kv_ko(**kwargs: Any) -> str:
        # 사용자/LLM에 DB column 명이 노출되지 않도록 "한글 라벨"로만 구성한다.
        lines: list[str] = []
        for k, v in kwargs.items():
            s = str(v or "").strip()
            if not s:
                continue
            lines.append(f"{k}: {s}")
        return "\n".join(lines).strip()

    out: list[dict[str, Any]] = []
    with engine.connect() as conn:
        r1 = conn.execute(exhib_sql, {"ext": ext}).mappings().first()
        if r1:
            cdesc_full = _entity_description_full(r1.get("company_description_kor"))
            entity_detail = {
                "entity_type": "company",
                "external_id": ext,
                "company_name": (r1.get("company_name_kor") or r1.get("company_name_eng") or "").strip() or None,
                "one_liner": ((cdesc_full or "")[:120] or None),
                "description": cdesc_full,
                "booth": (str(r1.get("booth_number") or "").strip() or None),
                "hall": (str(r1.get("exhibit_hall_label_kor") or "").strip() or None),
                "category": (str(r1.get("exhibition_category_label") or "").strip() or None),
                "contact": (str(r1.get("exhibition_manager_tel") or "").strip() or None),
                "website": (str(r1.get("homepage") or "").strip() or None),
            }
            content = _kv_ko(
                회사명=entity_detail.get("company_name"),
                부스=entity_detail.get("booth"),
                홀=entity_detail.get("hall"),
                분야=entity_detail.get("category"),
                연락처=entity_detail.get("contact"),
                웹사이트=entity_detail.get("website"),
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
                    "entity_type": "company",
                    "entity_detail": entity_detail,
                    "distance": 0.0,
                    "score": 1.0,
                }
            )
        try:
            r2 = conn.execute(item_sql, {"ext": ext}).mappings().first()
            if r2:
                pdesc_full = _entity_description_full(r2.get("product_description_kor"))
                entity_detail = {
                    "entity_type": "product",
                    "external_id": ext,
                    "product_name": (r2.get("product_name_kor") or r2.get("product_name_eng") or "").strip() or None,
                    "one_liner": ((pdesc_full or "")[:120] or None),
                    "description": pdesc_full,
                    "manufacturer": (str(r2.get("manufacturer_kor") or "").strip() or None),
                    "model_name": (str(r2.get("model_name") or "").strip() or None),
                    "category": (str(r2.get("item_main_category_label_kor") or r2.get("exhibition_category_label") or "").strip() or None),
                    "location": (str(r2.get("exhibit_hall_label_kor") or "").strip() or None),
                }
                content = _kv_ko(
                    제품명=entity_detail.get("product_name"),
                    제조사=entity_detail.get("manufacturer"),
                    모델=entity_detail.get("model_name"),
                    카테고리=entity_detail.get("category"),
                    전시위치=entity_detail.get("location"),
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
                        "entity_type": "product",
                        "entity_detail": entity_detail,
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
    max_output_tokens: int = 16384,
) -> str:
    """동기 OpenAI 클라이언트(Chat Completions). AsyncOpenAI 는 같은 이벤트 루프에서 SQLAlchemy 와 섞일 때 MissingGreenlet 이 날 수 있어 스레드에서 이 경로만 쓴다."""

    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=max_output_tokens,
        )
    except Exception:
        resp = client.chat.completions.create(model=model, messages=messages, max_tokens=min(max_output_tokens, 8192))
    choice = resp.choices[0]
    finish = getattr(choice, "finish_reason", None)
    if finish == "length":
        logger.warning(
            "[answer] OpenAI finish_reason=length model=%s — 출력 토큰 상한에 도달했을 수 있어 답변이 잘릴 수 있음",
            model,
        )
    return ((choice.message.content) or "").strip() or "LLM이 빈 답변을 반환했습니다."


def _answer_base_url_norm(base: str) -> str | None:
    b = (base or "").strip()
    return b or None


def _answer_style_hints(
    *,
    intent: str,
    retrieval_topic: str | None,
    is_dialog_followup: bool,
    answer_focus: str | None = None,
    language: str = "ko",
) -> str:
    """시스템 프롬프트에만 쓰는 짧은 톤 힌트 (사용자 메시지에는 넣지 않음)."""
    rt = (retrieval_topic or "all").strip().lower()
    af = (answer_focus or "").strip().lower()
    lang = (language or "ko").strip().lower()
    parts: list[str] = []
    if is_dialog_followup:
        if lang == "en":
            parts.append("The user may omit the subject; you may infer it from the previous turn naturally.")
        else:
            parts.append("직전 대화 맥락을 이어 받은 질문일 수 있으니, 생략된 주어를 자연스럽게 보완해도 된다.")
    if af == "product" or intent == "product" or rt == "product":
        parts.append("Focus on product/exhibit item details." if lang == "en" else "전시품·제품 정보 위주로 정리한다.")
    elif af == "company" or intent == "company" or rt == "company":
        parts.append("Focus on exhibitor/company details." if lang == "en" else "참가업체(회사) 정보 위주로 정리한다.")
    else:
        if lang == "en":
            parts.append("Stick to one axis (company or product) as in the reference; do not mix sections.")
        else:
            parts.append("참고 자료에 포함된 축(업체 또는 제품)에 맞춰 한쪽으로만 정리한다.")
    return " ".join(parts)


def _llm_answer_format_instructions(*, focus: str, language: str = "ko") -> str:
    """OpenAI 답변용: 업체/제품 중 한 형식만 사용하도록 고정 (한국어/영어)."""

    lang = (language or "ko").strip().lower()
    if lang == "en":
        common = (
            "Forbidden: exposing UUIDs, internal IDs, DB column names, scores, raw JSON, or pgvector metadata. "
            "If the reference includes a full company or product description, reproduce the full text in your answer "
            "without arbitrary shortening. Omit whole bullet lines when a fact is missing (do not use '-' placeholders). "
            "Write like an on-site show assistant introducing exhibitors or products. "
            "Never explain search quality, ranking, 'insufficient detail', 'not enough information', metadata limits, DB state, "
            "or phrases like 'only entry', 'reference entry', 'Product 1/2 numbering', or why items were included or excluded. "
        )
        if (focus or "").strip().lower() == "product":
            return (
                common
                + "Use **product** information only. Do not output exhibitor/company-only sections.\n\n"
                + "[Product information]\n"
                + "Product name\n"
                + "[Product overview]\n"
                + "(full DB description)\n\n"
                + "· Manufacturer:\n"
                + "· Category:\n"
                + "· Show location:\n"
                + "· Contact:\n"
                + "· Website:\n"
            )
        return (
            common
            + "Use **exhibitor** information only. Do not output product-only sections.\n\n"
            + "[Exhibitor information]\n"
            + "Company name\n"
            + "[Company overview]\n"
            + "(full DB description)\n\n"
            + "· Location:\n"
            + "· Category:\n"
            + "· Contact:\n"
            + "· Website:\n"
            + "· Key products/services:\n"
            + "· Other notes:\n"
        )

    common = (
        "절대 금지: UUID/internal id/DB 컬럼명/점수/원시 JSON/pgvector 메타데이터 노출. "
        "참고 자료에 '업체 소개(전문)' 또는 '제품 소개(전문)'으로 주어진 description 텍스트는 "
        "임의로 축약·요약하지 말고 원문을 그대로 답변 본문에 빠짐없이 옮긴다. 빈 항목은 '-'로 채우지 말고 해당 줄을 통째로 생략한다. "
        "전시장 안내 데스크처럼 자연스럽게 업체·제품을 소개한다. 검색/rank 품질, 부족/불충분, 메타데이터, DB 상태, "
        "'reference/entry', '유일 항목' 같은 내부 설명 문구는 쓰지 않는다. "
    )
    if (focus or "").strip().lower() == "product":
        return (
            common
            + "이번 답변은 **제품** 정보만 작성한다. [업체 정보] 섹션·업체 전용 항목은 출력하지 않는다.\n\n"
            + "[제품 정보]\n"
            + "제품명\n"
            + "[제품 소개]\n"
            + "(DB description 전문)\n\n"
            + "· 제조사:\n"
            + "· 카테고리:\n"
            + "· 전시 위치:\n"
            + "· 문의:\n"
            + "· 웹사이트:\n"
        )
    return (
        common
        + "이번 답변은 **참가업체** 정보만 작성한다. [제품 정보] 섹션·제품 전용 항목은 출력하지 않는다.\n\n"
        + "[업체 정보]\n"
        + "회사명\n"
        + "[업체 소개]\n"
        + "(DB description 전문)\n\n"
        + "· 위치:\n"
        + "· 카테고리:\n"
        + "· 연락처:\n"
        + "· 웹사이트:\n"
        + "· 주요 제품/서비스:\n"
        + "· 기타 특징:\n"
    )


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
    lang = (language or "ko").strip().lower()
    if not results:
        return (
            "No search results; cannot generate an answer."
            if lang == "en"
            else "검색 결과가 없어 답변을 생성할 수 없습니다."
        )

    context_text = format_search_results_for_llm_context(
        results, intent=intent, retrieval_topic=retrieval_topic, language=language
    )
    focus = infer_answer_focus(intent=intent, retrieval_topic=retrieval_topic, results=results)
    if lang == "en":
        language_rule = "Answer in English. Keep database proper nouns as given."
        bot_role = (
            "You are a chatbot for trade-show exhibitors and exhibit products. "
            "Use only the summary and related excerpts below as factual sources. "
            "Do not invent missing facts; simply omit fields you do not have. "
            "Never discuss search internals, ranks, completeness, or why snippets were chosen."
        )
        user_tail = (
            "Answer using only the reference above. Use the **single** format specified. Hide internal metadata. "
            "Do not mention retrieval quality or missing coverage in user-facing wording."
        )
    else:
        language_rule = "한국어로 답변"
        bot_role = (
            "너는 전시회 참가기업·전시품 안내를 하는 챗봇이다. "
            "아래에 주어진 요약과 관련 문구만 사실의 근거로 사용한다. 없는 정보는 지어내지 말며, 해당 항목은 출력에서 생략한다. "
            "검색·랭킹·DB 상태·데이터 불충분 여부 같은 내부 이유는 사용자에게 설명하지 않는다."
        )
        user_tail = (
            "위 자료만 바탕으로 질문에 답해 줘. 위에서 제시한 **단일** 형식만 사용하고, 내부 메타는 숨겨. "
            "'정보가 부족하다', '등록이 덜 됐다' 같은 품질·데이터 상태 설명은 하지 말고 알려줄 수 있는 사실만 전달해."
        )
    style = _answer_style_hints(
        intent=intent,
        retrieval_topic=retrieval_topic,
        is_dialog_followup=is_dialog_followup,
        answer_focus=focus,
        language=language,
    )
    logger.info(
        "[answer] openai_generate(sync via thread) start query_len=%d results=%d context_chars=%d answer_focus=%s lang=%s",
        len(query or ""),
        len(results),
        len(context_text),
        focus,
        lang,
    )
    messages = [
        {
            "role": "system",
            "content": (
                f"{bot_role} {language_rule} {style} "
                + _llm_answer_format_instructions(focus=focus, language=language)
            ),
        },
        {
            "role": "user",
            "content": (
                (f"User question:\n{query}\n\nReference:\n{context_text}\n\n{user_tail}")
                if lang == "en"
                else (f"사용자 질문:\n{query}\n\n참고 자료 (검색 DB에서 가져온 내용):\n{context_text}\n\n{user_tail}")
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
            max_output_tokens=16384,
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
    lang = (language or "ko").strip().lower()
    if lang == "en":
        language_rule = "Respond in clear, natural English."
        sys_c = (
            "You are a helpful assistant. "
            f"{language_rule} "
            "Be concise: optional one-line summary, then '·' bullets. Use blank lines between paragraphs."
        )
        usr = f"User message: {query}\nReply briefly in a helpful way."
    else:
        language_rule = "한국어로 자연스럽게 답변"
        sys_c = (
            "너는 사용자 입력에 친절하게 반응하는 도우미다. "
            f"{language_rule}. "
            "짧게, **정리형**으로: 필요하면 첫 줄 요약 후 '·' 불릿. 문단 사이에는 빈 줄을 넣는다."
        )
        usr = f"사용자 입력: {query}\n이 메시지 의도에 맞게 간단히 응답해줘."
    messages = [
        {"role": "system", "content": sys_c},
        {"role": "user", "content": usr},
    ]
    return await asyncio.to_thread(
        partial(
            _sync_chat_completions_text,
            api_key=api_key,
            base_url=_answer_base_url_norm(base_url),
            model=model,
            messages=messages,
            max_output_tokens=4096,
        )
    )


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
    # 1) JSON payload 우선
    clean_query, payload_ext, payload_typ, payload_lang = _extract_entity_payload(query)
    query = clean_query or query
    # 2) legacy marker fallback
    clean_query2, ext_marker2 = _extract_external_id_marker(query)
    query = clean_query2 or query
    ext_marker = payload_ext or ext_marker2

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
            # payload로 entity_type이 지정되면 해당 타입만 우선 반환(엔티티 우선 retrieval)
            if payload_typ in {"company", "product"}:
                direct_results = [r for r in direct_results if str(r.get("entity_type") or "") == payload_typ] or direct_results
            _dl_lang = _resolve_answer_language(query, payload_lang)
            try:
                direct_results = await asyncio.to_thread(
                    enrich_results_with_entity_detail_sync,
                    engine=_sync_search_db_engine,
                    results=direct_results,
                    language=_dl_lang,
                )
            except Exception:
                logger.exception("[ENTITY_ENRICH] direct_lookup enrich failed (continuing)")
            _u_floor_dl = float(get_settings().retrieval_user_answer_min_score or 0.0)
            direct_results = sanitize_rag_results_for_user(direct_results, min_best_score=_u_floor_dl)
            _dl_intent = payload_typ if payload_typ in {"company", "product"} else "general"
            _dl_topic = payload_typ if payload_typ in {"company", "product"} else None
            answer_korean: str
            answer_meta_dl: dict[str, Any]
            if answer_mode == "openai" and key:
                try:
                    answer_korean = await _generate_korean_answer_with_openai(
                        query=query,
                        results=direct_results,
                        api_key=key,
                        base_url=(openai_base_url or "").strip(),
                        model=_ANSWER_OPENAI_MODEL,
                        intent=_dl_intent,
                        language=_dl_lang,
                        retrieval_topic=_dl_topic,
                        is_dialog_followup=False,
                    )
                    answer_meta_dl = {"mode": "direct_external_id_openai", "model": _ANSWER_OPENAI_MODEL}
                except Exception as e:
                    logger.exception("[search] direct_lookup openai failed: %s", e)
                    answer_korean = build_korean_search_answer(
                        query,
                        direct_results,
                        intent=_dl_intent,
                        retrieval_topic=_dl_topic,
                        language=_dl_lang,
                    )
                    answer_meta_dl = {"mode": "direct_external_id_template_fallback", "error": str(e)}
            else:
                answer_korean = build_korean_search_answer(
                    query,
                    direct_results,
                    intent=_dl_intent,
                    retrieval_topic=_dl_topic,
                    language=_dl_lang,
                )
                answer_meta_dl = {"mode": "direct_external_id"}
            suggestion_cards = await build_retrieval_suggestion_cards(direct_results, language=_dl_lang)
            return {
                "query": query,
                "top_k": max(1, int(top_k)),
                "lang": _dl_lang,
                "chunk_type": chunk_type,
                "count": len(direct_results),
                "retrieval": {
                    "intent": "direct_lookup",
                    "retrieval_topic": _dl_topic,
                    "is_dialog_followup": False,
                    "language": _dl_lang,
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
    # --- entity enrichment (제품/업체 RAG 품질 안정화) ---
    # 외부 id(external_id)로 실 entity 테이블에서 상세 정보를 조회해 results에 attach한다.
    try:
        results = await asyncio.to_thread(
            enrich_results_with_entity_detail_sync,
            engine=_sync_search_db_engine,
            results=results,
            language=str(retrieval_payload.get("language") or "ko"),
        )
    except Exception:
        logger.exception("[ENTITY_ENRICH] failed (answer still returned)")

    _u_floor = float(st.retrieval_user_answer_min_score or 0.0)
    results = sanitize_rag_results_for_user(results, min_best_score=_u_floor)
    retrieval_payload["final_results"] = results
    retrieval_payload["merged_entities"] = merged_entity_context(results)
    try:
        _, retrieval_payload["llm_context"] = apply_cutoff_and_build_context(
            results,
            score_cutoff=0.0,
            final_top_k=max(1, len(results)),
            context_limit=max(1, cl),
        )
    except Exception:
        logger.exception("[rag_sanitize] llm_context 재구성 실패 (기존 컨텍스트 유지)")
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
        answer_korean = build_korean_search_answer(
            query,
            results,
            intent=str(retrieval_payload["intent"]),
            retrieval_topic=retrieval_payload.get("retrieval_topic"),
            language=str(retrieval_payload.get("language") or "ko"),
        )
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
                answer_korean = build_korean_search_answer(
                    query,
                    results,
                    intent=str(retrieval_payload["intent"]),
                    retrieval_topic=retrieval_payload.get("retrieval_topic"),
                    language=str(retrieval_payload.get("language") or "ko"),
                )
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
    # 참가 기업/제품(RAG) 모드에서는 follow-up 버튼을 노출하지 않는다.
    followups_rag: list[dict[str, Any]] = []
    if response_mode == "retrieval" and results:
        try:
            suggestion_cards = await build_retrieval_suggestion_cards(
                results, language=str(retrieval_payload.get("language") or "ko")
            )
        except Exception as e:
            logger.warning("[search] suggestion_cards skipped: %s", e)
        followups_rag = []
    else:
        followups_rag = []

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
