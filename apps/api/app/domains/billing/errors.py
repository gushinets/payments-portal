from __future__ import annotations

from app.core.errors import AppError


class SubscriptionNotFoundError(AppError):
    pass


class SubscriptionPlanMissingError(AppError):
    pass


class AmbiguousCatalogProductOfferError(AppError):
    def __init__(self, *, product_code: str) -> None:
        super().__init__(details_safe={"product_code": product_code})
