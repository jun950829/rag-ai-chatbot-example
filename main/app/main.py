"""FastAPI 앱 팩토리.

라우팅 구성:
- ``api_router``: ``{API_PREFIX}`` 아래 REST (health, companies, products)
- ``embedding_tool_router``: UI + ``/tools/embedding/api/search`` 등 (프리픽스 없음)
- ``chatbot_router``: Redis 큐 기반 ``/chat`` + SSE ``/stream/{id}`` (프리픽스 없음)

아키텍처 설명: ``docs/CHATBOT_ARCHITECTURE.md``
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.routes.chatbot import router as chatbot_router
from app.api.routes.embedding_tool import router as embedding_tool_router
from app.core.config import get_settings
from app.core.logging_config import configure_console_logging


def create_app() -> FastAPI:
    configure_console_logging()
    settings = get_settings()

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
    return app


app = create_app()
