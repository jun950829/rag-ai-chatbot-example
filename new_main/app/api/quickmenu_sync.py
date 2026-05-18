"""kprint_qa_quickmenu 동기 조회 (new_main: SQLAlchemy sync 엔진)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.retrieval.vector_db import get_sync_engine


def _dedupe_codes(codes: list[str | None]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in codes:
        c = (raw or "").strip()
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def _candidate_codes(raw_code: str) -> list[str]:
    c = (raw_code or "").strip()
    if not c:
        return []
    out = [c]
    if c.startswith("km_"):
        out.append("kp_" + c[3:])
    return _dedupe_codes(out)


def _effective_quickmenu_label(row: dict[str, Any]) -> str:
    for raw in (row.get("quickmenu_label"), row.get("subcategory"), row.get("category"), row.get("domain")):
        v = (str(raw or "")).strip()
        if v and v != "-":
            return v
    return (str(row.get("qna_code") or "")).strip()


def quickmenu_row_to_dict(row: dict[str, Any], *, include_prompt: bool = True) -> dict[str, Any]:
    d: dict[str, Any] = {
        "qna_code": row.get("qna_code"),
        "primary_question": row.get("primary_question"),
        "parent_id": row.get("parent_id"),
        "depth": row.get("depth"),
        "quickmenu_label": row.get("quickmenu_label"),
        "quickmenu_display_label": _effective_quickmenu_label(row),
        "qa_user": row.get("qa_user"),
        "domain": row.get("domain"),
        "category": row.get("category"),
        "subcategory": row.get("subcategory"),
        "question_sample": row.get("question_sample"),
        "answer_sample": row.get("answer_sample"),
        "links": row.get("links"),
        "utm": row.get("utm"),
        "follow_question1": row.get("follow_question1"),
        "follow_question2": row.get("follow_question2"),
        "follow_question3": row.get("follow_question3"),
        "follow_question4": row.get("follow_question4"),
        "follow_question5_formoreinformation": row.get("follow_question5_formoreinformation"),
        "default_quickmenu": row.get("default_quickmenu"),
        "default_answer_type": row.get("default_answer_type"),
        "notes": row.get("notes"),
    }
    if include_prompt:
        d["default_answer_prompt"] = row.get("default_answer_prompt")
    return d


def follow_codes_from_row(row: dict[str, Any]) -> list[str]:
    return _dedupe_codes(
        [
            row.get("follow_question1"),
            row.get("follow_question2"),
            row.get("follow_question3"),
            row.get("follow_question4"),
            row.get("follow_question5_formoreinformation"),
            row.get("default_quickmenu"),
        ]
    )


def _row_select_fragment() -> str:
    return """
        qna_code, primary_question, parent_id, depth, quickmenu_label, qa_user, domain, category, subcategory,
        question_sample, answer_sample, links, utm, follow_question1, follow_question2, follow_question3, follow_question4,
        follow_question5_formoreinformation, default_quickmenu, default_answer_type, default_answer_prompt, notes
    """


def landing_counts() -> tuple[int, int]:
    eng = get_sync_engine()
    sql = text(
        """
        SELECT
          (SELECT count(*)::int FROM kprint_qa_quickmenu q WHERE q.primary_question IS TRUE AND q.qa_user = 'visitor') AS vn,
          (SELECT count(*)::int FROM kprint_qa_quickmenu q WHERE q.primary_question IS TRUE AND q.qa_user = 'exhibitor') AS en
        """
    )
    with eng.connect() as conn:
        r = conn.execute(sql).mappings().first()
        if not r:
            return 0, 0
        return int(r.get("vn") or 0), int(r.get("en") or 0)


def list_primary_rows(*, qa_user: str | None, domain: str | None) -> list[dict[str, Any]]:
    eng = get_sync_engine()
    cols = _row_select_fragment()
    where = ["primary_question IS TRUE"]
    params: dict[str, Any] = {}
    if (qa_user or "").strip():
        where.append("qa_user = :qa_user")
        params["qa_user"] = qa_user.strip()
    if (domain or "").strip():
        where.append("domain = :domain")
        params["domain"] = domain.strip()
    w = " AND ".join(where)
    sql = text(f"SELECT {cols} FROM kprint_qa_quickmenu WHERE {w} ORDER BY qna_code")
    with eng.connect() as conn:
        return [dict(x) for x in conn.execute(sql, params).mappings().all()]


def get_row(qna_code: str) -> dict[str, Any] | None:
    code = (qna_code or "").strip()
    if not code:
        return None
    eng = get_sync_engine()
    cols = _row_select_fragment()
    sql = text(f"SELECT {cols} FROM kprint_qa_quickmenu WHERE qna_code = :code LIMIT 1")
    with eng.connect() as conn:
        r = conn.execute(sql, {"code": code}).mappings().first()
        return dict(r) if r else None


def list_follow_link_rows(qna_code: str) -> list[dict[str, Any]]:
    row = get_row(qna_code)
    if not row:
        return []
    ordered = follow_codes_from_row(row)
    if not ordered:
        return []
    eng = get_sync_engine()
    in_params = {f"c{i}": v for i, v in enumerate(ordered)}
    in_list = ", ".join([f":c{i}" for i in range(len(ordered))])
    cols = _row_select_fragment()
    sql = text(f"SELECT {cols} FROM kprint_qa_quickmenu WHERE qna_code IN ({in_list})")
    with eng.connect() as conn:
        by_code = {str(x["qna_code"]): dict(x) for x in conn.execute(sql, in_params).mappings().all()}
    return [by_code[c] for c in ordered if c in by_code]


def resolve_follow_question_rows(row: dict[str, Any]) -> list[dict[str, Any]]:
    slots = [
        ("follow_question1", row.get("follow_question1")),
        ("follow_question2", row.get("follow_question2")),
        ("follow_question3", row.get("follow_question3")),
        ("follow_question4", row.get("follow_question4")),
    ]
    raw_codes = [str(v).strip() for _, v in slots if str(v or "").strip()]
    if not raw_codes:
        return []

    all_candidates: list[str] = []
    for rc in raw_codes:
        all_candidates.extend(_candidate_codes(rc))
    all_candidates = _dedupe_codes(all_candidates)

    eng = get_sync_engine()
    in_params = {f"c{i}": v for i, v in enumerate(all_candidates)}
    in_list = ", ".join([f":c{i}" for i in range(len(all_candidates))]) or "NULL"
    cols = _row_select_fragment()
    sql = text(f"SELECT {cols} FROM kprint_qa_quickmenu WHERE qna_code IN ({in_list})")
    with eng.connect() as conn:
        by_code = {str(x["qna_code"]): dict(x) for x in conn.execute(sql, in_params).mappings().all()}

    out: list[dict[str, Any]] = []
    for slot_name, raw in slots:
        code = str(raw or "").strip()
        if not code:
            continue
        resolved = None
        resolved_code = None
        for cand in _candidate_codes(code):
            if cand in by_code:
                resolved = by_code[cand]
                resolved_code = cand
                break
        out.append(
            {
                "slot": slot_name,
                "code": code,
                "resolved_qna_code": resolved_code,
                "item": quickmenu_row_to_dict(resolved, include_prompt=False) if resolved is not None else None,
            }
        )
    return out
