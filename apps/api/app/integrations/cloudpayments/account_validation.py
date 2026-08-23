from __future__ import annotations

from app.models import PaymentProviderAccount
from app.payment_providers.contracts import OperationResultMeta, RetryDisposition
from app.integrations.cloudpayments.operation_meta import failed_meta


def validate_provider_account_context(
    *,
    provider_account: PaymentProviderAccount,
    provider_code: str,
    configured_public_id: str,
) -> OperationResultMeta | None:
    if provider_account.provider != provider_code:
        return failed_meta(
            code="provider_account_invalid_provider",
            message_safe="Selected provider account does not belong to CloudPayments.",
            retry_disposition=RetryDisposition.NON_RETRYABLE,
        )
    if not provider_account.enabled:
        return failed_meta(
            code="provider_account_disabled",
            message_safe="Selected provider account is disabled.",
            retry_disposition=RetryDisposition.NON_RETRYABLE,
        )
    configured_public_id = configured_public_id.strip()
    account_public_id = (provider_account.public_identifier or "").strip()
    if not configured_public_id or not account_public_id:
        return failed_meta(
            code="cloudpayments_public_id_missing",
            message_safe="CloudPayments provider account is missing its terminal identity.",
            retry_disposition=RetryDisposition.NON_RETRYABLE,
        )
    if account_public_id != configured_public_id:
        return failed_meta(
            code="cloudpayments_public_id_mismatch",
            message_safe="Selected provider account does not match the configured CloudPayments terminal.",
            retry_disposition=RetryDisposition.NON_RETRYABLE,
        )
    return None
