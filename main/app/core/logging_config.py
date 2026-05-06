"""콘솔 로깅: uvicorn 기본 설정만으로는 ``app.*`` 로거 INFO가 안 보일 때가 있어 루트 레벨과 핸들러를 맞춘다."""

from __future__ import annotations

import logging
import sys

_configured = False


def configure_console_logging(level: int = logging.INFO) -> None:
    """앱 부팅 시 한 번 호출. 터미널에 ``app.rag`` 등 단계 로그가 보이도록 한다."""
    global _configured
    root = logging.getLogger()
    root.setLevel(level)
    for name in ("app", "app.rag", "app.api", "app.db", "app.services"):
        logging.getLogger(name).setLevel(level)
    if _configured:
        return
    # uvicorn이 이미 루트 핸들러를 붙인 경우 중복 출력을 피한다.
    if root.handlers:
        _configured = True
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(handler)
    _configured = True
