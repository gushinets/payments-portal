from __future__ import annotations

from app.core.errors import PaymentsError, PaymentsTransportError
from app.payment_providers.contracts import (
    OperationOutcome,
    OperationResultMeta,
    ProviderFailure,
    RetryDisposition,
)


def succeeded_meta(*, idempotency_key: str | None = None) -> OperationResultMeta:
    return OperationResultMeta(
        outcome=OperationOutcome.SUCCEEDED,
        retry_disposition=RetryDisposition.NON_RETRYABLE,
        idempotency_key=idempotency_key,
    )


def failed_meta(
    *,
    code: str,
    message_safe: str | None,
    retry_disposition: RetryDisposition,
    idempotency_key: str | None = None,
) -> OperationResultMeta:
    return OperationResultMeta(
        outcome=OperationOutcome.FAILED,
        retry_disposition=retry_disposition,
        idempotency_key=idempotency_key,
        failure=ProviderFailure(code=code, message_safe=message_safe),
    )


def failed_meta_from_error(
    error: PaymentsError,
    *,
    idempotency_key: str | None = None,
) -> OperationResultMeta:
    retry_disposition = (
        error.retry_disposition if isinstance(error, PaymentsTransportError) else RetryDisposition.NON_RETRYABLE
    )
    return failed_meta(
        code=error.code,
        message_safe=error.message_safe,
        retry_disposition=retry_disposition,
        idempotency_key=idempotency_key,
    )
