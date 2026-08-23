from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from app.core.errors import PaymentsError
from app.integrations.cloudpayments.api_client import (
    CloudPaymentsApiClient,
    CloudPaymentsTransactionModel,
    CloudPaymentsTransactionStatus,
)
from app.models import PaymentProviderAccount
from app.payment_providers.contracts import (
    OperationResultMeta,
    RetryDisposition,
    TransactionLookupRequest,
    TransactionLookupResult,
    TransactionStatus,
)

FailureMetaFactory = Callable[..., OperationResultMeta]

CLOUDPAYMENTS_TRANSACTION_STATUS_MAP = {
    CloudPaymentsTransactionStatus.AWAITING_AUTHENTICATION: TransactionStatus.PENDING,
    CloudPaymentsTransactionStatus.AUTHORIZED: TransactionStatus.AUTHORIZED,
    CloudPaymentsTransactionStatus.COMPLETED: TransactionStatus.SUCCEEDED,
    CloudPaymentsTransactionStatus.CANCELLED: TransactionStatus.CANCELED,
    CloudPaymentsTransactionStatus.DECLINED: TransactionStatus.FAILED,
}


def lookup_transaction(
    *,
    api_client: CloudPaymentsApiClient,
    provider_account: PaymentProviderAccount,
    request: TransactionLookupRequest,
    provider_code: str,
    account_error: OperationResultMeta | None,
    failed_meta: FailureMetaFactory,
    failed_meta_from_error: Callable[..., OperationResultMeta],
    succeeded_meta: Callable[..., OperationResultMeta],
) -> TransactionLookupResult:
    if account_error is not None:
        return _lookup_failure_result(
            provider_code=provider_code,
            provider_account=provider_account,
            request=request,
            meta=account_error,
        )

    provider_transaction_id = _provider_transaction_id(request.provider_payment_id)
    if request.provider_payment_id and provider_transaction_id is None:
        return _lookup_failure_result(
            provider_code=provider_code,
            provider_account=provider_account,
            request=request,
            meta=failed_meta(
                code="cloudpayments_transaction_id_invalid",
                message_safe="CloudPayments TransactionId is invalid.",
                retry_disposition=RetryDisposition.NON_RETRYABLE,
            ),
        )

    lookup_invoice_id = _lookup_invoice_id(request)
    if provider_transaction_id is None and lookup_invoice_id is None:
        return _lookup_failure_result(
            provider_code=provider_code,
            provider_account=provider_account,
            request=request,
            meta=failed_meta(
                code="cloudpayments_lookup_identifier_required",
                message_safe="CloudPayments lookup requires a transaction or invoice identifier.",
                retry_disposition=RetryDisposition.NON_RETRYABLE,
            ),
        )

    try:
        if provider_transaction_id is not None:
            response = api_client.get_transaction(transaction_id=provider_transaction_id)
        else:
            assert lookup_invoice_id is not None
            response = api_client.find_transaction(invoice_id=lookup_invoice_id)
    except PaymentsError as exc:
        return _lookup_failure_result(
            provider_code=provider_code,
            provider_account=provider_account,
            request=request,
            meta=failed_meta_from_error(exc),
        )

    if response is None:
        return _lookup_failure_result(
            provider_code=provider_code,
            provider_account=provider_account,
            request=request,
            meta=failed_meta(
                code="cloudpayments_payment_not_found",
                message_safe="CloudPayments transaction was not found.",
                retry_disposition=RetryDisposition.NON_RETRYABLE,
            ),
        )

    model = response.model
    if model is None:
        return _lookup_failure_result(
            provider_code=provider_code,
            provider_account=provider_account,
            request=request,
            meta=failed_meta(
                code="cloudpayments_transaction_lookup_missing_model",
                message_safe="CloudPayments transaction lookup returned no model.",
                retry_disposition=RetryDisposition.NON_RETRYABLE,
            ),
        )

    if provider_account.public_identifier and model.public_id:
        if provider_account.public_identifier.strip() != model.public_id.strip():
            return _lookup_failure_result(
                provider_code=provider_code,
                provider_account=provider_account,
                request=request,
                meta=failed_meta(
                    code="cloudpayments_public_id_mismatch",
                    message_safe="CloudPayments transaction belongs to a different provider account.",
                    retry_disposition=RetryDisposition.NON_RETRYABLE,
                ),
            )

    validation_error = _validate_transaction_model(
        model=model,
        request=request,
        requested_transaction_id=provider_transaction_id,
        lookup_invoice_id=lookup_invoice_id,
    )
    if validation_error is not None:
        code, message_safe = validation_error
        return _lookup_failure_result(
            provider_code=provider_code,
            provider_account=provider_account,
            request=request,
            meta=failed_meta(
                code=code,
                message_safe=message_safe,
                retry_disposition=RetryDisposition.NON_RETRYABLE,
            ),
        )

    amount = model.amount
    currency = model.currency
    return TransactionLookupResult(
        provider=provider_code,
        provider_account_id=str(provider_account.id),
        provider_payment_id=str(model.transaction_id),
        provider_invoice_id=model.invoice_id,
        merchant_order_id=request.merchant_order_id,
        status=_map_transaction_status(model),
        amount_minor=_amount_minor(amount),
        amount=amount,
        currency=currency,
        meta=succeeded_meta(),
    )


def _provider_transaction_id(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or not normalized.isdigit():
        return None
    return int(normalized)


def _lookup_invoice_id(request: TransactionLookupRequest) -> str | None:
    """Map the local merchant order fallback to the CloudPayments InvoiceId."""

    for value in (request.provider_invoice_id, request.merchant_order_id):
        if value is not None and value.strip():
            return value.strip()
    return None


def _lookup_failure_result(
    *,
    provider_code: str,
    provider_account: PaymentProviderAccount,
    request: TransactionLookupRequest,
    meta: OperationResultMeta,
) -> TransactionLookupResult:
    return TransactionLookupResult(
        provider=provider_code,
        provider_account_id=str(provider_account.id),
        provider_payment_id=None,
        provider_invoice_id=None,
        merchant_order_id=request.merchant_order_id,
        status=TransactionStatus.UNKNOWN,
        amount_minor=None,
        amount=None,
        currency=None,
        meta=meta,
    )


def _validate_transaction_model(
    *,
    model: CloudPaymentsTransactionModel,
    request: TransactionLookupRequest,
    requested_transaction_id: int | None,
    lookup_invoice_id: str | None,
) -> tuple[str, str] | None:
    if model.transaction_id <= 0:
        return (
            "cloudpayments_transaction_lookup_schema_mismatch",
            "CloudPayments transaction response has an invalid transaction id.",
        )

    if requested_transaction_id is not None and model.transaction_id != requested_transaction_id:
        return (
            "cloudpayments_transaction_id_mismatch",
            "CloudPayments returned a different transaction id.",
        )

    if lookup_invoice_id is not None:
        if model.invoice_id is None or model.invoice_id.strip() != lookup_invoice_id:
            return (
                "cloudpayments_invoice_id_mismatch",
                "CloudPayments returned a different invoice id.",
            )

    amount = model.amount
    amount_minor = _amount_minor(amount)
    if amount_minor is None:
        return (
            "cloudpayments_transaction_amount_missing",
            "CloudPayments transaction response has no valid amount.",
        )
    if amount_minor != request.expected_amount_minor:
        return (
            "cloudpayments_amount_mismatch",
            "CloudPayments transaction amount does not match the expected amount.",
        )

    currency = model.currency
    if currency is None:
        return (
            "cloudpayments_transaction_currency_missing",
            "CloudPayments transaction response has no currency.",
        )
    if currency.strip().upper() != request.expected_currency.strip().upper():
        return (
            "cloudpayments_currency_mismatch",
            "CloudPayments transaction currency does not match the expected currency.",
        )

    operation_type = (model.operation_type or "").strip().casefold()
    if operation_type:
        if operation_type != "payment":
            return (
                "cloudpayments_non_payment_operation",
                "CloudPayments lookup returned a non-payment operation.",
            )
    elif model.transaction_type is None:
        return (
            "cloudpayments_ambiguous_operation",
            "CloudPayments transaction operation type is unavailable.",
        )
    elif model.transaction_type != 0:
        return (
            "cloudpayments_non_payment_operation",
            "CloudPayments lookup returned a non-payment operation.",
        )

    if _map_transaction_status(model) == TransactionStatus.UNKNOWN:
        return (
            "cloudpayments_transaction_status_unknown",
            "CloudPayments transaction status is unavailable or unknown.",
        )
    return None


def _map_transaction_status(model: CloudPaymentsTransactionModel) -> TransactionStatus:
    provider_status = _cloudpayments_transaction_status(model.status)
    if provider_status is None:
        return TransactionStatus.UNKNOWN
    return CLOUDPAYMENTS_TRANSACTION_STATUS_MAP[provider_status]


def _cloudpayments_transaction_status(value: str | None) -> CloudPaymentsTransactionStatus | None:
    if value is None:
        return None
    normalized = value.strip()
    for status in CloudPaymentsTransactionStatus:
        if normalized == status.value:
            return status
    return None


def _amount_minor(amount: Decimal | None) -> int | None:
    if amount is None:
        return None
    scaled = amount * Decimal("100")
    if scaled != scaled.to_integral_value():
        return None
    return int(scaled)
