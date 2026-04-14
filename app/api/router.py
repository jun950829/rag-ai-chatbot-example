from fastapi import APIRouter

from app.company.views import router as company_router
from app.api.routes.health import router as health_router
from app.new_company.views import router as new_company_router
from app.product.views import router as product_router


api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(company_router)
api_router.include_router(new_company_router)
api_router.include_router(product_router)
