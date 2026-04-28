from __future__ import annotations

from typing import Any

from app.rag.retrieval.intent import _intent_meta_used_openai


def append_step(
    logs: list[dict[str, Any]],
    *,
    step: int,
    title: str,
    detail: str,
    data: dict[str, Any] | None = None,
) -> None:
    logs.append({"step": step, "title": title, "detail": detail, "data": data or {}})


def build_openai_usage_summary(
    *,
    intent_meta: dict[str, Any],
    planning_meta: dict[str, Any],
    vector_search_ran: bool,
    openai_client_present: bool,
) -> dict[str, Any]:
    intent_src = str(intent_meta.get("source", ""))
    intent_used_openai = _intent_meta_used_openai(intent_meta)
    pm = planning_meta.get("planner_meta") or {}
    planner_src = str(pm.get("source", ""))
    skipped = bool(planning_meta.get("skipped"))

    if skipped or planner_src.startswith("skipped_"):
        query_plan_called = False
        query_plan_ok = False
        eff_planner_src = planner_src or "skipped_non_search_intent"
    elif not openai_client_present:
        query_plan_called = False
        query_plan_ok = False
        eff_planner_src = "no_openai_client"
    else:
        query_plan_called = planner_src in {"llm_query_planner", "llm_query_planner_error"}
        query_plan_ok = planner_src == "llm_query_planner"
        eff_planner_src = planner_src or "unknown"

    notes_parts: list[str] = []
    notes_parts.append("의도 분류에 OpenAI 사용" if intent_used_openai else "의도 분류는 휴리스틱/규칙 기반")
    if skipped or eff_planner_src.startswith("skipped"):
        notes_parts.append("쿼리 플래너 미호출(비검색 의도)")
    elif query_plan_ok:
        notes_parts.append("쿼리 변형 생성에 OpenAI 사용")
    elif query_plan_called:
        notes_parts.append("쿼리 플래너 호출했으나 오류·파싱 실패 가능")
    elif not openai_client_present:
        notes_parts.append("API 키 없음으로 쿼리 플래너 미사용")
    else:
        notes_parts.append("쿼리 플래너 미사용")
    notes_parts.append("벡터(임베딩) 검색 수행" if vector_search_ran else "벡터 검색 생략")

    return {
        "openai_client_configured": openai_client_present,
        "intent_classification_used_openai": intent_used_openai,
        "intent_classification_source": intent_src,
        "query_planning_called_openai": query_plan_called,
        "query_planning_succeeded": query_plan_ok,
        "query_planning_source": eff_planner_src,
        "vector_search_ran": vector_search_ran,
        "notes_ko": " · ".join(notes_parts),
    }

