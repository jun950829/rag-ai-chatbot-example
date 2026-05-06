"""워커 휴리스틱 fallback ``general`` → OpenAI 라우팅 재판 (gpt-4o-mini 등).

검색 API를 타기 전에 ``company`` / ``product`` / ``follow_up`` 로 보낼지 결정만 한다.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_WORKER_ROUTE_LABELS = frozenset({"greeting", "follow_up", "company", "product", "general", "not_related"})


def _normalize_llm_intent_token(raw: str | None) -> str | None:
    if not raw:
        return None
    x = raw.strip().lower().replace("-", "_")
    alias = {
        "company_query": "company",
        "product_query": "product",
        "companyquery": "company",
        "productquery": "product",
        "followup": "follow_up",
    }
    x = alias.get(x, x)
    return x if x in _WORKER_ROUTE_LABELS else None


def _parse_intent_line(raw: str) -> str | None:
    """``intent=greeting`` 또는 단일 토큰."""
    text = (raw or "").strip().lower()
    m = re.search(r"intent\s*=\s*([a-z_]+)", text)
    if m:
        return _normalize_llm_intent_token(m.group(1))
    parts = text.replace(";", " ").replace(",", " ").split()
    if parts:
        return _normalize_llm_intent_token(parts[0])
    return None


async def openai_refine_worker_routing_intent(
    *,
    message: str,
    previous_intent: str | None,
    api_key: str,
    base_url: str | None,
    model: str,
) -> tuple[str | None, dict[str, Any]]:
    """반환 (새 라벨, None 이면 휴리스틱 유지). meta 는 trace/log 용."""

    sys_p = """\
너는 전시 챗봇 앞단(워커) 라우터다. 아래 허용 라벨 중 **정확히 한 줄만** 출력한다.
형식 우선: intent=<label>

허용 label (아래 문자열만):
greeting — 인사·감사·작별만
follow_up — 반드시 이전 발화 맥락을 가리키는 표현이 있어야 한다 (대명사, "그 업체는", 그럼 등)
company — 참가업체·회사·부스·전시 업체 검색·추천·목록
product — 전시품·제품·모델·스펙 검색
general — 순수 한마디 농담·잡담 등 전시/업체/제품과 무관
not_related — 날씨·주식·요리 등 전시와 완전 무관

판정:
- 업체·제품 검색 또는 나열 의도면 company 또는 product (애매하면 문맥 우선).
- 후행 표현 없으면 follow_up 금지.
""".strip()
    prev = (previous_intent or "").strip() or "(없음)"
    user_p = f"""직전 라우팅 intent(참고): {prev}
사용자 메시지: <<<{message}>>>

한 줄 출력: intent=<label>"""

    meta: dict[str, Any] = {"model": model, "raw_response": ""}
    try:
        kw: dict[str, Any] = {"api_key": api_key}
        if (base_url or "").strip():
            kw["base_url"] = base_url.strip()
        client = AsyncOpenAI(**kw)
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": sys_p},
                {"role": "user", "content": user_p},
            ],
        )
        raw_line = ((resp.choices[0].message.content) or "").strip()
        meta["raw_response"] = raw_line
        resolved = _parse_intent_line(raw_line)
        if resolved is None:
            logger.warning("[worker][openai_router] parse failed raw=%s", raw_line[:120])
            return None, meta
        return resolved, meta
    except Exception as e:
        logger.exception("[worker][openai_router] call failed: %s", e)
        meta["error"] = str(e)
        return None, meta
