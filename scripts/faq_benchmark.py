from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> None:
    base = "http://52.64.112.27:8000"
    queries = [
        "전시 시간",
        "관람 시간",
        "셔틀 시간",
        "셔틀버스",
        "사전등록 방법",
        "등록 방법",
        "출입증 수령 위치",
        "주차 요금",
        "행사 장소",
        "오시는 길",
        "배지 발급",
    ]

    for q in queries:
        qs = urllib.parse.urlencode({"query": q, "qa_user": "visitor", "faq_only": "true"})
        url = f"{base}/tools/embedding/api/faq-debug?{qs}"
        t0 = time.perf_counter()
        out = _get(url)
        ms = (time.perf_counter() - t0) * 1000
        matched = bool(out.get("matched"))
        meta = ((out.get("payload") or {}).get("answer_meta") or {}) if matched else {}
        print(f"{q:12s} matched={matched} ms={ms:6.1f} mode={meta.get('mode')} qna={meta.get('qna_code')}")


if __name__ == "__main__":
    main()

