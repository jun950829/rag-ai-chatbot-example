"""FastAPI 앱 팩토리.

라우팅 구성:
- ``api_router``: ``{API_PREFIX}`` 아래 REST (health, companies, products)
- ``embedding_tool_router``: UI + ``/tools/embedding/api/search``, ``/kimeschat``, ``/tools/chatbot`` 등 (프리픽스 없음)
- ``chatbot_router``: ``app.routers.chatbot`` — Redis 큐 기반 ``/chat`` + SSE ``/stream/{id}`` (프리픽스 없음)
- 정적 챗봇 SPA(Mount ``/tools/chatbot-ui``): ``main/frontend`` 의 ``npm run build`` 산출물

아키텍처 설명: ``docs/CHATBOT_ARCHITECTURE.md``
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.routers.chatbot import router as chatbot_router
from app.api.routes.embedding_tool import router as embedding_tool_router
from app.core.config import get_settings
from app.core.logger import configure_root_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_root_logging(log_level_str=settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url=f"{settings.api_prefix}/openapi.json",
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/", tags=["meta"])
    def root() -> dict[str, str]:
        return {
            "message": f"{settings.app_name} is running.",
            "docs": "/docs",
            "health": f"{settings.api_prefix}/health",
        }

    app.include_router(api_router, prefix=settings.api_prefix)
    app.include_router(embedding_tool_router)
    app.include_router(chatbot_router)

    _chatbot_ui_root = Path(__file__).resolve().parent / "static" / "chatbot-ui"
    if _chatbot_ui_root.is_dir():
        app.mount(
            "/tools/chatbot-ui",
            StaticFiles(directory=str(_chatbot_ui_root), html=True),
            name="chatbot_ui",
        )

    return app


app = create_app()
