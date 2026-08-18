

from enum import Enum


class PlanScopeType(str, Enum):
    PRODUCT = "product"
    BUNDLE = "bundle"
    ALL_ACCESS = "all_access"


class ProductStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class BundleStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
