from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from embedding.pipeline import (
    DEFAULT_EMBEDDING_DEVICE,
    DEFAULT_EMBEDDING_MODEL_ID,
    embed_query_text,
    search_embedding_tables,
)

logger = logging.getLogger(__name__)

INTENT_LABELS = {"greeting", "followup", "new_company_query", "general", "not_related"}
LANGUAGE_LABELS = {"ko", "en"}

_KOREAN_RE = re.compile(r"[가-힣]")
_ENGLISH_RE = re.compile(r"[A-Za-z]")

_GREETING_WORDS = {
    "안녕",
    "안녕하세요",
    "반가워",
    "hello",
    "hi",
    "hey",
    "good morning",
    "good afternoon",
}
_FOLLOWUP_PREFIXES = (
    "그럼",
    "그럼요",
    "그리고",
    "또",
    "then",
    "also",
    "what about",
    "how about",
    "추가로",
    "계속",
)
_NOT_RELATED_HINTS = (
    "날씨",
    "주가",
    "환율",
    "점심",
    "sports",
    "bitcoin",
    "movie",
    "recipe",
)
_NEW_COMPANY_HINTS = (
    "업체",
    "회사",
    "기업",
    "참가",
    "전시",
    "부스",
    "company",
    "exhibitor",
    "booth",
    "hall",
    "profile",
)


@dataclass(frozen=True)
class RetrievalConfig:
    model_id: str = DEFAULT_EMBEDDING_MODEL_ID
    device: str | None = DEFAULT_EMBEDDING_DEVICE
    top_k_per_query: int = 12
    final_top_k: int = 10
    score_cutoff: float = 0.22
    evidence_ratio: float = 0.6
    min_queries: int = 3
    max_queries: int = 5
    rrf_k: int = 60
    context_limit: int = 6


def _append_step(
    logs: list[dict[str, Any]],
    *,
    step: int,
    title: str,
    detail: str,
    data: dict[str, Any] | None = None,
) -> None:
    logs.append(
        {
            "step": step,
            "title": title,
            "detail": detail,
            "data": data or {},
        }
    )


def classify_intent(query: str, *, has_history: bool = False) -> str:
    text = (query or "").strip()
    lowered = text.lower()
    if not text:
        return "not_related"
    if any(word in lowered for word in _GREETING_WORDS):
        return "greeting"
    if has_history and lowered.startswith(_FOLLOWUP_PREFIXES):
        return "followup"
    if any(word in lowered for word in _NOT_RELATED_HINTS):
        return "not_related"
    if any(word in lowered for word in _NEW_COMPANY_HINTS):
        return "new_company_query"
    return "general"


def detect_language(query: str) -> str:
    text = (query or "").strip()
    kor_count = len(_KOREAN_RE.findall(text))
    eng_count = len(_ENGLISH_RE.findall(text))
    if kor_count >= eng_count:
        return "ko"
    return "en"


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out


def plan_queries(query: str, *, intent: str, language: str, min_n: int = 3, max_n: int = 5) -> list[str]:
    base = (query or "").strip()
    if not base:
        return []

    variants: list[str] = [base]
    if language == "ko":
        variants.extend(
            [
                f"{base} 관련 전시 참가업체",
                f"{base} 기업 프로필 요약",
                f"{base} 근거 자료",
                f"{base} 부스 위치 및 국가",
            ]
        )
    else:
        variants.extend(
            [
                f"{base} exhibitor profile",
                f"{base} company evidence",
                f"{base} booth location and country",
                f"{base} trade show participant",
            ]
        )

    if intent == "followup":
        if language == "ko":
            variants.append(f"이전 질문 맥락에서 {base} 업체 정보")
        else:
            variants.append(f"in previous context, {base} company details")
    elif intent == "greeting":
        variants.append("전시 참가업체 추천")
    elif intent == "general":
        if language == "ko":
            variants.append(f"{base}와 연관된 업체")
        else:
            variants.append(f"companies related to {base}")

    deduped = _dedupe_keep_order(variants)
    target_n = max(min_n, min(max_n, len(deduped)))
    return deduped[:target_n]


def build_intent_heuristic_answer(*, intent: str, language: str, query: str) -> str:
    q = (query or "").strip()
    if intent == "greeting":
        if language == "ko":
            return (
                "안녕하세요. 전시 참가업체 검색 도우미입니다. "
                "찾고 싶은 제품, 기술, 업체명, 부스 정보 중 하나를 입력해 주세요."
            )
        return (
            "Hello. I am your exhibitor search assistant. "
            "Please tell me a product, technology, company name, or booth detail to search."
        )

    if intent == "not_related":
        if language == "ko":
            return (
                f"입력하신 질문('{q}')은 전시 참가업체 검색 범위와 거리가 있습니다. "
                "업체명, 제품/기술 키워드, 국가, 전시홀, 부스번호 중심으로 다시 질문해 주세요."
            )
        return (
            f"Your query ('{q}') appears to be outside exhibitor search scope. "
            "Please ask with company name, product/technology, country, hall, or booth number."
        )

    return ""


def _normalize_row(row: dict[str, Any], rank: int) -> dict[str, Any]:
    score = row.get("score")
    if not isinstance(score, (int, float)):
        score = 0.0
    distance = row.get("distance")
    if not isinstance(distance, (int, float)):
        distance = 1.0
    return {
        **row,
        "score": float(score),
        "distance": float(distance),
        "rank": rank,
    }


def semantic_search_multi_query(
    *,
    queries: list[str],
    model_id: str,
    device: str | None,
    top_k_per_query: int,
    lang: str,
    evidence_ratio: float,
) -> list[dict[str, Any]]:
    searches: list[dict[str, Any]] = []
    evidence_k = max(1, int(top_k_per_query * evidence_ratio))
    profile_k = max(1, top_k_per_query - evidence_k)

    for q in queries:
        logger.info("[retrieval][step4] semantic_search query=%s", q)
        qvec = embed_query_text(q, model_id=model_id, device=device)
        profile_rows = search_embedding_tables(
            query_embedding=qvec,
            model_id=model_id,
            top_k=profile_k,
            lang=lang,
            chunk_type="profile",
        )
        evidence_rows = search_embedding_tables(
            query_embedding=qvec,
            model_id=model_id,
            top_k=evidence_k,
            lang=lang,
            chunk_type="evidence",
        )
        merged = sorted(profile_rows + evidence_rows, key=lambda x: x.get("distance", 1.0))[:top_k_per_query]
        normalized = [_normalize_row(row, rank=i) for i, row in enumerate(merged, start=1)]
        searches.append({"query": q, "results": normalized})
        logger.info(
            "[retrieval][step4] query=%s profile=%d evidence=%d merged=%d",
            q,
            len(profile_rows),
            len(evidence_rows),
            len(normalized),
        )
    return searches


def rrf_fuse(searches: list[dict[str, Any]], *, rrf_k: int = 60) -> list[dict[str, Any]]:
    fused: dict[str, dict[str, Any]] = {}
    for bucket in searches:
        q = bucket["query"]
        for row in bucket["results"]:
            # Use a stable key per chunk so profile/evidence chunks can co-exist.
            key = "|".join(
                [
                    str(row.get("table_name", "")),
                    str(row.get("exhibitor_id", "")),
                    str(row.get("source_field", "")),
                    str(row.get("chunk_index", "")),
                    str(row.get("content", ""))[:160],
                ]
            )
            base = fused.get(key)
            score_rrf = 1.0 / (rrf_k + int(row.get("rank", 1)))
            if base is None:
                fused[key] = {
                    **row,
                    "rrf_score": score_rrf,
                    "matched_queries": [q],
                    "best_score": float(row.get("score", 0.0)),
                    "best_distance": float(row.get("distance", 1.0)),
                }
            else:
                base["rrf_score"] += score_rrf
                base["matched_queries"].append(q)
                if float(row.get("score", 0.0)) > float(base.get("best_score", 0.0)):
                    base["best_score"] = float(row.get("score", 0.0))
                    base["best_distance"] = float(row.get("distance", 1.0))

    ranked = sorted(
        fused.values(),
        key=lambda x: (float(x.get("rrf_score", 0.0)), float(x.get("best_score", 0.0))),
        reverse=True,
    )
    logger.info("[retrieval][step5] rrf_fused_count=%d", len(ranked))
    return ranked


def apply_cutoff_and_build_context(
    fused_results: list[dict[str, Any]],
    *,
    score_cutoff: float,
    final_top_k: int,
    context_limit: int,
) -> tuple[list[dict[str, Any]], str]:
    filtered = [r for r in fused_results if float(r.get("best_score", 0.0)) >= score_cutoff]
    top = filtered[: max(1, final_top_k)]

    lines: list[str] = []
    for i, row in enumerate(top[:context_limit], start=1):
        content = (row.get("content") or "").strip().replace("\n", " / ")
        if len(content) > 260:
            content = content[:260].rstrip() + "..."
        lines.append(
            f"[{i}] rrf={float(row.get('rrf_score', 0.0)):.4f}, "
            f"score={float(row.get('best_score', 0.0)):.4f}, "
            f"type={row.get('chunk_typ')}, lang={row.get('lang')}, "
            f"external_id={row.get('external_id')}, content={content}"
        )
    context_text = "\n".join(lines)
    logger.info(
        "[retrieval][step6] cutoff=%s kept=%d context_lines=%d",
        score_cutoff,
        len(top),
        len(lines),
    )
    return top, context_text


def execute_retrieval_pipeline(
    query: str,
    *,
    config: RetrievalConfig | None = None,
    has_history: bool = False,
) -> dict[str, Any]:
    cfg = config or RetrievalConfig()
    normalized_query = (query or "").strip()
    if not normalized_query:
        raise ValueError("query is empty")
    step_logs: list[dict[str, Any]] = []

    logger.info("[retrieval][step1] intent classification started")
    intent = classify_intent(normalized_query, has_history=has_history)
    if intent not in INTENT_LABELS:
        intent = "general"
    logger.info("[retrieval][step1] intent=%s", intent)
    _append_step(
        step_logs,
        step=1,
        title="의도 분류",
        detail=f"query 의도를 '{intent}'로 분류",
        data={"intent": intent, "query": normalized_query},
    )

    logger.info("[retrieval][step2] language detection started")
    language = detect_language(normalized_query)
    if language not in LANGUAGE_LABELS:
        language = "ko"
    logger.info("[retrieval][step2] language=%s", language)
    _append_step(
        step_logs,
        step=2,
        title="언어 감지",
        detail=f"입력 언어를 '{language}'로 판정",
        data={"language": language},
    )

    logger.info("[retrieval][step3] query planning started")
    planned_queries = plan_queries(
        normalized_query,
        intent=intent,
        language=language,
        min_n=cfg.min_queries,
        max_n=cfg.max_queries,
    )
    logger.info("[retrieval][step3] planned_queries=%s", planned_queries)
    _append_step(
        step_logs,
        step=3,
        title="쿼리 계획",
        detail=f"{len(planned_queries)}개 집중 쿼리 생성",
        data={"planned_queries": planned_queries},
    )

    if intent in {"greeting", "not_related"}:
        heuristic_answer = build_intent_heuristic_answer(intent=intent, language=language, query=normalized_query)
        _append_step(
            step_logs,
            step=4,
            title="검색 생략",
            detail=f"의도 '{intent}'로 판단되어 다중 쿼리 검색을 수행하지 않음",
            data={"response_mode": "intent_heuristic"},
        )
        return {
            "intent": intent,
            "language": language,
            "planned_queries": [],
            "per_query_results": [],
            "fused_results": [],
            "final_results": [],
            "llm_context": "",
            "step_logs": step_logs,
            "response_mode": "intent_heuristic",
            "heuristic_answer": heuristic_answer,
        }

    search_lang = "kor" if language == "ko" else "eng"
    searches = semantic_search_multi_query(
        queries=planned_queries,
        model_id=cfg.model_id,
        device=cfg.device,
        top_k_per_query=cfg.top_k_per_query,
        lang=search_lang,
        evidence_ratio=cfg.evidence_ratio,
    )
    query_summaries: list[dict[str, Any]] = []
    for bucket in searches:
        rows = bucket["results"]
        query_summaries.append(
            {
                "query": bucket["query"],
                "count": len(rows),
                "top_preview": [r.get("content", "")[:80] for r in rows[:2]],
            }
        )
    _append_step(
        step_logs,
        step=4,
        title="의미 검색",
        detail="쿼리별 profile/evidence 검색 수행",
        data={"query_summaries": query_summaries, "search_lang": search_lang},
    )

    fused = rrf_fuse(searches, rrf_k=cfg.rrf_k)
    _append_step(
        step_logs,
        step=5,
        title="다중 쿼리 융합 (RRF)",
        detail=f"RRF로 {len(fused)}개 후보 생성",
        data={"rrf_k": cfg.rrf_k, "fused_count": len(fused)},
    )
    final_results, llm_context = apply_cutoff_and_build_context(
        fused,
        score_cutoff=cfg.score_cutoff,
        final_top_k=cfg.final_top_k,
        context_limit=cfg.context_limit,
    )
    _append_step(
        step_logs,
        step=6,
        title="컷오프 + 컨텍스트 조립",
        detail=f"score_cutoff={cfg.score_cutoff} 적용 후 {len(final_results)}개 결과 유지",
        data={
            "score_cutoff": cfg.score_cutoff,
            "final_count": len(final_results),
            "context_limit": cfg.context_limit,
        },
    )

    return {
        "intent": intent,
        "language": language,
        "planned_queries": planned_queries,
        "per_query_results": searches,
        "fused_results": fused,
        "final_results": final_results,
        "llm_context": llm_context,
        "step_logs": step_logs,
        "response_mode": "retrieval",
        "heuristic_answer": "",
    }
