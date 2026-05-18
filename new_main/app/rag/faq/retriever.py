"""FAQRetriever: PostgreSQL 기반 고속 FAQ 검색기.

금지:
- embedding 생성 금지
- pgvector/semantic retrieval 금지
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.core.logger import get_logger

from .models import FaqCandidate, FaqSearchResult
from .normalize import normalize_faq_query
from .reranker import compute_rerank_score

logger = get_logger(__name__)


class FaqRetriever:
    """FAQ 검색 전용 Retriever.

    검색 방식:
    - websearch_to_tsquery + ts_rank_cd (FTS)
    - pg_trgm similarity + % 연산자(가능하면) 기반 후보 확장
    - alias 테이블(faq_alias) 포함
    - 문자열 기반 rerank로 최종 보정
    """

    def __init__(self, *, engine) -> None:
        self._engine = engine

    def search(
        self,
        *,
        query: str,
        qa_user: str | None = None,
        limit: int = 20,
        trace_id: str | None = None,
    ) -> FaqSearchResult:
        q_canon = normalize_faq_query(query)
        trace: dict[str, Any] = {"trace_id": trace_id, "query_norm": q_canon}
        if not q_canon:
            return FaqSearchResult(best=None, candidates=[], trace={**trace, "reason": "empty_query"})

        user_filter_sql = ""
        params: dict[str, Any] = {"q": query, "q_norm": q_canon, "lim": int(limit)}
        if (qa_user or "").strip():
            params["qa_user"] = (qa_user or "").strip()
            user_filter_sql = " AND (q.qa_user = :qa_user OR q.qa_user IS NULL OR q.qa_user = '')"

        exact_rows: list[dict[str, Any]] = []
        try:
            exact_sql = text(
                f"""
                SELECT
                  q.qna_code, q.qa_user, q.domain, q.category, q.subcategory,
                  q.quickmenu_label, q.question_sample, q.answer_sample, q.links, q.notes,
                  1.0::float AS exact_score
                FROM faq_alias a
                JOIN kprint_qa_quickmenu q ON q.qna_code = a.faq_id
                WHERE a.normalized_question = :q_norm{user_filter_sql}
                LIMIT 8
                """
            )
            with self._engine.connect() as conn:
                exact_rows = list(conn.execute(exact_sql, params).mappings().all())
        except Exception as e:  # noqa: BLE001
            trace["exact_error"] = str(e)

        trace["exact_hits"] = len(exact_rows)

        sql = text(
            f"""
            WITH fts AS (
              SELECT
                q.qna_code,
                q.qa_user,
                q.domain,
                q.category,
                q.subcategory,
                q.quickmenu_label,
                q.question_sample,
                q.answer_sample,
                q.links,
                q.notes,
                ts_rank(
                  COALESCE(
                    q.faq_search_tsv,
                    (
                      setweight(to_tsvector('simple', coalesce(q.question_sample,'')), 'A') ||
                      setweight(to_tsvector('simple', coalesce(q.quickmenu_label,'')), 'A') ||
                      setweight(to_tsvector('simple', coalesce(q.category,'')), 'B') ||
                      setweight(to_tsvector('simple', coalesce(q.subcategory,'')), 'B') ||
                      setweight(to_tsvector('simple', coalesce(q.answer_sample,'')), 'C')
                    )
                  ),
                  websearch_to_tsquery('simple', :q_norm)
                ) AS fts_rank
                ,
                0.0::float AS trgm_sim
              FROM kprint_qa_quickmenu q
              WHERE (
                COALESCE(
                  q.faq_search_tsv,
                  (
                    setweight(to_tsvector('simple', coalesce(q.question_sample,'')), 'A') ||
                    setweight(to_tsvector('simple', coalesce(q.quickmenu_label,'')), 'A') ||
                    setweight(to_tsvector('simple', coalesce(q.category,'')), 'B') ||
                    setweight(to_tsvector('simple', coalesce(q.subcategory,'')), 'B') ||
                    setweight(to_tsvector('simple', coalesce(q.answer_sample,'')), 'C')
                  )
                ) @@ websearch_to_tsquery('simple', :q_norm)
              ){user_filter_sql}
              ORDER BY fts_rank DESC
              LIMIT 20
            ),
            trgm AS (
              SELECT
                q.qna_code,
                q.qa_user,
                q.domain,
                q.category,
                q.subcategory,
                q.quickmenu_label,
                q.question_sample,
                q.answer_sample,
                q.links,
                q.notes,
                0.0::float AS fts_rank,
                GREATEST(
                  similarity(coalesce(q.question_sample,''), :q),
                  similarity(coalesce(q.quickmenu_label,''), :q),
                  similarity(coalesce(q.category,''), :q),
                  similarity(coalesce(q.subcategory,''), :q)
                ) AS trgm_sim
              FROM kprint_qa_quickmenu q
              WHERE (
                    GREATEST(
                      similarity(coalesce(q.question_sample,''), :q),
                      similarity(coalesce(q.quickmenu_label,''), :q),
                      similarity(coalesce(q.category,''), :q),
                      similarity(coalesce(q.subcategory,''), :q)
                    ) >= 0.18
                 OR coalesce(q.question_sample,'') % :q
                 OR coalesce(q.quickmenu_label,'') % :q
              ){user_filter_sql}
              ORDER BY trgm_sim DESC
              LIMIT 20
            ),
            alias_trgm AS (
              SELECT
                q.qna_code,
                max(similarity(coalesce(a.alias_question,''), :q)) AS alias_sim,
                max(CASE WHEN coalesce(a.alias_question,'') % :q THEN 1 ELSE 0 END) AS alias_match
              FROM faq_alias a
              JOIN kprint_qa_quickmenu q ON q.qna_code = a.faq_id
              WHERE (
                    similarity(coalesce(a.alias_question,''), :q) >= 0.20
                 OR coalesce(a.alias_question,'') % :q
                 OR to_tsvector('simple', coalesce(a.alias_question,'')) @@ websearch_to_tsquery('simple', :q_norm)
              ){user_filter_sql}
              GROUP BY q.qna_code
            )
            SELECT
              x.*,
              coalesce(at.alias_sim, 0.0) AS alias_sim,
              coalesce(at.alias_match, 0)::int AS alias_match,
              coalesce(x.fts_rank, 0.0) AS fts_rank,
              coalesce(x.trgm_sim, 0.0) AS trgm_sim
            FROM (
              SELECT * FROM fts
              UNION ALL
              SELECT * FROM trgm
            ) x
            LEFT JOIN alias_trgm at ON at.qna_code = x.qna_code
            """
        )

        rows: list[dict[str, Any]] = []
        try:
            with self._engine.connect() as conn:
                rows = list(conn.execute(sql, params).mappings().all())
        except Exception as e:  # noqa: BLE001
            trace["db_error"] = str(e)
            logger.warning("[faq][%s] search failed, fallback to FTS-only: %s", trace_id or "-", e)
            fts_only = text(
                f"""
                SELECT
                  q.qna_code,
                  q.qa_user,
                  q.domain,
                  q.category,
                  q.subcategory,
                  q.quickmenu_label,
                  q.question_sample,
                  q.answer_sample,
                  q.links,
                  q.notes,
                  (
                    ts_rank_cd(
                      to_tsvector('simple', coalesce(q.question_sample,'') || ' ' || coalesce(q.quickmenu_label,'') || ' ' || coalesce(q.category,'') || ' ' || coalesce(q.subcategory,'') || ' ' || coalesce(q.domain,'')),
                      websearch_to_tsquery('simple', :q_norm)
                    )
                    + 0.60 * ts_rank_cd(
                      to_tsvector('simple', coalesce(q.question_sample,'') || ' ' || coalesce(q.quickmenu_label,'') || ' ' || coalesce(q.category,'') || ' ' || coalesce(q.subcategory,'') || ' ' || coalesce(q.domain,'')),
                      plainto_tsquery('simple', :q_norm)
                    )
                  ) AS fts_rank
                FROM kprint_qa_quickmenu q
                WHERE (
                  to_tsvector('simple', coalesce(q.question_sample,'') || ' ' || coalesce(q.quickmenu_label,'') || ' ' || coalesce(q.category,'') || ' ' || coalesce(q.subcategory,'') || ' ' || coalesce(q.domain,''))
                    @@ websearch_to_tsquery('simple', :q_norm)
                  OR to_tsvector('simple', coalesce(q.question_sample,'') || ' ' || coalesce(q.quickmenu_label,'') || ' ' || coalesce(q.category,'') || ' ' || coalesce(q.subcategory,'') || ' ' || coalesce(q.domain,''))
                    @@ plainto_tsquery('simple', :q_norm)
                ){user_filter_sql}
                ORDER BY fts_rank DESC
                LIMIT :lim
                """
            )
            try:
                with self._engine.connect() as conn:
                    rows = list(conn.execute(fts_only, params).mappings().all())
                    trace["fallback"] = "fts_only"
            except Exception as e2:  # noqa: BLE001
                return FaqSearchResult(
                    best=None,
                    candidates=[],
                    trace={**trace, "reason": "db_error", "error": str(e2)},
                )

        trace["fts_trgm_candidates"] = len(rows)
        cands: list[FaqCandidate] = []
        by_code: dict[str, dict[str, Any]] = {}
        for r in (exact_rows + rows):
            code = str(r.get("qna_code") or "").strip()
            if not code:
                continue
            prev = by_code.get(code)
            rdict = dict(r)
            if rdict.get("fts_rank") in (None, 0) and rdict.get("ts_rank") is not None:
                rdict["fts_rank"] = rdict.get("ts_rank")
            if not prev:
                by_code[code] = rdict
                continue
            for k in ("fts_rank", "trgm_sim", "alias_sim", "alias_match", "exact_score"):
                pv = float(prev.get(k) or 0.0)
                nv = float(rdict.get(k) or 0.0)
                if nv > pv:
                    prev[k] = rdict[k]
            by_code[code] = prev

        trace["db_candidates"] = len(by_code)

        for r in by_code.values():
            exact = float(r.get("exact_score") or 0.0)
            fts_rank = float(r.get("fts_rank") or r.get("ts_rank") or 0.0)
            trgm_sim = max(float(r.get("trgm_sim") or 0.0), float(r.get("alias_sim") or 0.0))
            alias_match = 1.0 if int(r.get("alias_match") or 0) else (1.0 if exact >= 0.99 else 0.0)

            cat_blob = " ".join(str(r.get(k) or "") for k in ("domain", "category", "subcategory")).strip().lower()
            cat_boost = 0.05 if (cat_blob and any(x and x in cat_blob for x in q_canon.split(" ")[:4])) else 0.0

            q_tokens = [t for t in q_canon.split(" ") if len(t) >= 2][:12]
            cand_blob = " ".join(str(r.get(k) or "") for k in ("question_sample", "quickmenu_label", "category", "subcategory", "answer_sample")).lower()
            hit = sum(1 for t in q_tokens if t and t in cand_blob)
            keyword_overlap = (hit / max(1, len(q_tokens))) if q_tokens else 0.0

            kw_boost = 0.0
            for kw in ("시간", "위치", "방법", "요금", "주차"):
                if kw in q_canon and kw in cand_blob:
                    kw_boost += 0.03

            final_score = (
                (exact * 1.0)
                + (fts_rank * 0.45)
                + (trgm_sim * 0.45)
                + (keyword_overlap * 0.10)
                + kw_boost
                + (cat_boost * 0.02)
            )

            cand_text = " ".join(
                str(x or "")
                for x in (
                    r.get("question_sample"),
                    r.get("quickmenu_label"),
                    r.get("subcategory"),
                    r.get("category"),
                    r.get("domain"),
                )
            ).strip()
            rr = compute_rerank_score(query, cand_text)
            final_score = float(min(2.0, final_score + (rr.total * 0.10)))

            cands.append(
                FaqCandidate(
                    qna_code=str(r.get("qna_code") or "").strip(),
                    qa_user=(str(r.get("qa_user") or "").strip() or None),
                    domain=(str(r.get("domain") or "").strip() or None),
                    category=(str(r.get("category") or "").strip() or None),
                    subcategory=(str(r.get("subcategory") or "").strip() or None),
                    quickmenu_label=(str(r.get("quickmenu_label") or "").strip() or None),
                    question_sample=(str(r.get("question_sample") or "").strip() or None),
                    answer_sample=(str(r.get("answer_sample") or "").strip() or None),
                    links=(str(r.get("links") or "").strip() or None),
                    notes=(str(r.get("notes") or "").strip() or None),
                    scores={
                        "exact": exact,
                        "fts_rank": fts_rank,
                        "trgm_sim": trgm_sim,
                        "alias_match": alias_match,
                        "cat_boost": cat_boost,
                        "keyword_overlap": float(keyword_overlap),
                        "kw_boost": float(kw_boost),
                        "rerank": float(rr.total),
                        "final": float(final_score),
                    },
                )
            )

        cands.sort(key=lambda x: float((x.scores or {}).get("final") or 0.0), reverse=True)
        best = cands[0] if cands else None
        if best:
            trace["best_qna_code"] = best.qna_code
            trace["best_scores"] = best.scores
            logger.info(
                "[faq_v2] query=%s exact=%s fts=%s trgm=%s final=%s score=%.3f trace_id=%s",
                (query or "")[:80],
                float((best.scores or {}).get("exact") or 0.0),
                float((best.scores or {}).get("fts_rank") or 0.0),
                float((best.scores or {}).get("trgm_sim") or 0.0),
                float((best.scores or {}).get("final") or 0.0),
                float((best.scores or {}).get("final") or 0.0),
                trace_id or "-",
            )
        return FaqSearchResult(best=best, candidates=cands[:8], trace=trace)
