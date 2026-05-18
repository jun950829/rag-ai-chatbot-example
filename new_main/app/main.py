from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.api.tools_compat import router as tools_compat_router
from app.core.config import get_settings
from app.core.logger import configure_root_logging


def create_app() -> FastAPI:
    st = get_settings()
    configure_root_logging(log_level_str="INFO")
    app = FastAPI(title=st.app_name, version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(tools_compat_router)
    app.include_router(chat_router)

    dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")

    return app


app = create_app()
