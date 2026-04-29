"""버전이 붙은 공개 REST API 묶음 (``settings.api_prefix``, 기본 ``/api/v1``).

챗봇·임베딩 도구 UI는 ``main.py`` 에서 별도 라우터로 마운트한다 (프리픽스 없이 ``/tools/...``, ``/chat`` 등).
"""

from fastapi import APIRouter

from app.company.views import router as company_router
from app.api.routes.health import router as health_router
from app.product.views import router as product_router


api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(company_router)
api_router.include_router(product_router)
