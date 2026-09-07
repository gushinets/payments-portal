from __future__ import annotations

from app.core.errors import AppError


class CheckoutError(AppError):
    pass


class UnknownProductPlanError(CheckoutError):
    pass


class AutomaticRenewalNotPermittedError(CheckoutError):
    pass


class MissingRequiredDocumentsError(CheckoutError):
    def __init__(self, documents: list[dict[str, str]]) -> None:
        super().__init__(details_safe={"documents": documents})


class RecurringConsentRequiredError(CheckoutError):
    pass


class ProviderCurrencyMismatchError(CheckoutError):
    pass


class PasswordResetError(AppError):
    pass


class PasswordResetRateLimitedError(PasswordResetError):
    pass


class InvalidOrExpiredResetTokenError(PasswordResetError):
    pass
