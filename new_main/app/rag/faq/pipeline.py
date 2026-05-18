"""FAQ 파이프라인.

chat_pipeline.py 와 대응하는 FAQ 전용 파이프라인.
임베딩 기반 시맨틱 검색으로 FAQ 를 찾고, 언어에 맞는 답변을 반환한다.

흐름:
    1) 질문 정규화
    2) 언어 감지 (ko / en)
    3) FAQ 전용 qa_user 분류 (visitor / exhibitor / None)
    4) 임베딩 검색 (언어별 테이블)
    5) 임계값 판정 → 답변 반환
"""

from __future__ import annotations

from typing import Any

from app.core.logger import logger
from app.retrieval.vector_db import get_sync_engine
from app.services.steps.intent import heuristic_catalog_redirect_intent
from app.services.steps.language import detect_language
from app.services.steps.normalize import normalize_question
from sqlalchemy import text

from .embedding_retriever import search_faq_by_embedding
from .intent import classify_faq_qa_user
from .models import FaqCandidate

# app.core.logger 의 공용 logger 인스턴스 (setup_logger / configure_root_logging 체인 사용)

# 임베딩 유사도 임계값
_SCORE_STRONG = 0.75   # 바로 답변
_SCORE_SUGGEST = 0.55  # 후보 제안


def _find_direct_match(query: str, qa_user: str | None) -> FaqCandidate | None:
    """quickmenu_label 또는 question_sample 이 정확히 일치하면 DB에서 직접 반환."""
    q = query.strip()
    if not q:
        return None

    params: dict[str, Any] = {"query": q}
    user_filter = ""
    if (qa_user or "").strip():
        params["qa_user"] = qa_user.strip()
        user_filter = " AND (qa_user = :qa_user OR qa_user IS NULL OR qa_user = '')"

    try:
        engine = get_sync_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    f"""
                    SELECT qna_code, qa_user, domain, category, subcategory, quickmenu_label,
                           question_sample, answer_sample, question_sample_eng, answer_sample_eng,
                           links, notes
                      FROM kprint_qa_quickmenu
                     WHERE (LOWER(quickmenu_label) = LOWER(:query)
                            OR LOWER(question_sample) = LOWER(:query))
                           {user_filter}
                     LIMIT 1
                    """
                ),
                params,
            ).mappings().first()
        if not row:
            return None
        return FaqCandidate(
            qna_code=str(row["qna_code"]),
            qa_user=(str(row.get("qa_user") or "")).strip() or None,
            domain=(str(row.get("domain") or "")).strip() or None,
            category=(str(row.get("category") or "")).strip() or None,
            subcategory=(str(row.get("subcategory") or "")).strip() or None,
            quickmenu_label=(str(row.get("quickmenu_label") or "")).strip() or None,
            question_sample=(str(row.get("question_sample") or "")).strip() or None,
            answer_sample=(str(row.get("answer_sample") or "")).strip() or None,
            question_sample_eng=(str(row.get("question_sample_eng") or "")).strip() or None,
            answer_sample_eng=(str(row.get("answer_sample_eng") or "")).strip() or None,
            links=(str(row.get("links") or "")).strip() or None,
            notes=(str(row.get("notes") or "")).strip() or None,
            scores={"score": 1.0, "distance": 0.0},
        )
    except Exception as exc:
        logger.warning("[faq_pipeline] direct match 조회 실패: %s", exc)
        return None


async def faq_pipeline(
    *,
    query: str,
    qa_user: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """FAQ 파이프라인 진입점. `tools_compat.py` 의 `/tools/embedding/api/search` 에서 호출."""

    # 1) 정규화
    normalized = await normalize_question(query)
    if not normalized.strip():
        return _empty_response(query)

    # 2) 언어 감지
    language = detect_language(normalized)

    # 3) qa_user 분류 — 호출 측에서 명시적으로 넘기면 그걸 우선 사용
    resolved_qa_user = (qa_user or "").strip() or classify_faq_qa_user(normalized)

    logger.info(
        "[faq_pipeline] query=%s lang=%s qa_user=%s",
        normalized[:60],
        language,
        resolved_qa_user or "-",
    )

    # 4) quickmenu_label / question_sample 직접 일치 우선 검색
    direct = _find_direct_match(normalized, resolved_qa_user)
    if direct:
        logger.info("[faq_pipeline] direct match qna_code=%s", direct.qna_code)
        answer = _pick_answer(direct, language)
        if answer:
            followups = _resolve_followups(direct.qna_code, resolved_qa_user)
            return {
                "query": query,
                "count": 1,
                "results": [],
                "answer": answer,
                "answer_meta": {
                    "mode": "faq_direct",
                    "qna_code": direct.qna_code,
                    "qa_user": direct.qa_user,
                    "language": language,
                    "scores": direct.scores,
                },
                "cards": [],
                "follow_up_questions": followups,
                "answer_korean": direct.answer_sample or "",
                "suggestion_cards": [],
            }

    # 5) 임베딩 검색
    candidates = await search_faq_by_embedding(
        query=normalized,
        language=language,
        qa_user=resolved_qa_user,
        top_k=top_k,
    )

    # 5) 임계값 판정 및 응답 조립
    return _build_response(
        query=query,
        normalized=normalized,
        language=language,
        candidates=candidates,
        qa_user=resolved_qa_user,
    )


def _build_response(
    *,
    query: str,
    normalized: str,
    language: str,
    candidates: list[FaqCandidate],
    qa_user: str | None,
) -> dict[str, Any]:
    if not candidates:
        return _faq_no_match_outcome(query, normalized, language)

    best = candidates[0]
    score = float(best.scores.get("score", 0.0))

    if score >= _SCORE_STRONG:
        decided = "strong"
    elif score >= _SCORE_SUGGEST:
        decided = "suggest"
    else:
        decided = "no_match"

    logger.info(
        "[faq_pipeline] decided=%s score=%.3f qna_code=%s",
        decided,
        score,
        best.qna_code,
    )

    if decided == "no_match":
        return _faq_no_match_outcome(query, normalized, language)

    if decided == "suggest":
        return _suggest_response(query, language, candidates[:5])

    # strong match → 언어에 맞는 답변 반환
    answer = _pick_answer(best, language)
    if not answer:
        return _faq_no_match_outcome(query, normalized, language)

    followups = _resolve_followups(best.qna_code, qa_user)

    return {
        "query": query,
        "count": 1,
        "results": [],
        "answer": answer,
        "answer_meta": {
            "mode": "faq_embedding",
            "qna_code": best.qna_code,
            "qa_user": best.qa_user,
            "language": language,
            "scores": best.scores,
        },
        "cards": [],
        "follow_up_questions": followups,
        "answer_korean": best.answer_sample or "",
        "suggestion_cards": [],
    }


def _pick_answer(candidate: FaqCandidate, language: str) -> str:
    """언어에 맞는 답변 선택. 영어 번역이 없으면 한국어 fallback."""
    if language == "en":
        eng = (candidate.answer_sample_eng or "").strip()
        if eng:
            if (candidate.links or "").strip():
                eng += "\n\nLink: " + candidate.links.strip()
            return eng
    kor = (candidate.answer_sample or "").strip()
    if kor and (candidate.links or "").strip():
        kor += "\n\n링크: " + candidate.links.strip()
    return kor


def _suggest_response(query: str, language: str, candidates: list[FaqCandidate]) -> dict[str, Any]:
    if language == "en":
        intro = "Here are some related FAQ topics. Please select the closest one and ask again."
    else:
        intro = "질문과 가까운 FAQ 후보가 있어요. 아래 중 가장 가까운 항목을 선택해서 다시 질문해 주세요."

    lines = [intro]
    for i, c in enumerate(candidates, start=1):
        label = (
            (c.question_sample_eng if language == "en" else None)
            or c.question_sample
            or c.quickmenu_label
            or c.subcategory
            or c.category
            or c.qna_code
        )
        lines.append(f"{i}. {(label or '').strip()}")

    return {
        "query": query,
        "count": 0,
        "results": [],
        "answer": "\n".join(lines),
        "answer_meta": {
            "mode": "faq_embedding_suggest",
            "language": language,
            "candidates": [c.qna_code for c in candidates],
        },
        "cards": [],
        "follow_up_questions": [],
        "answer_korean": "\n".join(lines),
        "suggestion_cards": [],
    }


def _faq_no_match_outcome(query: str, normalized: str, language: str) -> dict[str, Any]:
    """FAQ 미매칭 시 휴리스틱 intent 로 제품/업체 검색으로 유도할지 결정."""
    h = heuristic_catalog_redirect_intent(normalized, language)
    preview = (normalized or "").replace("\n", " ")[:100]
    if h in ("company_query", "product_query"):
        logger.info(
            "[faq_pipeline] no_match_outcome branch=catalog_hint heuristic=%s lang=%s query_preview=%r",
            h,
            language,
            preview,
        )
        return _no_match_response_catalog_switch(query, language, h)
    logger.info(
        "[faq_pipeline] no_match_outcome branch=message_only heuristic=%s lang=%s query_preview=%r",
        h if h is not None else "none",
        language,
        preview,
    )
    return _no_match_response(query, language)


def _no_match_response_catalog_switch(
    query: str, language: str, search_intent: str,
) -> dict[str, Any]:
    base = _no_match_response(query, language)
    if language == "en":
        if search_intent == "product_query":
            hint = (
                "Your question looks like a product or exhibit item search rather than an FAQ. "
                "Switch to Product & company search below and ask again."
            )
        else:
            hint = (
                "Your question looks like an exhibitor or company search rather than an FAQ. "
                "Switch to Product & company search below and ask again."
            )
    else:
        if search_intent == "product_query":
            hint = (
                "질문 내용이 FAQ보다는 전시 **제품** 정보에 가깝습니다. "
                "아래에서 **제품/기업 검색**으로 전환한 뒤 다시 질문해 주세요."
            )
        else:
            hint = (
                "질문 내용이 FAQ보다는 **참가업체** 정보에 가깝습니다. "
                "아래에서 **제품/기업 검색**으로 전환한 뒤 다시 질문해 주세요."
            )
    answer = f"{base['answer']}\n\n{hint}"
    meta = dict(base.get("answer_meta") or {})
    meta["mode"] = "faq_embedding_no_match_catalog_hint"
    meta["intent"] = search_intent
    meta["show_catalog_mode_switcher"] = True
    logger.info(
        "[faq_pipeline] catalog_hint reply intent=%s lang=%s mode=%s",
        search_intent,
        language,
        meta["mode"],
    )
    return {
        **base,
        "answer": answer,
        "answer_korean": answer,
        "answer_meta": meta,
    }


def _no_match_response(query: str, language: str) -> dict[str, Any]:
    if language == "en":
        msg = "I couldn't find an exact match for your question. Please try rephrasing or use a more specific keyword."
    else:
        msg = "원하는 답변을 정확히 찾지 못했어요. 질문을 더 구체적인 키워드로 다시 입력해 주세요."
    return {
        "query": query,
        "count": 0,
        "results": [],
        "answer": msg,
        "answer_meta": {"mode": "faq_embedding_no_match", "show_catalog_mode_switcher": False},
        "cards": [],
        "follow_up_questions": [],
        "answer_korean": msg,
        "suggestion_cards": [],
    }


def _empty_response(query: str) -> dict[str, Any]:
    return {
        "query": query,
        "count": 0,
        "results": [],
        "answer": "질문을 입력해 주세요.",
        "answer_meta": {"mode": "empty"},
        "cards": [],
        "follow_up_questions": [],
        "answer_korean": "질문을 입력해 주세요.",
        "suggestion_cards": [],
    }


def _resolve_followups(qna_code: str, qa_user: str | None) -> list[dict[str, Any]]:
    """후속 질문 코드를 label 과 함께 조회한다."""
    code = (qna_code or "").strip()
    if not code:
        return []

    params: dict[str, Any] = {"code": code}
    user_filter = ""
    if (qa_user or "").strip():
        params["qa_user"] = qa_user.strip()
        user_filter = " AND (qa_user = :qa_user OR qa_user IS NULL OR qa_user = '')"

    try:
        engine = get_sync_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    f"""
                    SELECT follow_question1, follow_question2, follow_question3, follow_question4
                      FROM kprint_qa_quickmenu
                     WHERE qna_code = :code {user_filter}
                     LIMIT 1
                    """
                ),
                params,
            ).mappings().first()
            if not row:
                return []

            codes = [
                str(row.get(k) or "").strip()
                for k in ("follow_question1", "follow_question2", "follow_question3", "follow_question4")
                if (row.get(k) or "").strip()
            ]
            if not codes:
                return []

            placeholders = ", ".join(f":c{i}" for i in range(len(codes)))
            items = conn.execute(
                text(
                    f"""
                    SELECT qna_code, quickmenu_label, question_sample
                      FROM kprint_qa_quickmenu
                     WHERE qna_code IN ({placeholders}) {user_filter}
                    """
                ),
                {**{f"c{i}": v for i, v in enumerate(codes)}, **({} if not (qa_user or "").strip() else {"qa_user": qa_user.strip()})},
            ).mappings().all()

        by_code = {str(r["qna_code"]): dict(r) for r in items}
        out: list[dict[str, Any]] = []
        for c in codes:
            item = by_code.get(c)
            if not item:
                continue
            label = (item.get("question_sample") or item.get("quickmenu_label") or c).strip()
            out.append({"qna_code": c, "label": label, "ask": label})
        return out[:4]
    except Exception as exc:
        logger.warning("[faq_pipeline] followups 조회 실패: %s", exc)
        return []
