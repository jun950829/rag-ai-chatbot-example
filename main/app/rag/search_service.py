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

from app.rag.pipeline import build_korean_search_answer
from app.rag.retrieval.memory import ConversationMemory
from app.rag.retrieval import RetrievalConfig, execute_retrieval_pipeline

logger = logging.getLogger(__name__)
_DEFAULT_MEMORY = ConversationMemory(max_turns=5)


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

    lines: list[str] = []
    for i, r in enumerate(results[:6], start=1):
        score = r.get("score")
        score_txt = f"{float(score):.4f}" if isinstance(score, (int, float)) else "-"
        content = (r.get("content") or "").strip().replace("\n", " / ")
        if len(content) > 220:
            content = content[:220].rstrip() + "..."
        lines.append(
            f"[{i}] score={score_txt}, lang={r.get('lang')}, type={r.get('chunk_typ')}, "
            f"external_id={r.get('external_id')}, source_field={r.get('source_field')}, content={content}"
        )
    context_text = "\n".join(lines)
    # --- 단계: 답변 LLM에 라우팅 intent와 검색 축·후행 여부를 함께 넘겨 톤을 맞춘다 ---
    rt = (retrieval_topic or "all").strip().lower()
    fu_txt = "직전 대화를 이어 받는 후행 질문" if is_dialog_followup else "신규 검색형 질문"
    user_tone = (
        f"질문 의도={intent}, 검색축={rt}, 대화특성={fu_txt}"
        if intent not in {"company", "product"} or is_dialog_followup
        else f"질문 의도가 명확한 검색 요청 (축={rt})"
    )
    language_rule = "한국어로 답변" if language == "ko" else "기본은 한국어, 필요 시 핵심 영문 키워드 병기"
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "너는 전시 참가업체 검색 도우미다. "
                    f"{language_rule}. "
                    "주어진 검색 결과만 근거로 답한다. 근거가 약하면 추정하지 말고 한계를 명시한다. "
                    "질문의 뉘앙스(비교/추천/요약/조건 필터)를 먼저 파악하고 그 의도에 맞는 형식으로 정리한다. "
                    "답변은 간결하되 실무적으로 유용해야 한다."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"질문: {query}\n\n"
                    f"의도 분류: {intent} | 검색축: {rt} | 후행: {is_dialog_followup}\n"
                    f"질문 톤 해석: {user_tone}\n\n"
                    f"검색 결과:\n{context_text}\n\n"
                    "요청:\n"
                    "1) 질문 의도에 맞게 핵심만 정제해서 답변\n"
                    "2) 추천/비교라면 선택 이유를 근거와 함께 제시\n"
                    "3) 마지막에 '근거 요약'을 한 줄로 정리"
                ),
            },
        ],
    )
    return ((resp.choices[0].message.content) or "").strip() or "LLM이 빈 답변을 반환했습니다."


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
                    "입력 의도와 뉘앙스(테스트, 확인, 요청)를 반영해 짧고 자연스럽게 응답한다."
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
            answer_meta = {"mode": "template_fallback", "error": "OPENAI_API_KEY is not set", "requested_mode": "openai"}
        else:
            try:
                answer_korean = await _generate_korean_answer_with_openai(
                    query=query,
                    results=results,
                    client=openai_client,
                    model=openai_model,
                    intent=retrieval_payload["intent"],
                    language=retrieval_payload["language"],
                    retrieval_topic=retrieval_payload.get("retrieval_topic"),
                    is_dialog_followup=bool(retrieval_payload.get("is_dialog_followup", False)),
                )
                answer_meta = {"mode": "openai", "model": openai_model}
            except Exception as e:
                answer_korean = (
                    f"[OpenAI 호출 실패로 템플릿 응답으로 대체] {build_korean_search_answer(query, results)} "
                    f"(원인: {e})"
                )
                answer_meta = {"mode": "template_fallback", "error": str(e), "requested_mode": "openai"}
    elif response_mode == "general_chat" and answer_mode == "openai":
        if openai_client is None:
            answer_meta = {
                "mode": "general_chat_template_fallback",
                "error": "OPENAI_API_KEY is not set",
                "requested_mode": "openai",
            }
        else:
            try:
                answer_korean = await _generate_general_answer_with_openai(
                    query=query,
                    client=openai_client,
                    model=openai_model,
                    language=retrieval_payload["language"],
                )
                answer_meta = {"mode": "general_chat_openai", "model": openai_model}
            except Exception as e:
                answer_meta = {
                    "mode": "general_chat_template_fallback",
                    "error": str(e),
                    "requested_mode": "openai",
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
    }
