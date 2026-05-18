"""FAQ 검색 서비스 계층.

이 계층은 FAQ 정책(faq_only, no LLM)과 응답 포맷(기존 API 호환)을 담당한다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.core.logger import get_logger

from .retriever import FaqRetriever
from app.rag.faq_normalizer import normalize_faq_query as normalize_faq_query_dict

logger = get_logger(__name__)


class FaqSearchService:
    """FAQ 검색 서비스.

    - FAQ 모드에서는 절대 LLM/RAG로 fallback 하지 않는다.
    - FAQ 검색은 PostgreSQL 기반(FTS+trgm+alias+문자열 rerank)만 사용한다.
    """

    def __init__(self, *, engine) -> None:
        self._engine = engine
        self._retriever = FaqRetriever(engine=engine)

    def search_and_build_payload(
        self,
        *,
        query: str,
        qa_user: str | None,
        faq_only: bool,
        trace_id: str | None = None,
        no_match_message: str,
    ) -> dict[str, Any] | None:
        """FAQ를 시도하고, 매칭되면 기존 API 형태의 payload(dict)를 만든다.

        반환:
        - 매칭 성공: payload(dict)
        - 매칭 실패: faq_only면 no-match payload(dict), 아니면 None(상위에서 다른 경로 가능)
        """

        # 인사/잡담은 FAQ 검색 자체를 타지 않는다(한국어 UX 개선)
        if self._looks_like_greeting(query):
            msg = "안녕하세요.\n전시회 FAQ(시간/기간/등록/셔틀/교통/출입증/주차 등)나 참가기업/제품 정보를 질문해 주세요."
            return {
                "query": query,
                "count": 0,
                "results": [],
                "answer": msg,
                "answer_meta": {"mode": "faq_greeting"},
                "cards": [],
                "follow_up_questions": [],
                "answer_korean": msg,
                "suggestion_cards": [],
            }

        res = self._retriever.search(query=query, qa_user=qa_user, limit=64, trace_id=trace_id)
        best = res.best
        if not best or not (best.answer_sample or "").strip():
            if faq_only:
                nd = normalize_faq_query_dict(query or "")
                canon = str(nd.get("canonical") or "").strip() or None
                examples = self._example_aliases(qa_user=qa_user, canonical_topic=canon, limit=3, fallback_popular=True)
                hint = (
                    "원하는 답변을 정확히 찾지 못했어요.\n"
                    "현재 선택한 FAQ 카테고리(참관객/참가업체)가 맞는지 확인해 주세요."
                )
                if examples:
                    hint = (hint + "\n\n아래 예시 질문이 비슷한가요?\n" + "\n".join([f"- {e}" for e in examples])).strip()
                else:
                    hint = (hint + "\n\n질문을 더 구체적인 키워드로 다시 입력해 주세요.").strip()
                return {
                    "query": query,
                    "count": 0,
                    "results": [],
                    "answer": hint,
                    "answer_meta": {
                        "mode": "faq_only_no_match",
                        "reason": "no_db_match",
                        "trace": res.trace,
                    },
                    "cards": [],
                    "follow_up_questions": [],
                    "answer_korean": hint,
                    "suggestion_cards": [],
                }
            return None

        # threshold 정책
        qn = str((res.trace or {}).get("query_norm") or "")
        is_short = len(qn.replace(" ", "")) <= 8
        exact = float((best.scores or {}).get("exact") or 0.0)
        score = float((best.scores or {}).get("final") or 0.0)
        thr_exact = 0.95
        thr_strong = 0.60 - (0.10 if is_short else 0.0)
        thr_suggest = 0.40 - (0.10 if is_short else 0.0)

        # exact/strong/suggest 판단
        if exact >= thr_exact:
            decided = "exact"
        elif score >= thr_strong:
            decided = "strong"
        elif score >= thr_suggest:
            decided = "suggest"
        else:
            decided = "no_match"

        logger.info(
            "[faq_v2] threshold query=%s norm=%s short=%s score=%.3f exact=%.3f decided=%s (exact>=%.2f strong>=%.2f suggest>=%.2f) trace_id=%s",
            (query or "")[:80],
            qn[:80],
            is_short,
            score,
            exact,
            decided,
            thr_exact,
            thr_strong,
            thr_suggest,
            trace_id or "-",
        )

        if decided == "no_match":
            # faq_only: 안내문 반환 / 비 faq_only: None → 상위에서 RAG fallback 가능
            if faq_only:
                nd = normalize_faq_query_dict(query or "")
                canon = str(nd.get("canonical") or "").strip() or None
                examples = self._example_aliases(qa_user=qa_user, canonical_topic=canon, limit=3, fallback_popular=True)
                hint = (
                    "원하는 답변을 정확히 찾지 못했어요.\n"
                    "현재 선택한 FAQ 카테고리(참관객/참가업체)가 맞는지 확인해 주세요."
                )
                if examples:
                    hint = (hint + "\n\n아래 예시 질문이 비슷한가요?\n" + "\n".join([f"- {e}" for e in examples])).strip()
                else:
                    hint = (hint + "\n\n질문을 더 구체적인 키워드로 다시 입력해 주세요.").strip()
                return {
                    "query": query,
                    "count": 0,
                    "results": [],
                    "answer": hint,
                    "answer_meta": {"mode": "faq_only_no_match", "reason": "threshold", "trace": res.trace},
                    "cards": [],
                    "follow_up_questions": [],
                    "answer_korean": hint,
                    "suggestion_cards": [],
                }
            return None

        if decided == "suggest" and not faq_only:
            # suggest는 RAG로 넘기지 않고, 후보 제시 메시지로 종료 (LLM 금지)
            lines = ["질문과 가까운 FAQ 후보가 있어요. 아래 중 가장 가까운 항목을 선택해서 다시 질문해 주세요."]
            for idx, c in enumerate(res.candidates[:5], start=1):
                label = (c.question_sample or c.quickmenu_label or c.subcategory or c.category or c.qna_code).strip()
                lines.append(f"{idx}. {label}")
            msg = "\n".join(lines).strip()
            return {
                "query": query,
                "count": 0,
                "results": [],
                "answer": msg,
                "answer_meta": {"mode": "faq_suggest", "trace": res.trace, "candidates": [c.__dict__ for c in res.candidates[:5]]},
                "cards": [],
                "follow_up_questions": [],
                "answer_korean": msg,
                "suggestion_cards": [],
            }

        ans = (best.answer_sample or "").strip()
        if (best.links or "").strip():
            ans = (ans + ("\n\n링크: " + (best.links or "").strip())).strip()

        followups = self._followups(qna_code=best.qna_code, qa_user=qa_user)
        return {
            "query": query,
            "count": 0,
            "results": [],
            "answer": ans,
            "answer_meta": {
                "mode": "faq_only" if faq_only else "faq",
                "qna_code": best.qna_code,
                "qa_user": best.qa_user,
                "scores": best.scores,
                "trace": res.trace,
            },
            "cards": [],
            "follow_up_questions": followups,
            "answer_korean": ans,
            "suggestion_cards": [],
        }

    def _example_aliases(
        self,
        *,
        qa_user: str | None,
        canonical_topic: str | None,
        limit: int = 3,
        fallback_popular: bool = False,
    ) -> list[str]:
        """실제로 검색 가능한 예시 문구를 DB에서 가져온다(하드코딩 금지)."""

        params: dict[str, Any] = {"lim": int(limit)}
        user_filter = ""
        if (qa_user or "").strip():
            params["qa_user"] = (qa_user or "").strip()
            user_filter = " AND (q.qa_user = :qa_user OR q.qa_user IS NULL OR q.qa_user = '')"

        topic_filter = ""
        if (canonical_topic or "").strip():
            params["topic"] = (canonical_topic or "").strip()
            topic_filter = " AND a.canonical_topic = :topic"

        # usage_count가 있으면 우선 사용, 없으면 랜덤
        sql = text(
            f"""
            SELECT a.alias_question
              FROM faq_alias a
              JOIN kprint_qa_quickmenu q ON q.qna_code = a.faq_id
             WHERE coalesce(trim(a.alias_question),'') <> ''{user_filter}{topic_filter}
             ORDER BY coalesce(a.usage_count, 0) DESC, random()
             LIMIT :lim
            """
        )
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(sql, params).mappings().all()
                out = [str(r.get("alias_question") or "").strip() for r in rows]
                picked = [x for x in out if x][:limit]
                if picked or not fallback_popular:
                    return picked

                # 토픽 매칭이 없으면 인기/랜덤 예시 3개로 fallback (항상 3개 노출)
                rows2 = conn.execute(
                    text(
                        f"""
                        SELECT a.alias_question
                          FROM faq_alias a
                          JOIN kprint_qa_quickmenu q ON q.qna_code = a.faq_id
                         WHERE coalesce(trim(a.alias_question),'') <> ''{user_filter}
                         ORDER BY coalesce(a.usage_count, 0) DESC, random()
                         LIMIT :lim
                        """
                    ),
                    {"lim": int(limit), **({"qa_user": params["qa_user"]} if "qa_user" in params else {})},
                ).mappings().all()
                out2 = [str(r.get("alias_question") or "").strip() for r in rows2]
                return [x for x in out2 if x][:limit]
        except Exception as e:  # noqa: BLE001
            logger.warning("[faq_v2] example aliases query failed: %s", e)
            return []

    def _looks_like_greeting(self, text: str) -> bool:
        t = (text or "").strip().lower()
        if not t:
            return False
        if len(t) <= 10 and any(k in t for k in ("안녕", "안녕하세요", "반가", "hello", "hi", "헬로")):
            return True
        return False

    def _followups(self, *, qna_code: str, qa_user: str | None) -> list[dict[str, Any]]:
        """follow_question1~4 기반 follow-up 버튼을 반환(동기 SQL)."""

        code = (qna_code or "").strip()
        if not code:
            return []
        params: dict[str, Any] = {"code": code}
        user_filter = ""
        if (qa_user or "").strip():
            params["qa_user"] = (qa_user or "").strip()
            user_filter = " AND (qa_user = :qa_user OR qa_user IS NULL OR qa_user = '')"

        row_sql = text(
            f"""
            SELECT follow_question1, follow_question2, follow_question3, follow_question4
              FROM kprint_qa_quickmenu
             WHERE qna_code = :code{user_filter}
             LIMIT 1
            """
        )
        with self._engine.connect() as conn:
            row = conn.execute(row_sql, params).mappings().first()
            if not row:
                return []
            raw_codes = [str(row.get(k) or "").strip() for k in ("follow_question1", "follow_question2", "follow_question3", "follow_question4")]
            codes = [c for c in raw_codes if c]
            if not codes:
                return []

            # km_ → kp_ 후보 변환 포함
            expanded: list[str] = []
            for c in codes:
                expanded.append(c)
                if c.startswith("km_"):
                    expanded.append("kp_" + c[3:])

            # dedupe preserve order
            seen: set[str] = set()
            expanded2: list[str] = []
            for c in expanded:
                if c in seen:
                    continue
                seen.add(c)
                expanded2.append(c)

            in_params = {f"c{i}": v for i, v in enumerate(expanded2)}
            in_list = ", ".join([f":c{i}" for i in range(len(expanded2))]) or "NULL"
            items_sql = text(
                f"""
                SELECT qna_code, quickmenu_label, question_sample, category, subcategory, domain
                  FROM kprint_qa_quickmenu
                 WHERE qna_code IN ({in_list}){user_filter}
                """
            )
            res = conn.execute(
                items_sql,
                {**in_params, **({"qa_user": params["qa_user"]} if "qa_user" in params else {})},
            ).mappings().all()
            by_code = {str(r.get("qna_code") or ""): dict(r) for r in res}

        out: list[dict[str, Any]] = []
        for c in codes:
            cand_codes = [c, ("kp_" + c[3:]) if c.startswith("km_") else ""]
            item = None
            resolved_code = None
            for cc in cand_codes:
                if cc and cc in by_code:
                    item = by_code[cc]
                    resolved_code = cc
                    break
            if not item:
                continue
            label = (
                (item.get("question_sample") or "")
                or (item.get("quickmenu_label") or "")
                or (item.get("subcategory") or "")
                or (item.get("category") or "")
                or (item.get("domain") or "")
                or (resolved_code or "")
            )
            label = str(label).strip()
            if not label:
                continue
            out.append({"qna_code": resolved_code, "label": label, "ask": label})
        return out[:4]

