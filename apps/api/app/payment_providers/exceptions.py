from __future__ import annotations

from app.core.exceptions import ApplicationError


class PaymentProviderError(ApplicationError):
    code = "payment_provider_error"
    message = "Payment provider operation failed"


class CheckoutProviderUnavailableError(PaymentProviderError):
    code = "payment_provider_unavailable"
    message = "Payment provider is unavailable"

    def __init__(
        self,
        *,
        reason: str,
    ) -> None:
        super().__init__(reason=reason)
