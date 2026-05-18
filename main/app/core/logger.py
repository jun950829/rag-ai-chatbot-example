import logging
import os
import sys
from logging.handlers import WatchedFileHandler
from pathlib import Path
from typing import Optional


class _ExactLevelFilter(logging.Filter):
    def __init__(self, level: int):
        super().__init__()
        self._level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == self._level


class _MinLevelFilter(logging.Filter):
    def __init__(self, level: int):
        super().__init__()
        self._level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self._level


def setup_logger(
    name: str = "exmatch",
    log_dir: str = "logs",
    level: int = logging.INFO,
    console_output: bool = True,
) -> logging.Logger:
    requested_log_dir = os.getenv("LOG_DIR", log_dir)
    log_path: Optional[Path] = None
    last_log_dir_error: Optional[Exception] = None

    for candidate in (Path(requested_log_dir), Path("/tmp/exmatch_logs")):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            if os.access(candidate, os.W_OK | os.X_OK):
                log_path = candidate
                break
        except OSError as exc:
            last_log_dir_error = exc

    file_logging_enabled = log_path is not None

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(filename)s:%(lineno)d | %(funcName)s() | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if file_logging_enabled and log_path is not None:
        try:
            info_handler = WatchedFileHandler(filename=str(log_path / "info.log"), encoding="utf-8")
            info_handler.setLevel(logging.INFO)
            info_handler.addFilter(_ExactLevelFilter(logging.INFO))
            info_handler.setFormatter(formatter)
            logger.addHandler(info_handler)

            warning_handler = WatchedFileHandler(filename=str(log_path / "warning.log"), encoding="utf-8")
            warning_handler.setLevel(logging.WARNING)
            warning_handler.addFilter(_ExactLevelFilter(logging.WARNING))
            warning_handler.setFormatter(formatter)
            logger.addHandler(warning_handler)

            error_handler = WatchedFileHandler(filename=str(log_path / "error.log"), encoding="utf-8")
            error_handler.setLevel(logging.ERROR)
            error_handler.addFilter(_MinLevelFilter(logging.ERROR))
            error_handler.setFormatter(formatter)
            logger.addHandler(error_handler)
        except OSError as exc:
            file_logging_enabled = False
            last_log_dir_error = exc

    if console_output or not file_logging_enabled:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if not file_logging_enabled:
        reason = f"{last_log_dir_error}" if last_log_dir_error else "unknown error"
        logger.warning(
            "File logging disabled; using console only. requested_log_dir=%s reason=%s",
            requested_log_dir,
            reason,
        )

    return logger


_root_logging_bound = False


def parse_log_level(name: str) -> int:
    """문자열 레벨(예: settings.log_level, LOG_LEVEL) → logging 상수."""

    n = (name or "INFO").strip().upper()
    return getattr(logging, n, logging.INFO)


def configure_root_logging(*, log_level_str: str = "INFO") -> None:
    """``setup_logger`` 로 만든 핸들러를 root에 붙인다.

    ``get_logger(__name__)`` 출력이 동일 파일·콘솔 정책을 따른다.
    FastAPI ``create_app`` 에서 1회 호출. ``LOG_LEVEL`` 환경 변수가 있으면 ``log_level_str`` 보다 우선.
    """

    global _root_logging_bound
    if _root_logging_bound:
        return

    env = (os.getenv("LOG_LEVEL") or "").strip().upper()
    level = parse_log_level(env) if env else parse_log_level(log_level_str)

    app_logger = setup_logger(name="exmatch", level=level, console_output=True)

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass

    for h in list(app_logger.handlers):
        app_logger.removeHandler(h)
        root.addHandler(h)

    app_logger.propagate = True
    app_logger.setLevel(level)
    root.setLevel(level)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    _root_logging_bound = True


def get_logger(name: str) -> logging.Logger:
    """모듈 로거. ``logger = get_logger(__name__)`` 형태로 사용."""

    return logging.getLogger(name)


logger = setup_logger()
