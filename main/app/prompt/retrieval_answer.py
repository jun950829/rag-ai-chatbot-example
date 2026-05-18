"""RAG 검색 결과 기반 답변용 시스템·유저 메시지 조립."""

from __future__ import annotations

from typing import Any

from app.rag.pipeline import format_search_results_for_llm_context, infer_answer_focus


def answer_style_hints(
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


def llm_answer_format_instructions(*, focus: str, language: str = "ko") -> str:
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


def build_retrieval_openai_messages(
    *,
    query: str,
    results: list[dict[str, Any]],
    intent: str,
    language: str,
    retrieval_topic: str | None,
    is_dialog_followup: bool,
) -> list[dict[str, Any]]:
    """검색 근거 기반 한/영 답변용 messages. ``results`` 가 비어 있으면 호출하지 말 것."""
    lang = (language or "ko").strip().lower()
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
    style = answer_style_hints(
        intent=intent,
        retrieval_topic=retrieval_topic,
        is_dialog_followup=is_dialog_followup,
        answer_focus=focus,
        language=language,
    )
    return [
        {
            "role": "system",
            "content": (
                f"{bot_role} {language_rule} {style} "
                + llm_answer_format_instructions(focus=focus, language=language)
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
