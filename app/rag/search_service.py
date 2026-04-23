"""Vector search + answer assembly (runs in the API process; vectors may come from a remote embed server)."""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI

from app.rag.pipeline import build_korean_search_answer
from app.rag.retrieval import RetrievalConfig, execute_retrieval_pipeline

logger = logging.getLogger(__name__)


async def _generate_korean_answer_with_openai(
    *,
    query: str,
    results: list[dict[str, Any]],
    client: AsyncOpenAI,
    model: str,
    intent: str,
    language: str,
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
    user_tone = "질문 의도가 명확한 검색 요청" if intent == "new_company_query" else f"질문 의도={intent}"
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
                    f"의도 분류: {intent}\n"
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
    )

    results = retrieval_payload["final_results"]
    response_mode = retrieval_payload.get("response_mode", "retrieval")
    logger.info(
        "[retrieval] done mode=%s intent=%s language=%s queries=%d results=%d",
        response_mode,
        retrieval_payload["intent"],
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

    return {
        "query": query,
        "top_k": max(1, int(top_k)),
        "lang": retrieval_payload["language"],
        "chunk_type": chunk_type,
        "count": len(results),
        "retrieval": {
            "intent": retrieval_payload["intent"],
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
