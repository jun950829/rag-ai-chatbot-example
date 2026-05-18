"""FAQ 임베딩 기반 벡터 검색.

kprint_qa_quickmenu_embedding_qwen3_0_6b_kor / _eng 테이블을
pgvector cosine 거리로 검색하고 FaqCandidate 리스트를 반환한다.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.core.config import get_settings
from app.core.logger import get_logger
from app.retrieval.embedding_client import embed_queries_text_async
from app.retrieval.vector_db import get_sync_engine

from .models import FaqCandidate

log = get_logger(__name__)

_EMB_KOR = "kprint_qa_quickmenu_embedding_qwen3_0_6b_kor"
_EMB_ENG = "kprint_qa_quickmenu_embedding_qwen3_0_6b_eng"


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{float(x):.8f}" for x in vec) + "]"


async def search_faq_by_embedding(
    *,
    query: str,
    language: str,
    qa_user: str | None = None,
    top_k: int = 5,
) -> list[FaqCandidate]:
    """임베딩 서버로 query 를 벡터화한 뒤 FAQ 임베딩 테이블에서 유사 항목을 검색한다."""
    st = get_settings()
    q = (query or "").strip()
    if not q:
        return []

    # 1) 쿼리 임베딩
    try:
        vecs = await embed_queries_text_async(
            [q],
            model_id=st.retrieval_model_id,
            device=st.retrieval_device,
            remote_base_url=st.embedding_service_url or None,
        )
    except Exception as exc:
        log.warning("[faq_emb] 임베딩 서버 호출 실패: %s", exc)
        return []

    query_vec = vecs[0]
    lang = "eng" if (language or "ko").strip().lower() == "en" else "kor"
    table = _EMB_ENG if lang == "eng" else _EMB_KOR

    # 2) 벡터 검색
    user_filter = ""
    params: dict[str, Any] = {
        "embedding": _vector_literal(query_vec),
        "top_k": max(1, top_k),
    }
    if (qa_user or "").strip():
        user_filter = " AND (q.qa_user = :qa_user OR q.qa_user IS NULL OR q.qa_user = '')"
        params["qa_user"] = qa_user.strip()

    sql = sa.text(
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
            q.question_sample_eng,
            q.answer_sample_eng,
            q.links,
            q.notes,
            q.follow_question1,
            q.follow_question2,
            q.follow_question3,
            q.follow_question4,
            (e.embedding <=> CAST(:embedding AS vector)) AS distance
        FROM {table} e
        JOIN kprint_qa_quickmenu q ON q.qna_code = e.faq_id
        WHERE e.embedding IS NOT NULL
          {user_filter}
        ORDER BY e.embedding <=> CAST(:embedding AS vector)
        LIMIT :top_k
        """
    )

    try:
        engine = get_sync_engine()
        with engine.connect() as conn:
            rows = conn.execute(sql, params).mappings().all()
    except Exception as exc:
        log.warning("[faq_emb] DB 검색 실패: %s", exc)
        return []

    candidates: list[FaqCandidate] = []
    for r in rows:
        distance = float(r.get("distance") or 1.0)
        score = max(0.0, 1.0 - distance)
        candidates.append(
            FaqCandidate(
                qna_code=str(r.get("qna_code") or "").strip(),
                qa_user=(str(r.get("qa_user") or "").strip() or None),
                domain=(str(r.get("domain") or "").strip() or None),
                category=(str(r.get("category") or "").strip() or None),
                subcategory=(str(r.get("subcategory") or "").strip() or None),
                quickmenu_label=(str(r.get("quickmenu_label") or "").strip() or None),
                question_sample=(str(r.get("question_sample") or "").strip() or None),
                answer_sample=(str(r.get("answer_sample") or "").strip() or None),
                question_sample_eng=(str(r.get("question_sample_eng") or "").strip() or None),
                answer_sample_eng=(str(r.get("answer_sample_eng") or "").strip() or None),
                links=(str(r.get("links") or "").strip() or None),
                notes=(str(r.get("notes") or "").strip() or None),
                scores={"distance": distance, "score": score},
            )
        )

    log.info(
        "[faq_emb] query=%s lang=%s qa_user=%s top_k=%d hits=%d best_score=%.3f",
        q[:60],
        lang,
        qa_user or "-",
        top_k,
        len(candidates),
        candidates[0].scores["score"] if candidates else 0.0,
    )
    return candidates
