from __future__ import annotations

from decimal import Decimal

from app.core.errors import PaymentsError
from app.integrations.cloudpayments.account_validation import validate_provider_account_context
from app.integrations.cloudpayments.api_client import (
    CloudPaymentsApiClient,
    CloudPaymentsCreateSubscriptionRequest,
    CloudPaymentsUpdateSubscriptionRequest,
)
from app.integrations.cloudpayments.operation_meta import (
    failed_meta,
    failed_meta_from_error,
    has_idempotency_key,
    idempotency_key_required_meta,
    succeeded_meta,
)
from app.models import PaymentProviderAccount
from app.payment_providers.contracts import (
    CancelRecurringSubscriptionRequest,
    CancelRecurringSubscriptionResult,
    CreateRecurringSubscriptionRequest,
    CreateRecurringSubscriptionResult,
    OperationResultMeta,
    RecurringSubscriptionStatus,
    RetryDisposition,
    UpdateRecurringSubscriptionRequest,
    UpdateRecurringSubscriptionResult,
)

_MUTABLE_SUBSCRIPTION_STATUSES = {
    RecurringSubscriptionStatus.ACTIVE,
    RecurringSubscriptionStatus.PAST_DUE,
}


def create_recurring_subscription(
    *,
    api_client: CloudPaymentsApiClient,
    provider_code: str,
    provider_account: PaymentProviderAccount,
    request: CreateRecurringSubscriptionRequest,
) -> CreateRecurringSubscriptionResult:
    account_error = validate_provider_account_context(
        provider_account=provider_account,
        provider_code=provider_code,
        configured_public_id=api_client.config.public_id,
    )
    if account_error is not None:
        return _create_subscription_failure_result(
            provider_code=provider_code,
            provider_account=provider_account,
            request=request,
            meta=account_error,
        )

    if not has_idempotency_key(request.idempotency_key):
        return _create_subscription_failure_result(
            provider_code=provider_code,
            provider_account=provider_account,
            request=request,
            meta=idempotency_key_required_meta(),
        )

    validation_error = _validate_create_subscription_request(
        provider_account=provider_account,
        request=request,
    )
    if validation_error is not None:
        return _create_subscription_failure_result(
            provider_code=provider_code,
            provider_account=provider_account,
            request=request,
            meta=validation_error,
        )

    assert request.start_at is not None
    interval = _cloudpayments_interval(request.interval_unit)
    assert interval is not None
    try:
        response = api_client.create_subscription(
            request=CloudPaymentsCreateSubscriptionRequest(
                Token=request.payment_method_reference,
                AccountId=request.account_id,
                Description=request.description,
                Amount=request.amount,
                Currency=request.currency.strip().upper(),
                RequireConfirmation=request.require_confirmation,
                StartDate=request.start_at.strip(),
                Interval=interval,
                Period=request.interval_count,
                Email=request.email,
                MaxPeriods=request.max_periods,
            ),
            idempotency_key=request.idempotency_key,
        )
    except PaymentsError as exc:
        return _create_subscription_failure_result(
            provider_code=provider_code,
            provider_account=provider_account,
            request=request,
            meta=failed_meta_from_error(exc, idempotency_key=request.idempotency_key),
        )

    assert response.model is not None
    model = response.model
    return CreateRecurringSubscriptionResult(
        provider=provider_code,
        provider_account_id=str(provider_account.id),
        provider_subscription_id=model.subscription_id,
        account_id=request.account_id,
        status=_map_subscription_status(model.status),
        amount_minor=_amount_minor(model.amount),
        amount=model.amount,
        currency=model.currency,
        interval_unit=_normalized_interval_unit(model.interval),
        interval_count=model.period,
        meta=succeeded_meta(idempotency_key=request.idempotency_key),
    )


def update_recurring_subscription(
    *,
    api_client: CloudPaymentsApiClient,
    provider_code: str,
    provider_account: PaymentProviderAccount,
    request: UpdateRecurringSubscriptionRequest,
) -> UpdateRecurringSubscriptionResult:
    account_error = validate_provider_account_context(
        provider_account=provider_account,
        provider_code=provider_code,
        configured_public_id=api_client.config.public_id,
    )
    if account_error is not None:
        return _update_subscription_failure_result(
            provider_code=provider_code,
            provider_account=provider_account,
            request=request,
            meta=account_error,
        )

    if not has_idempotency_key(request.idempotency_key):
        return _update_subscription_failure_result(
            provider_code=provider_code,
            provider_account=provider_account,
            request=request,
            meta=idempotency_key_required_meta(),
        )

    validation_error = _validate_update_subscription_request(
        provider_account=provider_account,
        request=request,
    )
    if validation_error is not None:
        return _update_subscription_failure_result(
            provider_code=provider_code,
            provider_account=provider_account,
            request=request,
            meta=validation_error,
        )

    current_subscription_error = _validate_current_subscription_can_be_updated(
        api_client=api_client,
        request=request,
    )
    if current_subscription_error is not None:
        return _update_subscription_failure_result(
            provider_code=provider_code,
            provider_account=provider_account,
            request=request,
            meta=current_subscription_error,
        )

    interval = _cloudpayments_interval(request.interval_unit)
    try:
        response = api_client.update_subscription(
            request=CloudPaymentsUpdateSubscriptionRequest(
                Id=request.provider_subscription_id,
                Description=request.description,
                Amount=request.amount,
                Currency=request.currency.strip().upper() if request.currency is not None else None,
                RequireConfirmation=request.require_confirmation,
                StartDate=request.start_at.strip() if request.start_at is not None else None,
                Interval=interval,
                Period=request.interval_count,
                MaxPeriods=request.max_periods,
            ),
            idempotency_key=request.idempotency_key,
        )
    except PaymentsError as exc:
        return _update_subscription_failure_result(
            provider_code=provider_code,
            provider_account=provider_account,
            request=request,
            meta=failed_meta_from_error(exc, idempotency_key=request.idempotency_key),
        )

    assert response.model is not None
    model = response.model
    return UpdateRecurringSubscriptionResult(
        provider=provider_code,
        provider_account_id=str(provider_account.id),
        provider_subscription_id=model.subscription_id,
        status=_map_subscription_status(model.status),
        amount_minor=_amount_minor(model.amount),
        amount=model.amount,
        currency=model.currency,
        interval_unit=_normalized_interval_unit(model.interval),
        interval_count=model.period,
        meta=succeeded_meta(idempotency_key=request.idempotency_key),
    )


def cancel_recurring_subscription(
    *,
    api_client: CloudPaymentsApiClient,
    provider_code: str,
    provider_account: PaymentProviderAccount,
    request: CancelRecurringSubscriptionRequest,
) -> CancelRecurringSubscriptionResult:
    account_error = validate_provider_account_context(
        provider_account=provider_account,
        provider_code=provider_code,
        configured_public_id=api_client.config.public_id,
    )
    if account_error is not None:
        return CancelRecurringSubscriptionResult(
            provider=provider_code,
            provider_account_id=str(provider_account.id),
            provider_subscription_id=request.provider_subscription_id,
            status=RecurringSubscriptionStatus.FAILED,
            meta=account_error,
        )

    if not has_idempotency_key(request.idempotency_key):
        return CancelRecurringSubscriptionResult(
            provider=provider_code,
            provider_account_id=str(provider_account.id),
            provider_subscription_id=request.provider_subscription_id,
            status=RecurringSubscriptionStatus.FAILED,
            meta=idempotency_key_required_meta(),
        )

    try:
        api_client.cancel_subscription(
            subscription_id=request.provider_subscription_id,
            idempotency_key=request.idempotency_key,
        )
    except PaymentsError as exc:
        return CancelRecurringSubscriptionResult(
            provider=provider_code,
            provider_account_id=str(provider_account.id),
            provider_subscription_id=request.provider_subscription_id,
            status=RecurringSubscriptionStatus.FAILED,
            meta=failed_meta_from_error(exc, idempotency_key=request.idempotency_key),
        )

    return CancelRecurringSubscriptionResult(
        provider=provider_code,
        provider_account_id=str(provider_account.id),
        provider_subscription_id=request.provider_subscription_id,
        status=RecurringSubscriptionStatus.CANCELED,
        meta=succeeded_meta(idempotency_key=request.idempotency_key),
    )


def _validate_create_subscription_request(
    *,
    provider_account: PaymentProviderAccount,
    request: CreateRecurringSubscriptionRequest,
) -> OperationResultMeta | None:
    if request.start_at is None or not request.start_at.strip():
        return failed_meta(
            code="recurring_start_at_required",
            message_safe="Recurring subscription creation requires a first payment date.",
            retry_disposition=RetryDisposition.NON_RETRYABLE,
            idempotency_key=request.idempotency_key,
        )
    return _validate_subscription_commercial_fields(
        provider_account=provider_account,
        amount=request.amount,
        amount_minor=request.amount_minor,
        currency=request.currency,
        interval_unit=request.interval_unit,
        interval_count=request.interval_count,
        max_periods=request.max_periods,
        idempotency_key=request.idempotency_key,
    )


def _validate_update_subscription_request(
    *,
    provider_account: PaymentProviderAccount,
    request: UpdateRecurringSubscriptionRequest,
) -> OperationResultMeta | None:
    if not _has_subscription_update_patch(request):
        return failed_meta(
            code="recurring_update_patch_empty",
            message_safe="Recurring subscription update requires at least one changed field.",
            retry_disposition=RetryDisposition.NON_RETRYABLE,
            idempotency_key=request.idempotency_key,
        )
    amount_error = _validate_optional_subscription_amount(
        amount=request.amount,
        amount_minor=request.amount_minor,
        idempotency_key=request.idempotency_key,
    )
    if amount_error is not None:
        return amount_error

    if request.currency is not None:
        currency_error = _validate_subscription_currency(
            provider_account=provider_account,
            currency=request.currency,
            idempotency_key=request.idempotency_key,
        )
        if currency_error is not None:
            return currency_error
    return _validate_subscription_interval_fields(
        interval_unit=request.interval_unit,
        interval_count=request.interval_count,
        max_periods=request.max_periods,
        idempotency_key=request.idempotency_key,
    )


def _validate_current_subscription_can_be_updated(
    *,
    api_client: CloudPaymentsApiClient,
    request: UpdateRecurringSubscriptionRequest,
) -> OperationResultMeta | None:
    try:
        response = api_client.get_subscription(subscription_id=request.provider_subscription_id)
    except PaymentsError as exc:
        return failed_meta_from_error(exc, idempotency_key=request.idempotency_key)

    if response.model is None:
        return failed_meta(
            code="payments_api_response_validation_error",
            message_safe="CloudPayments subscription lookup response is missing a subscription model.",
            retry_disposition=RetryDisposition.NON_RETRYABLE,
            idempotency_key=request.idempotency_key,
        )

    current_status = _map_subscription_status(response.model.status)
    if current_status not in _MUTABLE_SUBSCRIPTION_STATUSES:
        return failed_meta(
            code="recurring_subscription_terminal",
            message_safe="Recurring subscription update is rejected for a non-mutable provider status.",
            retry_disposition=RetryDisposition.NON_RETRYABLE,
            idempotency_key=request.idempotency_key,
        )
    return None


def _validate_subscription_commercial_fields(
    *,
    provider_account: PaymentProviderAccount,
    amount: Decimal,
    amount_minor: int,
    currency: str,
    interval_unit: str,
    interval_count: int,
    max_periods: int | None,
    idempotency_key: str | None,
) -> OperationResultMeta | None:
    amount_error = _validate_subscription_amount(
        amount=amount,
        amount_minor=amount_minor,
        idempotency_key=idempotency_key,
    )
    if amount_error is not None:
        return amount_error
    currency_error = _validate_subscription_currency(
        provider_account=provider_account,
        currency=currency,
        idempotency_key=idempotency_key,
    )
    if currency_error is not None:
        return currency_error
    return _validate_subscription_interval_fields(
        interval_unit=interval_unit,
        interval_count=interval_count,
        max_periods=max_periods,
        idempotency_key=idempotency_key,
    )


def _validate_optional_subscription_amount(
    *,
    amount: Decimal | None,
    amount_minor: int | None,
    idempotency_key: str | None,
) -> OperationResultMeta | None:
    if amount is None and amount_minor is None:
        return None
    if amount is None or amount_minor is None:
        return failed_meta(
            code="recurring_amount_mismatch",
            message_safe="Recurring subscription amount and amount_minor must be supplied together.",
            retry_disposition=RetryDisposition.NON_RETRYABLE,
            idempotency_key=idempotency_key,
        )
    return _validate_subscription_amount(
        amount=amount,
        amount_minor=amount_minor,
        idempotency_key=idempotency_key,
    )


def _validate_subscription_amount(
    *,
    amount: Decimal,
    amount_minor: int,
    idempotency_key: str | None,
) -> OperationResultMeta | None:
    if amount_minor <= 0 or amount <= Decimal("0"):
        return failed_meta(
            code="recurring_amount_invalid",
            message_safe="Recurring subscription amount must be positive.",
            retry_disposition=RetryDisposition.NON_RETRYABLE,
            idempotency_key=idempotency_key,
        )
    expected_amount_minor = _amount_minor(amount)
    if expected_amount_minor is None or expected_amount_minor != amount_minor:
        return failed_meta(
            code="recurring_amount_mismatch",
            message_safe="Recurring subscription amount and amount_minor must match.",
            retry_disposition=RetryDisposition.NON_RETRYABLE,
            idempotency_key=idempotency_key,
        )
    return None


def _validate_subscription_currency(
    *,
    provider_account: PaymentProviderAccount,
    currency: str,
    idempotency_key: str | None,
) -> OperationResultMeta | None:
    if provider_account.default_currency.strip().upper() == currency.strip().upper():
        return None
    return failed_meta(
        code="recurring_currency_mismatch",
        message_safe="Recurring subscription currency does not match provider account default currency.",
        retry_disposition=RetryDisposition.NON_RETRYABLE,
        idempotency_key=idempotency_key,
    )


def _validate_subscription_interval_fields(
    *,
    interval_unit: str | None,
    interval_count: int | None,
    max_periods: int | None,
    idempotency_key: str | None,
) -> OperationResultMeta | None:
    if interval_unit is not None and _cloudpayments_interval(interval_unit) is None:
        return failed_meta(
            code="recurring_interval_invalid",
            message_safe="Recurring subscription interval is not supported by CloudPayments.",
            retry_disposition=RetryDisposition.NON_RETRYABLE,
            idempotency_key=idempotency_key,
        )
    if interval_count is not None and interval_count <= 0:
        return failed_meta(
            code="recurring_interval_count_invalid",
            message_safe="Recurring subscription interval count must be positive.",
            retry_disposition=RetryDisposition.NON_RETRYABLE,
            idempotency_key=idempotency_key,
        )
    if max_periods is not None and max_periods <= 0:
        return failed_meta(
            code="recurring_max_periods_invalid",
            message_safe="Recurring subscription maximum periods must be positive.",
            retry_disposition=RetryDisposition.NON_RETRYABLE,
            idempotency_key=idempotency_key,
        )
    return None


def _create_subscription_failure_result(
    *,
    provider_code: str,
    provider_account: PaymentProviderAccount,
    request: CreateRecurringSubscriptionRequest,
    meta: OperationResultMeta,
) -> CreateRecurringSubscriptionResult:
    return CreateRecurringSubscriptionResult(
        provider=provider_code,
        provider_account_id=str(provider_account.id),
        provider_subscription_id=None,
        account_id=request.account_id,
        status=RecurringSubscriptionStatus.FAILED,
        amount_minor=request.amount_minor,
        amount=request.amount,
        currency=request.currency,
        interval_unit=request.interval_unit,
        interval_count=request.interval_count,
        meta=meta,
    )


def _update_subscription_failure_result(
    *,
    provider_code: str,
    provider_account: PaymentProviderAccount,
    request: UpdateRecurringSubscriptionRequest,
    meta: OperationResultMeta,
) -> UpdateRecurringSubscriptionResult:
    return UpdateRecurringSubscriptionResult(
        provider=provider_code,
        provider_account_id=str(provider_account.id),
        provider_subscription_id=request.provider_subscription_id,
        status=RecurringSubscriptionStatus.FAILED,
        amount_minor=request.amount_minor,
        amount=request.amount,
        currency=request.currency,
        interval_unit=request.interval_unit,
        interval_count=request.interval_count,
        meta=meta,
    )


def _map_subscription_status(status: str | None) -> RecurringSubscriptionStatus:
    return {
        "Active": RecurringSubscriptionStatus.ACTIVE,
        "PastDue": RecurringSubscriptionStatus.PAST_DUE,
        "Cancelled": RecurringSubscriptionStatus.CANCELED,
        "Rejected": RecurringSubscriptionStatus.FAILED,
        "Expired": RecurringSubscriptionStatus.ENDED,
    }.get(status or "", RecurringSubscriptionStatus.UNKNOWN)


def _cloudpayments_interval(interval_unit: str | None) -> str | None:
    normalized = str(interval_unit or "").strip().casefold()
    return {
        "day": "Day",
        "week": "Week",
        "month": "Month",
    }.get(normalized)


def _normalized_interval_unit(interval_unit: str | None) -> str | None:
    normalized = _cloudpayments_interval(interval_unit)
    return normalized.lower() if normalized is not None else None


def _has_subscription_update_patch(request: UpdateRecurringSubscriptionRequest) -> bool:
    return any(
        value is not None
        for value in (
            request.description,
            request.amount_minor,
            request.amount,
            request.currency,
            request.interval_unit,
            request.interval_count,
            request.require_confirmation,
            request.start_at,
            request.max_periods,
        )
    )


def _amount_minor(amount: Decimal | None) -> int | None:
    if amount is None:
        return None
    scaled = amount * Decimal("100")
    if scaled != scaled.to_integral_value():
        return None
    return int(scaled)
