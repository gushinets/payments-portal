

from enum import Enum


class PlanScopeType(str, Enum):
    PRODUCT = "product"
    BUNDLE = "bundle"
    ALL_ACCESS = "all_access"