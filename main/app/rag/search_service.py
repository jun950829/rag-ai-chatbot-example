"""RAG 검색 오케스트레이션 (API 프로세스 내 동기 DB + 선택적 원격 임베딩).

흐름 요약:
1. ``session_id`` 가 있으면 Async DB에서 ``ConversationMemory`` 적재·히스토리 여부 계산
2. ``execute_retrieval_pipeline`` — 의도/검색축 분류 → (검색형이면) 쿼리 계획 → pgvector 다중 쿼리 검색 → RRF·컷오프
3. 세션 모드에서는 **분류·검색이 끝난 뒤** ``MessageService.save_user_message`` 로 intent·``retrieval_topic``·follow-up 메타 저장
4. 답변: 템플릿 또는 OpenAI (``answer_mode``)

자세한 구조는 저장소 루트 ``docs/CHATBOT_ARCHITECTURE.md`` 참고.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from openai import AsyncOpenAI

from app.rag.pipeline import build_korean_search_answer, format_search_results_for_llm_context
from app.rag.retrieval.memory import ConversationMemory
from app.rag.retrieval import RetrievalConfig, execute_retrieval_pipeline
from app.rag.suggestion_cards import build_retrieval_suggestion_cards

logger = logging.getLogger(__name__)
_DEFAULT_MEMORY = ConversationMemory(max_turns=5)
_ANSWER_OPENAI_MODEL = "gpt-5-mini"


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
    client: AsyncOpenAI,
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
        "[answer] openai_generate start query_len=%d results=%d context_chars=%d",
        len(query or ""),
        len(results),
        len(context_text),
    )
    resp = await client.chat.completions.create(
        model=model,
        messages=[
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
        ],
    )
    out = ((resp.choices[0].message.content) or "").strip() or "LLM이 빈 답변을 반환했습니다."
    logger.info("[answer] openai_generate done answer_chars=%d", len(out))
    return out


async def _generate_general_answer_with_openai(
    *,
    query: str,
    client: AsyncOpenAI,
    model: str,
    language: str,
) -> str:
    language_rule = "한국어로 자연스럽게 답변" if language == "ko" else "기본은 한국어, 필요 시 영어 병기"
    resp = await client.chat.completions.create(
        model=model,
        messages=[
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
        ],
    )
    return ((resp.choices[0].message.content) or "").strip() or "LLM이 빈 답변을 반환했습니다."


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
) -> dict[str, Any]:
    if chunk_type not in {"all", "profile", "evidence"}:
        raise ValueError("chunk_type must be one of: all, profile, evidence")
    if answer_mode not in {"template", "openai"}:
        raise ValueError("answer_mode must be one of: template, openai")

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

    if session_id:
        from app.db.session import AsyncSessionLocal
        from app.services import ConversationService, is_followup_v2

        async with AsyncSessionLocal() as db:
            conv = ConversationService(db)
            sid = await conv.get_or_create_session(session_id)
            db_memory = await conv.hydrate_memory(sid, limit=5)
            has_history = len(db_memory.get_recent()) > 0
            hist_texts = [m.get("message", "") for m in db_memory.get_recent()][-5:]
            is_fu, fu_conf, fu_meta = is_followup_v2(current=query, history=hist_texts)
            fu_state = (is_fu, fu_conf, fu_meta)
            session_uuid_for_save = sid

    logger.info("[search] retrieval_pipeline ...")
    retrieval_payload = await execute_retrieval_pipeline(
        query,
        config=RetrievalConfig(
            model_id=model_id,
            device=device or None,
            top_k_per_query=max(6, top_k),
            final_top_k=max(1, top_k),
            score_cutoff=0.22,
            evidence_ratio=0.6,
            min_queries=3,
            max_queries=5,
            rrf_k=60,
            context_limit=6,
        ),
        openai_client=openai_client,
        intent_model=openai_model,
        embedding_remote_base_url=embedding_remote_base_url,
        has_history=has_history,
        memory=db_memory or _DEFAULT_MEMORY,
    )

    # --- 단계 1: 파이프라인 결과로 사용자 메시지 메타를 확정 저장 (세션 모드 전용) ---
    if session_uuid_for_save is not None:
        from app.db.session import AsyncSessionLocal
        from app.services import MessageService

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

        async with AsyncSessionLocal() as db:
            msg_svc = MessageService(db)
            await msg_svc.save_user_message(
                session_id=session_uuid_for_save,
                content=query,
                intent=pip_intent,
                is_followup=pip_fu,
                confidence=conf,
                retrieval_topic=pip_topic,
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
        if openai_client is None:
            logger.warning("[search] openai requested but OPENAI_API_KEY missing → template")
            answer_meta = {"mode": "template_fallback", "error": "OPENAI_API_KEY is not set", "requested_mode": "openai"}
        else:
            try:
                answer_korean = await _generate_korean_answer_with_openai(
                    query=query,
                    results=results,
                    client=openai_client,
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
        if openai_client is None:
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
                    client=openai_client,
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
    if response_mode == "retrieval" and results:
        try:
            suggestion_cards = await build_retrieval_suggestion_cards(results)
        except Exception as e:
            logger.warning("[search] suggestion_cards skipped: %s", e)

    if memory is None:
        _DEFAULT_MEMORY.add("assistant", answer_korean)
    else:
        memory.add("assistant", answer_korean)

    # (프로덕션) 세션 기반일 때 assistant 메시지 저장
    if session_id:
        from app.db.session import AsyncSessionLocal
        from app.services import ConversationService, MessageService

        async with AsyncSessionLocal() as db:
            conv = ConversationService(db)
            msg_svc = MessageService(db)
            sid = await conv.get_or_create_session(session_id)
            await msg_svc.save_assistant_message(session_id=sid, content=answer_korean)

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
        },
        "answer_korean": answer_korean,
        "answer_meta": answer_meta,
        "results": results,
        "suggestion_cards": suggestion_cards,
    }
