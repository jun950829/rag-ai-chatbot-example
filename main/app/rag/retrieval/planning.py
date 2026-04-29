from __future__ import annotations

from typing import Any

from app.rag.retrieval.intent import _dedupe_keep_order, _is_informative_query, _norm_text, _strip_request_scaffolding


async def generate_search_plan_v2(
    *,
    message: str,
    language: str,
    intent: str,
    retrieval_topic: str,
    is_dialog_followup: bool,
    openai_client: Any | None,
    openai_model: str,
    min_queries: int,
    max_queries: int,
) -> tuple[list[str], dict[str, Any]]:
    """--- 단계: 다중 임베딩 검색용 쿼리 문자열 목록을 만든다.

    - ``intent``: 라우팅 라벨(followup/company/product 등). 플래너 확장 분기 참고용.
    - ``retrieval_topic``: 실제 검색 축(회사/제품/전체). follow-up이어도 제품이면 product 확장을 탄다.
    - ``is_dialog_followup``: 직전 맥락을 덧붙이는 보조 쿼리를 넣을지 여부.
    """
    del openai_client, openai_model
    raw = _norm_text(message)
    cleaned = _strip_request_scaffolding(raw)
    base_queries = [cleaned, raw]

    # --- 단계 A: 후행 질문이면 맥락·회사·제품 보조 문구를 한꺼번에 붙인다 (기존 followup 동작 유지) ---
    if is_dialog_followup or intent == "followup":
        base_queries.append(f"{cleaned} 이전 질문 맥락")
        base_queries.append(f"{cleaned} company detail")
        base_queries.append(f"{cleaned} exhibitor info")
        base_queries.append(f"{cleaned} product detail")
        base_queries.append(f"{cleaned} exhibit item info")

    # --- 단계 A-2: 후행 + 검색축이 product일 때 전시품 쪽 쿼리를 추가로 깊게 펼친다 ---
    # (이유: 단계 A만으로는 회사/제품이 섞여 RRF에서 제품 테이블 신호가 약해질 수 있음)
    if is_dialog_followup and retrieval_topic == "product":
        base_queries.append(f"{cleaned} 대표 제품")
        base_queries.append(f"{cleaned} 주력 제품")
        base_queries.append(f"{cleaned} 전시품 목록")
        base_queries.append(f"{cleaned} exhibit item specification")
        base_queries.append(f"{cleaned} featured product booth")

    # --- 단계 B: 검색 축(retrieval_topic)에 따른 확장 — follow-up + 제품 조합에서 핵심 ---
    if retrieval_topic == "company":
        base_queries.append(f"{cleaned} exhibitor")
        base_queries.append(f"{cleaned} company profile")
    if retrieval_topic == "product":
        base_queries.append(f"{cleaned} exhibit item")
        base_queries.append(f"{cleaned} product spec")

    # --- 단계 C: 언어별 일반 확장 (topic이 all이면 회사·제품 양쪽 힌트를 섞는다) ---
    if language == "ko":
        if retrieval_topic == "product":
            base_queries.append(f"{cleaned} 전시품")
            base_queries.append(f"{cleaned} 제품")
        elif retrieval_topic == "company":
            base_queries.append(f"{cleaned} 참가업체")
            base_queries.append(f"{cleaned} 업체 프로필")
        else:
            base_queries.append(f"{cleaned} 참가업체")
            base_queries.append(f"{cleaned} 업체 프로필")
            base_queries.append(f"{cleaned} 전시품")
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
        "retrieval_topic": retrieval_topic,
        "is_dialog_followup": is_dialog_followup,
    }
