"""new_main retrieval 단계 구현 (원 프로젝트의 semantic+RRF+cutoff를 포팅)."""

from __future__ import annotations

import asyncio
from typing import Any

from app.retrieval.embedding_client import embed_queries_text, embed_queries_text_async
from app.retrieval.vector_db import search_embedding_tables

# LLM 컨텍스트 한 블록당 본문 상한 (기존 260은 제품 소개가 잘리며 답변이 '-' 로만 채워지기 쉬움)
CONTEXT_ITEM_MAX_CHARS = 4000


def _normalize_row(row: dict[str, Any], rank: int) -> dict[str, Any]:
    score = row.get("score")
    if not isinstance(score, (int, float)):
        score = 0.0
    distance = row.get("distance")
    if not isinstance(distance, (int, float)):
        distance = 1.0
    return {**row, "score": float(score), "distance": float(distance), "rank": rank}


def _vector_buckets_after_embed(
    *,
    normalized: list[str],
    idx_nonempty: list[int],
    vec_list: list[list[float]],
    model_id: str,
    top_k_per_query: int,
    lang: str,
    evidence_ratio: float,
    entity_scope: str,
) -> list[dict[str, Any]]:
    evidence_k = max(1, int(top_k_per_query * evidence_ratio))
    profile_k = max(1, top_k_per_query - evidence_k)
    non_empty_buckets: list[dict[str, Any]] = []
    for j, i in enumerate(idx_nonempty):
        q = normalized[i]
        qvec = vec_list[j]
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
        non_empty_buckets.append({"query": q, "results": [_normalize_row(r, rank=k) for k, r in enumerate(merged, 1)]})

    it = iter(non_empty_buckets)
    out: list[dict[str, Any]] = []
    for q in normalized:
        if not q.strip():
            out.append({"query": q, "results": []})
        else:
            out.append(next(it))
    return out


def semantic_search_multi_query(
    *,
    queries: list[str],
    model_id: str,
    device: str | None,
    top_k_per_query: int,
    lang: str,
    evidence_ratio: float,
    embedding_remote_base_url: str | None,
    entity_scope: str = "all",
) -> list[dict[str, Any]]:
    if not queries:
        return []
    normalized = [str(q or "") for q in queries]
    idx_nonempty = [i for i, q in enumerate(normalized) if q.strip()]
    if not idx_nonempty:
        return [{"query": q, "results": []} for q in normalized]

    texts = [normalized[i] for i in idx_nonempty]
    vec_list = embed_queries_text(texts, model_id=model_id, device=device, remote_base_url=embedding_remote_base_url)
    return _vector_buckets_after_embed(
        normalized=normalized,
        idx_nonempty=idx_nonempty,
        vec_list=vec_list,
        model_id=model_id,
        top_k_per_query=top_k_per_query,
        lang=lang,
        evidence_ratio=evidence_ratio,
        entity_scope=entity_scope,
    )


async def semantic_search_multi_query_async(
    *,
    queries: list[str],
    model_id: str,
    device: str | None,
    top_k_per_query: int,
    lang: str,
    evidence_ratio: float,
    embedding_remote_base_url: str | None,
    entity_scope: str = "all",
) -> list[dict[str, Any]]:
    """임베딩은 httpx 비동기, pgvector 조회는 동기라 스레드에서 실행해 이벤트 루프를 막지 않는다."""
    if not queries:
        return []
    normalized = [str(q or "") for q in queries]
    idx_nonempty = [i for i, q in enumerate(normalized) if q.strip()]
    if not idx_nonempty:
        return [{"query": q, "results": []} for q in normalized]

    texts = [normalized[i] for i in idx_nonempty]
    vec_list = await embed_queries_text_async(
        texts, model_id=model_id, device=device, remote_base_url=embedding_remote_base_url
    )
    return await asyncio.to_thread(
        _vector_buckets_after_embed,
        normalized=normalized,
        idx_nonempty=idx_nonempty,
        vec_list=vec_list,
        model_id=model_id,
        top_k_per_query=top_k_per_query,
        lang=lang,
        evidence_ratio=evidence_ratio,
        entity_scope=entity_scope,
    )


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
    return sorted(
        fused.values(),
        key=lambda x: (float(x.get("rrf_score", 0.0)), float(x.get("best_score", 0.0))),
        reverse=True,
    )


def merge_fused_rows_by_external_id(rows: list[dict[str, Any]], *, max_chunks_per_entity: int = 12) -> list[dict[str, Any]]:
    """같은 external_id(같은 제품/업체)의 profile·evidence 청크 본문을 한 블록으로 합친다."""
    order_keys: list[str] = []
    buckets: dict[str, list[dict[str, Any]]] = {}
    for idx, r in enumerate(rows):
        ext = str(r.get("external_id") or "").strip()
        if not ext:
            # external_id 없으면 행마다 분리 (잘못된 병합 방지)
            ext = f"__row_{idx}"
        key = f"{str(r.get('table_name') or '')}|{ext}"
        if key not in buckets:
            order_keys.append(key)
            buckets[key] = []
        if len(buckets[key]) < max_chunks_per_entity:
            buckets[key].append(r)

    merged: list[dict[str, Any]] = []
    for key in order_keys:
        grp = buckets.get(key) or []
        if not grp:
            continue
        base = dict(grp[0])
        texts: list[str] = []
        seen: set[str] = set()
        for g in grp:
            t = (g.get("content") or "").strip()
            if t and t not in seen:
                seen.add(t)
                texts.append(t)
        base["content"] = "\n\n".join(texts)
        base["rrf_score"] = sum(float(x.get("rrf_score") or 0.0) for x in grp)
        base["best_score"] = max(float(x.get("best_score") or 0.0) for x in grp)
        typs = sorted({str(x.get("chunk_typ") or "") for x in grp if x.get("chunk_typ")})
        if typs:
            base["chunk_typ"] = ",".join(typs)
        merged.append(base)
    return merged


def select_rows_for_suggestion_cards(
    fused_results: list[dict[str, Any]],
    *,
    score_cutoff: float,
    final_top_k: int,
    max_raw_chunks: int = 16,
) -> list[dict[str, Any]]:
    """병합 전 RRF 정렬 행 — 캐러셀용. merge 시 청크가 묶이며 줄어드는 문제를 피한다."""
    filtered = [r for r in fused_results if float(r.get("best_score", 0.0)) >= score_cutoff]
    if not filtered:
        return []
    limit = min(len(filtered), max(max_raw_chunks, final_top_k, 8))
    return filtered[:limit]


def apply_cutoff_and_build_context(
    fused_results: list[dict[str, Any]],
    *,
    score_cutoff: float,
    final_top_k: int,
    context_limit: int,
) -> tuple[list[dict[str, Any]], str]:
    filtered = [r for r in fused_results if float(r.get("best_score", 0.0)) >= score_cutoff]
    top = filtered[: max(1, final_top_k)]
    merged_top = merge_fused_rows_by_external_id(top)
    lines: list[str] = []
    for i, row in enumerate(merged_top[:context_limit], start=1):
        content = (row.get("content") or "").strip().replace("\n", " / ")
        if len(content) > CONTEXT_ITEM_MAX_CHARS:
            content = content[:CONTEXT_ITEM_MAX_CHARS].rstrip() + "..."
        lines.append(
            f"[{i}] rrf={float(row.get('rrf_score', 0.0)):.4f}, "
            f"score={float(row.get('best_score', 0.0)):.4f}, "
            f"type={row.get('chunk_typ')}, lang={row.get('lang')}, "
            f"source_field={row.get('source_field')}, external_id={row.get('external_id')}, content={content}"
        )
    return merged_top[:context_limit], "\n".join(lines)
