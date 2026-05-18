"""벡터 검색 파이프라인 — 입력 검증·질의 정규화·OpenAI 클라이언트."""

from __future__ import annotations

import re
from typing import Any

from openai import AsyncOpenAI

from app.rag.retrieval.intent import detect_language

_EXTERNAL_ID_MARKER_RE = re.compile(r"\(\s*external_id\s*:\s*([^)]+?)\s*\)", re.IGNORECASE)
_DL_LANG_STRIP_KO_TAIL_RE = re.compile(
    r"[,.]?\s*("
    r"에\s*대한\s*정보를\s*알려\s*줘|"
    r"에\s*대해\s*알려\s*줘|"
    r"에\s*대해\s*자세히\s*알려\s*줘|"
    r"에\s*대한\s*자세한\s*정보를\s*알려\s*줘|"
    r"자세히\s*알려\s*줘|"
    r"자세히\s*보기"
    r")\s*\Z",
    re.IGNORECASE,
)


def validate_vector_search_inputs(*, chunk_type: str, answer_mode: str) -> None:
    if chunk_type not in {"all", "profile", "evidence"}:
        raise ValueError("chunk_type must be one of: all, profile, evidence")
    if answer_mode not in {"template", "openai"}:
        raise ValueError("answer_mode must be one of: template, openai")


def _norm_payload_language(raw: Any) -> str | None:
    s = str(raw or "").strip().lower()
    if s in {"en", "english"}:
        return "en"
    if s in {"ko", "korean", "kr"}:
        return "ko"
    return None


def _text_for_answer_language_detection(query: str) -> str:
    t = str(query or "").strip()
    t = _DL_LANG_STRIP_KO_TAIL_RE.sub("", t).strip()
    return t


def resolve_answer_language_for_direct_lookup(query: str, payload_lang: str | None) -> str:
    pl = _norm_payload_language(payload_lang)
    if pl in {"en", "ko"}:
        return pl
    return detect_language(_text_for_answer_language_detection(query))


def extract_entity_payload(query: str) -> tuple[str, str | None, str | None, str | None]:
    q = str(query or "").strip()
    if not (q.startswith("{") and q.endswith("}")):
        return q, None, None, None
    try:
        import json

        obj = json.loads(q)
        if not isinstance(obj, dict):
            return q, None, None, None
        clean = str(obj.get("query") or "").strip() or q
        ext = str(obj.get("external_id") or "").strip() or None
        typ = str(obj.get("entity_type") or "").strip().lower() or None
        if typ not in {None, "company", "product"}:
            typ = None
        lang = _norm_payload_language(obj.get("language") or obj.get("lang"))
        return clean, ext, typ, lang
    except Exception:
        return q, None, None, None


def extract_external_id_marker(query: str) -> tuple[str, str | None]:
    q = str(query or "")
    m = _EXTERNAL_ID_MARKER_RE.search(q)
    if not m:
        return q.strip(), None
    ext = (m.group(1) or "").strip()
    clean = _EXTERNAL_ID_MARKER_RE.sub("", q).strip()
    clean = re.sub(r"\s{2,}", " ", clean).strip()
    return clean, (ext or None)


def parse_query_markers(query: str) -> tuple[str, str | None, str | None, str | None]:
    clean_query, payload_ext, payload_typ, payload_lang = extract_entity_payload(query)
    q = clean_query or query
    clean_query2, ext_marker2 = extract_external_id_marker(q)
    q2 = clean_query2 or q
    ext_marker = payload_ext or ext_marker2
    return q2, ext_marker, payload_typ, payload_lang


def build_async_openai_client(*, openai_api_key: str, openai_base_url: str) -> tuple[AsyncOpenAI | None, str]:
    key = (openai_api_key or "").strip()
    if not key:
        return None, ""
    client_kwargs: dict[str, Any] = {"api_key": key}
    if (openai_base_url or "").strip():
        client_kwargs["base_url"] = (openai_base_url or "").strip()
    return AsyncOpenAI(**client_kwargs), key


def clamp01(x: float) -> float:
    return max(0.05, min(0.95, float(x)))
