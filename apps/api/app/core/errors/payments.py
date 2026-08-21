from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.errors.base import AppError
from app.payment_providers.contracts import RetryDisposition


class PaymentsError(AppError):
    pass


class PaymentProviderConfigurationError(PaymentsError):
    pass


class PaymentsTransportError(PaymentsError):
    def __init__(
        self,
        code: str,
        *,
        retry_disposition: RetryDisposition,
        message_safe: str | None = None,
        details_safe: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message_safe=message_safe, details_safe=details_safe)
        self.retry_disposition = retry_disposition


class PaymentsTimeoutError(PaymentsTransportError):
    pass


class PaymentsAuthenticationError(PaymentsError):
    pass


class PaymentsRateLimitError(PaymentsTransportError):
    pass


class PaymentsUpstreamError(PaymentsTransportError):
    pass


class PaymentsHttpError(PaymentsError):
    def __init__(
        self,
        code: str,
        *,
        status_code: int,
        message_safe: str | None = None,
        details_safe: Mapping[str, Any] | None = None,
    ) -> None:
        merged_details: dict[str, Any] = {"status_code": status_code}
        if details_safe:
            merged_details.update(details_safe)
        super().__init__(code, message_safe=message_safe, details_safe=merged_details)
        self.status_code = status_code


class PaymentsResponseDecodeError(PaymentsError):
    pass


class PaymentsResponseValidationError(PaymentsError):
    pass


class PaymentsOperationDeclinedError(PaymentsError):
    def __init__(
        self,
        code: str,
        *,
        provider: str,
        operation: str,
        message_safe: str | None = None,
        details_safe: Mapping[str, Any] | None = None,
    ) -> None:
        merged_details: dict[str, Any] = {
            "provider": provider,
            "operation": operation,
        }
        if details_safe:
            merged_details.update(details_safe)
        super().__init__(code, message_safe=message_safe, details_safe=merged_details)
        self.provider = provider
        self.operation = operation
