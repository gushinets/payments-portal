from __future__ import annotations

import base64
import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs

from fastapi import Request

from app.core.errors import (
    PaymentProviderConfigurationError,
)
from app.core.observability import redact
from app.core.settings import settings
from app.integrations.cloudpayments.api_client import (
    CloudPaymentsApiClient,
    build_cloudpayments_api_client,
)
from app.integrations.cloudpayments.contracts import (
    CloudPaymentsWebhookPayload,
    cloudpayments_event_idempotency_key,
)
from app.integrations.cloudpayments.payload import get_first
from app.integrations.cloudpayments.account_validation import validate_provider_account_context
from app.integrations.cloudpayments.operation_meta import failed_meta, failed_meta_from_error, succeeded_meta
from app.integrations.cloudpayments.recurring import (
    cancel_recurring_subscription as cancel_cloudpayments_recurring_subscription,
    create_recurring_subscription as create_cloudpayments_recurring_subscription,
    update_recurring_subscription as update_cloudpayments_recurring_subscription,
)
from app.integrations.cloudpayments.refunds import refund_payment as refund_cloudpayments_payment
from app.integrations.cloudpayments.transaction_lookup import lookup_transaction as lookup_cloudpayments_transaction
from app.models import Order, PaymentProviderAccount
from app.payment_providers.contracts import (
    CancelRecurringSubscriptionRequest,
    CancelRecurringSubscriptionResult,
    RefundRequest,
    RefundResult,
    CheckoutAction,
    CreateRecurringSubscriptionRequest,
    CreateRecurringSubscriptionResult,
    TransactionLookupRequest,
    TransactionLookupResult,
    NormalizedPaymentEvent,
    UpdateRecurringSubscriptionRequest,
    UpdateRecurringSubscriptionResult,
)

CLOUDPAYMENTS_PROVIDER_CODE = "cloudpayments"
SUPPORTED_ENDPOINTS = {
    "check",
    "pay",
    "fail",
    "refund",
    "recurrent",
    "confirm",
    "cancel",
}
CARD_DATA_KEYS = {
    "cardcryptogrampacket",
    "cardholdermessage",
    "cardfirstsix",
    "cardlastfour",
    "cardtype",
    "cardexpdate",
    "cardproduct",
    "cryptogram",
    "cvv",
    "cvc",
    "pan",
    "token",
}
CLOUDPAYMENTS_RESPONSE_CODES = {
    "order_not_found": 10,
    "missing_account_id": 11,
    "account_mismatch": 11,
    "missing_amount": 12,
    "amount_mismatch": 12,
    "missing_currency": 12,
    "currency_mismatch": 12,
    "missing_transaction_id": 13,
    "order_expired": 20,
    "payload_parse_error": 13,
    "payment_not_found": 13,
    "payment_not_refundable": 13,
    "payment_schema_mismatch": 13,
    "provider_account_not_found": 13,
    "missing_subscription_id": 13,
    "missing_subscription_description": 13,
    "missing_subscription_email": 13,
    "missing_subscription_status": 13,
    "invalid_subscription_status": 13,
    "normalization_unexpected_error": 13,
    "invalid_cloudpayments_signature": 13,
}


def _flatten_form_payload(raw_body: bytes) -> dict[str, Any]:
    parsed = parse_qs(raw_body.decode("utf-8"), keep_blank_values=True)
    return {key: values[0] if len(values) == 1 else values for key, values in parsed.items()}


async def _parse_payload(request: Request, raw_body: bytes) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        if not raw_body:
            return {}
        payload = json.loads(raw_body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload_not_object")
        return payload
    return _flatten_form_payload(raw_body)


def _safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _safe_payload(value)
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    return value


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in CARD_DATA_KEYS:
            safe[key] = "[redacted]"
        else:
            safe[key] = _safe_value(value)
    return safe


def _payload_hash(raw_body: bytes, payload: dict[str, Any]) -> str:
    if raw_body:
        return hashlib.sha256(raw_body).hexdigest()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_amount(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _amount_minor(amount: Decimal | None) -> int | None:
    if amount is None:
        return None
    return int((amount * Decimal("100")).quantize(Decimal("1")))


def _event_idempotency_key(
    endpoint: str,
    provider_event_id: str | None,
    invoice_id: str | None,
    transaction_id: str | None,
    refund_id: str | None,
    payload_hash: str,
) -> str:
    return cloudpayments_event_idempotency_key(
        endpoint,
        provider_event_id,
        invoice_id,
        transaction_id,
        refund_id,
        payload_hash,
    )


def verify_cloudpayments_signature(raw_body: bytes, headers: dict[str, str]) -> bool:
    if not settings.cloudpayments_api_secret:
        return False

    signature = (
        headers.get("content-hmac")
        or headers.get("x-content-hmac")
        or headers.get("Content-HMAC")
        or headers.get("X-Content-HMAC")
    )
    if not signature:
        return False

    digest = hmac.new(
        settings.cloudpayments_api_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(digest)
    return hmac.compare_digest(signature.encode("utf-8"), expected)


class CloudPaymentsAdapter:
    provider_code = CLOUDPAYMENTS_PROVIDER_CODE

    def __init__(self, *, api_client: CloudPaymentsApiClient) -> None:
        self._api_client = api_client

    def default_account_fields(self, *, tenant_id: str, region: str) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "region": region,
            "provider": self.provider_code,
            "public_identifier": settings.cloudpayments_public_id or None,
            "default_currency": "RUB",
            "enabled": True,
            "test_mode": True,
            "config": {"widget_mode": "charge", "receipt_mode": "deferred"},
        }

    def prepare_checkout_action(
        self,
        *,
        provider_account: PaymentProviderAccount,
        order: Order,
        account_id: str,
        description: str | None,
        metadata: dict[str, Any],
    ) -> CheckoutAction:
        mode = str(provider_account.config.get("widget_mode") or "charge")
        if mode not in {"charge", "auth"}:
            raise PaymentProviderConfigurationError("cloudpayments_widget_mode_invalid")
        public_identifier = provider_account.public_identifier or settings.cloudpayments_public_id or None
        if public_identifier is None or not public_identifier.strip():
            raise PaymentProviderConfigurationError("cloudpayments_public_terminal_id_missing")
        return CheckoutAction(
            provider=self.provider_code,
            experience="widget",
            mode=mode,
            public_identifier=public_identifier,
            amount_minor=order.amount_minor,
            amount=(Decimal(order.amount_minor) / Decimal("100")).quantize(Decimal("0.01")),
            currency=order.currency,
            merchant_order_id=order.merchant_order_id,
            provider_invoice_id=order.provider_invoice_id or order.merchant_order_id,
            account_id=account_id,
            description=description,
            metadata=metadata,
        )

    def lookup_transaction(
        self,
        *,
        provider_account: PaymentProviderAccount,
        request: TransactionLookupRequest,
    ) -> TransactionLookupResult:
        account_error = validate_provider_account_context(
            provider_account=provider_account,
            provider_code=self.provider_code,
            configured_public_id=self._api_client.config.public_id,
        )
        return lookup_cloudpayments_transaction(
            api_client=self._api_client,
            provider_account=provider_account,
            request=request,
            provider_code=self.provider_code,
            account_error=account_error,
            failed_meta=failed_meta,
            failed_meta_from_error=failed_meta_from_error,
            succeeded_meta=succeeded_meta,
        )

    def refund_payment(
        self,
        *,
        provider_account: PaymentProviderAccount,
        request: RefundRequest,
    ) -> RefundResult:
        return refund_cloudpayments_payment(
            api_client=self._api_client,
            provider_code=self.provider_code,
            provider_account=provider_account,
            request=request,
        )

    def create_recurring_subscription(
        self,
        *,
        provider_account: PaymentProviderAccount,
        request: CreateRecurringSubscriptionRequest,
    ) -> CreateRecurringSubscriptionResult:
        return create_cloudpayments_recurring_subscription(
            api_client=self._api_client,
            provider_code=self.provider_code,
            provider_account=provider_account,
            request=request,
        )

    def update_recurring_subscription(
        self,
        *,
        provider_account: PaymentProviderAccount,
        request: UpdateRecurringSubscriptionRequest,
    ) -> UpdateRecurringSubscriptionResult:
        return update_cloudpayments_recurring_subscription(
            api_client=self._api_client,
            provider_code=self.provider_code,
            provider_account=provider_account,
            request=request,
        )

    def cancel_recurring_subscription(
        self,
        *,
        provider_account: PaymentProviderAccount,
        request: CancelRecurringSubscriptionRequest,
    ) -> CancelRecurringSubscriptionResult:
        return cancel_cloudpayments_recurring_subscription(
            api_client=self._api_client,
            provider_code=self.provider_code,
            provider_account=provider_account,
            request=request,
        )

    async def normalize_webhook_request(
        self,
        *,
        endpoint: str,
        request: Request,
        raw_body: bytes,
    ) -> NormalizedPaymentEvent:
        headers = dict(request.headers)
        status = None
        error_message = None
        try:
            payload = await _parse_payload(request, raw_body)
        except Exception as exc:
            payload = {"_raw": "[omitted: payload_parse_error]"}
            status = "payload_parse_error"
            error_message = f"payload_parse_error: {type(exc).__name__}"

        verified = verify_cloudpayments_signature(raw_body, headers)
        if not verified:
            status = "invalid_cloudpayments_signature"
            error_message = "invalid_cloudpayments_signature"

        amount = _parse_amount(get_first(payload, "Amount", "amount"))
        amount_minor = _amount_minor(amount)
        payload_hash = _payload_hash(raw_body, payload)
        safe_payload = _safe_payload(payload)
        return CloudPaymentsWebhookPayload.model_validate(payload).to_normalized_event(
            endpoint=endpoint,
            payload_hash=payload_hash,
            safe_payload=safe_payload,
            safe_headers=redact(headers),
            verified=verified,
            amount_minor=amount_minor,
            amount=amount,
            error_code=status,
            error_message=error_message,
        )

    def webhook_success_response(self, event: NormalizedPaymentEvent) -> dict[str, Any]:
        return self.webhook_event_response(
            endpoint=event.endpoint,
            error_code=event.error_code,
        )

    def webhook_event_response(
        self,
        *,
        endpoint: str,
        error_code: str | None,
        event_status: str | None = None,
    ) -> dict[str, Any]:
        return {
            "code": self.webhook_response_code(
                endpoint=endpoint,
                error_code=error_code,
                event_status=event_status,
            )
        }

    def webhook_response_code(
        self,
        *,
        endpoint: str,
        error_code: str | None,
        event_status: str | None = None,
    ) -> int:
        if error_code is None or event_status in {"processed", "ignored", "duplicate"}:
            return 0
        if endpoint != "check":
            return 0
        return CLOUDPAYMENTS_RESPONSE_CODES.get(error_code, 13)


cloudpayments_adapter = CloudPaymentsAdapter(api_client=build_cloudpayments_api_client())
