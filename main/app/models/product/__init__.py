"""제품(product) 도메인 — ORM, API 스키마, 카테고리 라벨, DB 헬퍼."""

from app.models.product.category_dict import MAIN_CATEGORY_LABELS, SUB_CATEGORY_LABELS
from app.models.product.helpers import (
    apply_product_fields,
    apply_product_filters,
    ensure_company_exists,
    find_product_by_external_id,
)
from app.models.product.models import Product
from app.models.product.serializers import (
    ProductCreate,
    ProductListItem,
    ProductRead,
    ProductUpdate,
)

__all__ = [
    "MAIN_CATEGORY_LABELS",
    "SUB_CATEGORY_LABELS",
    "Product",
    "ProductCreate",
    "ProductListItem",
    "ProductRead",
    "ProductUpdate",
    "apply_product_fields",
    "apply_product_filters",
    "ensure_company_exists",
    "find_product_by_external_id",
]
