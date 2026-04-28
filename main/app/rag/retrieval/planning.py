from __future__ import annotations

from typing import Any

from app.rag.retrieval.intent import _dedupe_keep_order, _is_informative_query, _norm_text, _strip_request_scaffolding


async def generate_search_plan_v2(
    *,
    message: str,
    language: str,
    intent: str,
    openai_client: Any | None,
    openai_model: str,
    min_queries: int,
    max_queries: int,
) -> tuple[list[str], dict[str, Any]]:
    del openai_client, openai_model
    raw = _norm_text(message)
    cleaned = _strip_request_scaffolding(raw)
    base_queries = [cleaned, raw]
    if intent == "followup":
        base_queries.append(f"{cleaned} 이전 질문 맥락")
        base_queries.append(f"{cleaned} company detail")
        base_queries.append(f"{cleaned} exhibitor info")
        base_queries.append(f"{cleaned} product detail")
        base_queries.append(f"{cleaned} exhibit item info")
    if intent == "company":
        base_queries.append(f"{cleaned} exhibitor")
        base_queries.append(f"{cleaned} company profile")
    if intent == "product":
        base_queries.append(f"{cleaned} exhibit item")
        base_queries.append(f"{cleaned} product spec")
    if language == "ko":
        if intent == "product":
            base_queries.append(f"{cleaned} 전시품")
            base_queries.append(f"{cleaned} 제품")
        else:
            base_queries.append(f"{cleaned} 참가업체")
            base_queries.append(f"{cleaned} 업체 프로필")
    else:
        base_queries.append(f"{cleaned} exhibition")
    base_queries = [q for q in _dedupe_keep_order(base_queries) if _is_informative_query(q)]
    merged = _dedupe_keep_order(base_queries)
    target_n = max(min_queries, min(max_queries, len(merged)))
    return merged[:target_n], {
        "raw_query": raw,
        "cleaned_query": cleaned,
        "base_queries": base_queries,
        "llm_queries": [],
        "planner_meta": {"source": "heuristic_query_planner"},
    }

