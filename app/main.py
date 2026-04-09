from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings


def create_app() -> FastAPI:
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
    return app


app = create_app()
