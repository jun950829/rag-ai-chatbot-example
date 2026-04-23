from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from app.rag.pipeline import (
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
_PRODUCT_HINTS = (
    "x-ray",
    "ct",
    "mri",
    "초음파",
    "혈압",
    "진단",
    "monitor",
    "imaging",
    "device",
    "equipment",
)
_LOGISTICS_HINTS = (
    "일정",
    "시간",
    "장소",
    "입장",
    "등록",
    "주차",
    "date",
    "schedule",
    "location",
    "ticket",
    "registration",
)
_EXPO_DOMAIN_HINTS = (
    "전시",
    "참가업체",
    "업체",
    "회사",
    "기업",
    "부스",
    "전시홀",
    "exhibitor",
    "booth",
    "hall",
    "company",
    "profile",
    "catalog",
)
_OUT_OF_SCOPE_HINTS = (
    "배가 아프",
    "배고프",
    "아플까",
    "hungry",
    "stomach",
    "headache",
    "연애",
    "운세",
    "점",
)
_GENERIC_REQUEST_PATTERNS = (
    r"\bshow\b",
    r"\bshow me\b",
    r"\bfind\b",
    r"\blist\b",
    r"\brecommend\b",
    r"\bdetails?\b",
    r"\babout\b",
    r"보여\s*줘",
    r"알려\s*줘",
    r"추천\s*해\s*줘",
    r"찾아\s*줘",
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


def _build_openai_usage_summary(
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
    if intent_used_openai:
        notes_parts.append("의도 분류에 OpenAI 사용")
    else:
        notes_parts.append("의도 분류는 휴리스틱/규칙 기반")
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
    if vector_search_ran:
        notes_parts.append("벡터(임베딩) 검색 수행")
    else:
        notes_parts.append("벡터 검색 생략")

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


def _intent_meta_used_openai(intent_meta: dict[str, Any]) -> bool:
    src = str(intent_meta.get("source", ""))
    if src.startswith("llm_") or src.endswith("_by_llm") or "_llm_" in src:
        return True
    return bool(intent_meta.get("openai_checked_before_not_related"))


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


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _looks_like_greeting(text: str) -> bool:
    return any(word in text for word in _GREETING_WORDS)


def _looks_like_followup(text: str, has_history: bool) -> bool:
    return has_history and text.startswith(_FOLLOWUP_PREFIXES)


def _contains_company_question_pattern(text: str) -> bool:
    return bool(re.search(r"(업체|회사|기업|company|exhibitor).*(추천|찾|어디|who|which|find)", text))


def _has_product_keyword(text: str) -> bool:
    return any(word in text for word in _PRODUCT_HINTS)


def _has_product_category_reference(text: str) -> bool:
    return bool(re.search(r"(의료기기|헬스케어|진단기기|medical|healthcare|diagnostic)", text))


def _has_company_keyword(text: str) -> bool:
    return any(word in text for word in _NEW_COMPANY_HINTS)


def _has_company_name_suffix(text: str) -> bool:
    return bool(re.search(r"\b(inc|corp|co\.|ltd|llc|주식회사)\b", text))


def _looks_like_general_logistics(text: str) -> bool:
    return any(word in text for word in _LOGISTICS_HINTS)


def _looks_out_of_scope(text: str) -> bool:
    return any(word in text for word in _OUT_OF_SCOPE_HINTS)


def _has_expo_domain_signal(text: str) -> bool:
    if _has_company_keyword(text) or _has_product_keyword(text) or _has_product_category_reference(text):
        return True
    return any(word in text for word in _EXPO_DOMAIN_HINTS)


def _safe_default(text: str) -> str:
    if _looks_like_general_logistics(text):
        return "general"
    if _looks_out_of_scope(text):
        return "not_related"
    # If domain signal is weak but not clearly out-of-scope, prefer general.
    if not _has_expo_domain_signal(text):
        return "general"
    return "general"


def _extract_label(raw: str) -> str | None:
    candidate = (raw or "").strip().lower()
    if candidate in INTENT_LABELS:
        return candidate
    for token in re.split(r"[^a-z_]+", candidate):
        if token in INTENT_LABELS:
            return token
    return None


CLASSIFICATION_SYSTEM = (
    "Classify user intent into exactly one label from: "
    "greeting, followup, new_company_query, general, not_related. "
    "Return only the label."
)


async def classify_intent_v2(
    *,
    message: str,
    has_history: bool,
    openai_client: Any | None,
    model: str = "gpt-4o-mini",
) -> tuple[str, dict[str, Any]]:
    n = _norm_text(message)

    # 0) Fast paths
    if _looks_like_greeting(n):
        return "greeting", {"source": "heuristic_fast_path"}
    if _looks_like_followup(n, has_history):
        return "followup", {"source": "heuristic_fast_path"}

    # 1) Strong heuristic signals
    if _contains_company_question_pattern(n):
        return "new_company_query", {"source": "heuristic_strong_signal", "signal": "company_question_pattern"}
    if _has_product_keyword(n) or _has_product_category_reference(n):
        return "new_company_query", {"source": "heuristic_strong_signal", "signal": "product_keyword"}
    if _has_company_keyword(n) or _has_company_name_suffix(n):
        return "new_company_query", {"source": "heuristic_strong_signal", "signal": "company_keyword"}

    # 2) Heuristic default branch
    heuristic_intent = "general"
    heuristic_source = "heuristic_general_default"
    if _looks_like_general_logistics(n):
        heuristic_intent = "general"
        heuristic_source = "heuristic_logistics"
    elif _looks_out_of_scope(n):
        heuristic_intent = "not_related"
        heuristic_source = "heuristic_out_of_scope"
    elif any(word in n for word in _NOT_RELATED_HINTS):
        heuristic_intent = "not_related"
        heuristic_source = "heuristic_not_related"
    elif not _has_expo_domain_signal(n):
        heuristic_intent = "general"
        heuristic_source = "heuristic_no_domain_signal"

    # 3) Requested flow: if heuristic says general/not_related, verify once with OpenAI.
    if heuristic_intent in {"general", "not_related"}:
        if openai_client is None:
            return heuristic_intent, {
                "source": heuristic_source,
                "openai_checked_before_not_related": False,
            }
        try:
            resp = await openai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": CLASSIFICATION_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            "The heuristic classifier predicted one of {general, not_related}.\n"
                            f"Heuristic prediction: {heuristic_intent} ({heuristic_source})\n"
                            f"Message: <<<{message}>>>\n"
                            "Re-classify strictly with one label only."
                        ),
                    },
                ],
            )
            content = ((resp.choices[0].message.content) or "").strip()
            intent = _extract_label(content) or heuristic_intent
            if intent in {"general", "not_related"}:
                return intent, {
                    "source": "general_or_not_related_verified_by_llm",
                    "heuristic_intent": heuristic_intent,
                    "heuristic_source": heuristic_source,
                    "llm_raw": content,
                    "openai_checked_before_not_related": True,
                }
            return intent, {
                "source": "general_or_not_related_overruled_by_llm",
                "heuristic_intent": heuristic_intent,
                "heuristic_source": heuristic_source,
                "llm_raw": content,
                "openai_checked_before_not_related": True,
            }
        except Exception as exc:
            return heuristic_intent, {
                "source": "general_or_not_related_verification_exception_fallback",
                "heuristic_intent": heuristic_intent,
                "heuristic_source": heuristic_source,
                "error": str(exc),
                "openai_checked_before_not_related": True,
            }

    # 4) LLM fallback (defensive; currently unreachable due branching above)
    if openai_client is None:
        return _safe_default(n), {"source": "safe_default_no_openai"}
    try:
        resp = await openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": CLASSIFICATION_SYSTEM},
                {"role": "user", "content": f"<<<{message}>>>"},
            ],
        )
        content = ((resp.choices[0].message.content) or "").strip()
        intent = _extract_label(content)
        if intent == "general" and (_has_product_keyword(n) or _has_company_keyword(n)):
            return "new_company_query", {"source": "llm_fallback_overruled", "llm_raw": content}
        if intent == "general" and not _has_expo_domain_signal(n):
            return "not_related", {"source": "llm_fallback_overruled_no_domain", "llm_raw": content}
        return (intent or _safe_default(n)), {"source": "llm_fallback", "llm_raw": content}
    except Exception as exc:
        return _safe_default(n), {"source": "safe_default_exception", "error": str(exc)}


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


def _strip_request_scaffolding(raw: str) -> str:
    text = _norm_text(raw)
    for pattern in _GENERIC_REQUEST_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    # Remove very generic target words to keep semantic core.
    text = re.sub(r"\b(회사|업체|기업|company|product|제품)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_informative_query(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 2:
        return False
    return bool(_KOREAN_RE.search(t) or _ENGLISH_RE.search(t))


SEARCH_PLAN_SYSTEM = (
    "You generate retrieval queries for an exhibitor catalog search system. "
    "Return strict JSON only with keys: mode, queries. "
    "mode must be one of company, product, both. "
    "queries must be up to max_queries items, each 3-12 words."
)


async def _generate_llm_query_variants(
    *,
    openai_client: Any | None,
    model: str,
    user_message: str,
    cleaned_query: str,
    language: str,
    max_queries: int,
) -> tuple[list[str], dict[str, Any]]:
    if openai_client is None:
        return [], {"source": "no_openai_client"}
    prompt = (
        "User message: "
        f"\"{user_message}\"\n"
        f"Cleaned query: \"{cleaned_query}\"\n"
        f"Detected language: {language}\n\n"
        "Rules:\n"
        "- First query must be cleaned query.\n"
        "- If booth/exhibitor/company intent appears use mode=company.\n"
        "- If product/device/technology intent appears use mode=product.\n"
        "- If unclear use mode=both.\n"
        "- Include at least one Korean and one English query variant when possible.\n"
        f"- Return up to {max_queries} queries.\n"
    )
    try:
        resp = await openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SEARCH_PLAN_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        raw = ((resp.choices[0].message.content) or "").strip()
        # Minimal safe parsing using regex to keep dependencies unchanged.
        quoted = re.findall(r"\"([^\"]+)\"", raw)
        # Extract only plausible query strings.
        candidates = [q for q in quoted if _is_informative_query(q) and len(q.split()) <= 12]
        return _dedupe_keep_order(candidates)[:max_queries], {"source": "llm_query_planner", "raw": raw}
    except Exception as exc:
        return [], {"source": "llm_query_planner_error", "error": str(exc)}


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
    raw = _norm_text(message)
    cleaned = _strip_request_scaffolding(raw)

    base_queries = [cleaned, raw]
    if intent == "followup":
        base_queries.append(f"{cleaned} 이전 질문 맥락")
    if language == "ko":
        base_queries.append(f"{cleaned} exhibitor profile")
    else:
        base_queries.append(f"{cleaned} 전시 참가업체")

    base_queries = [q for q in _dedupe_keep_order(base_queries) if _is_informative_query(q)]
    llm_queries, planner_meta = await _generate_llm_query_variants(
        openai_client=openai_client,
        model=openai_model,
        user_message=message,
        cleaned_query=cleaned or raw,
        language=language,
        max_queries=max_queries,
    )
    merged = _dedupe_keep_order(base_queries + llm_queries)
    target_n = max(min_queries, min(max_queries, len(merged)))
    return merged[:target_n], {
        "raw_query": raw,
        "cleaned_query": cleaned,
        "base_queries": base_queries,
        "llm_queries": llm_queries,
        "planner_meta": planner_meta,
    }


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

    if intent == "general":
        if language == "ko":
            return (
                "테스트/일반 대화로 이해했습니다. "
                "업체 검색을 원하면 제품/기술 키워드나 업체명, 부스 정보로 질문해 주세요."
            )
        return (
            "I understood this as a general conversation message. "
            "If you want exhibitor search, please include product keyword, company name, or booth detail."
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
    embedding_remote_base_url: str | None = None,
) -> list[dict[str, Any]]:
    searches: list[dict[str, Any]] = []
    evidence_k = max(1, int(top_k_per_query * evidence_ratio))
    profile_k = max(1, top_k_per_query - evidence_k)

    for q in queries:
        logger.info("[retrieval][step4] semantic_search query=%s", q)
        qvec = embed_query_text(
            q,
            model_id=model_id,
            device=device,
            remote_base_url=embedding_remote_base_url,
        )
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


async def execute_retrieval_pipeline(
    query: str,
    *,
    config: RetrievalConfig | None = None,
    has_history: bool = False,
    openai_client: Any | None = None,
    intent_model: str = "gpt-4o-mini",
    embedding_remote_base_url: str | None = None,
) -> dict[str, Any]:
    cfg = config or RetrievalConfig()
    normalized_query = (query or "").strip()
    if not normalized_query:
        raise ValueError("query is empty")
    step_logs: list[dict[str, Any]] = []

    logger.info("[retrieval][step1] intent classification started")
    intent, intent_meta = await classify_intent_v2(
        message=normalized_query,
        has_history=has_history,
        openai_client=openai_client,
        model=intent_model,
    )
    if intent not in INTENT_LABELS:
        intent = "general"
    logger.info("[retrieval][step1] intent=%s", intent)
    classification_source = str(intent_meta.get("source", "unknown"))
    used_openai = _intent_meta_used_openai(intent_meta)
    classification_path_text = "OpenAI 기반 분류" if used_openai else "휴리스틱 분류"
    _append_step(
        step_logs,
        step=1,
        title="의도 분류",
        detail=(
            f"query 의도를 '{intent}'로 분류 "
            f"(분류 경로: {classification_path_text}, source={classification_source})"
        ),
        data={
            "intent": intent,
            "query": normalized_query,
            "classification_meta": intent_meta,
            "openai_used_for_intent": used_openai,
            "intent_model": intent_model if openai_client is not None else None,
        },
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

    openai_present = openai_client is not None
    logger.info("[retrieval][step3] query planning started")
    if intent in {"greeting", "not_related", "general"}:
        raw_norm = _norm_text(normalized_query)
        cleaned = _strip_request_scaffolding(raw_norm)
        planning_meta = {
            "skipped": True,
            "skip_reason": "non_search_intent",
            "planner_meta": {"source": "skipped_non_search_intent"},
            "raw_query": raw_norm,
            "cleaned_query": cleaned,
            "base_queries": [],
            "llm_queries": [],
        }
        planned_queries: list[str] = []
        logger.info("[retrieval][step3] query planning skipped intent=%s", intent)
        _append_step(
            step_logs,
            step=3,
            title="쿼리 계획 생략",
            detail="비검색 의도로 OpenAI 쿼리 플래너·다중 쿼리 생성을 건너뜀",
            data={
                "skipped": True,
                "intent": intent,
                "query_planner_meta": planning_meta["planner_meta"],
            },
        )
    else:
        planned_queries, planning_meta = await generate_search_plan_v2(
            message=normalized_query,
            language=language,
            intent=intent,
            openai_client=openai_client,
            openai_model=intent_model,
            min_queries=cfg.min_queries,
            max_queries=cfg.max_queries,
        )
        logger.info("[retrieval][step3] planned_queries=%s", planned_queries)
        planner_src = str((planning_meta.get("planner_meta") or {}).get("source", ""))
        _append_step(
            step_logs,
            step=3,
            title="쿼리 계획",
            detail=f"{len(planned_queries)}개 집중 쿼리 생성",
            data={
                "planned_queries": planned_queries,
                "cleaned_query": planning_meta.get("cleaned_query", ""),
                "base_queries": planning_meta.get("base_queries", []),
                "llm_queries": planning_meta.get("llm_queries", []),
                "openai_used_for_query_planning": planner_src == "llm_query_planner",
                "query_planner_meta": planning_meta.get("planner_meta", {}),
            },
        )

    if intent in {"greeting", "not_related", "general"}:
        heuristic_answer = build_intent_heuristic_answer(intent=intent, language=language, query=normalized_query)
        _append_step(
            step_logs,
            step=4,
            title="검색 생략",
            detail=f"의도 '{intent}'로 판단되어 다중 쿼리 검색을 수행하지 않음",
            data={"response_mode": "intent_heuristic"},
        )
        openai_usage_summary = _build_openai_usage_summary(
            intent_meta=intent_meta,
            planning_meta=planning_meta,
            vector_search_ran=False,
            openai_client_present=openai_present,
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
            "response_mode": "general_chat" if intent == "general" else "intent_heuristic",
            "heuristic_answer": heuristic_answer,
            "openai_usage_summary": openai_usage_summary,
        }

    search_lang = "kor" if language == "ko" else "eng"
    searches = semantic_search_multi_query(
        queries=planned_queries,
        model_id=cfg.model_id,
        device=cfg.device,
        top_k_per_query=cfg.top_k_per_query,
        lang=search_lang,
        evidence_ratio=cfg.evidence_ratio,
        embedding_remote_base_url=embedding_remote_base_url,
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

    openai_usage_summary = _build_openai_usage_summary(
        intent_meta=intent_meta,
        planning_meta=planning_meta,
        vector_search_ran=True,
        openai_client_present=openai_present,
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
        "openai_usage_summary": openai_usage_summary,
    }
