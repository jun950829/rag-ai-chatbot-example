from __future__ import annotations

import logging
from typing import Any

from app.rag.pipeline import embed_query_text, search_embedding_tables

logger = logging.getLogger(__name__)


def _normalize_row(row: dict[str, Any], rank: int) -> dict[str, Any]:
    score = row.get("score")
    if not isinstance(score, (int, float)):
        score = 0.0
    distance = row.get("distance")
    if not isinstance(distance, (int, float)):
        distance = 1.0
    return {**row, "score": float(score), "distance": float(distance), "rank": rank}


def semantic_search_multi_query(
    *,
    queries: list[str],
    model_id: str,
    device: str | None,
    top_k_per_query: int,
    lang: str,
    evidence_ratio: float,
    embedding_remote_base_url: str | None = None,
    entity_scope: str = "all",
) -> list[dict[str, Any]]:
    searches: list[dict[str, Any]] = []
    evidence_k = max(1, int(top_k_per_query * evidence_ratio))
    profile_k = max(1, top_k_per_query - evidence_k)
    for q in queries:
        logger.info("[retrieval][step4] semantic_search query=%s", q)
        qvec = embed_query_text(q, model_id=model_id, device=device, remote_base_url=embedding_remote_base_url)
        profile_rows = search_embedding_tables(
            query_embedding=qvec,
            model_id=model_id,
            top_k=profile_k,
            lang=lang,
            chunk_type="profile",
            entity_scope=entity_scope,
        )
        evidence_rows = search_embedding_tables(
            query_embedding=qvec,
            model_id=model_id,
            top_k=evidence_k,
            lang=lang,
            chunk_type="evidence",
            entity_scope=entity_scope,
        )
        merged = sorted(profile_rows + evidence_rows, key=lambda x: x.get("distance", 1.0))[:top_k_per_query]
        normalized = [_normalize_row(row, rank=i) for i, row in enumerate(merged, start=1)]
        searches.append({"query": q, "results": normalized})
        logger.info("[retrieval][step4] query=%s profile=%d evidence=%d merged=%d", q, len(profile_rows), len(evidence_rows), len(normalized))
    return searches


def rrf_fuse(searches: list[dict[str, Any]], *, rrf_k: int = 60) -> list[dict[str, Any]]:
    fused: dict[str, dict[str, Any]] = {}
    for bucket in searches:
        q = bucket["query"]
        for row in bucket["results"]:
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
    ranked = sorted(fused.values(), key=lambda x: (float(x.get("rrf_score", 0.0)), float(x.get("best_score", 0.0))), reverse=True)
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
    logger.info("[retrieval][step6] cutoff=%s kept=%d context_lines=%d", score_cutoff, len(top), len(lines))
    return top, context_text

