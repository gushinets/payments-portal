from __future__ import annotations

from app.core.exceptions import ApplicationError


class PaymentProviderError(ApplicationError):
    code = "payment_provider_error"
    message = "Payment provider operation failed"


class PaymentProviderConfigurationError(PaymentProviderError):
    code = "payment_provider_configuration_error"
    message = "Payment provider configuration is invalid"

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(reason=code)


class CheckoutProviderUnavailableError(PaymentProviderError):
    code = "payment_provider_unavailable"
    message = "Payment provider is unavailable"

    def __init__(
        self,
        *,
        reason: str,
    ) -> None:
        super().__init__(reason=reason)
