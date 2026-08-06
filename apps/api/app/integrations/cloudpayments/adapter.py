from __future__ import annotations

import base64
import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs

from fastapi import Request

from app.core.observability import redact
from app.core.settings import settings
from app.models import Order, PaymentProviderAccount
from app.payment_providers.contracts import (
    CheckoutAction,
    NormalizedPaymentEvent,
    PaymentProviderConfigurationError,
)

CLOUDPAYMENTS_PROVIDER_CODE = "cloudpayments"
SUPPORTED_ENDPOINTS = {"check", "pay", "fail", "refund", "recurrent", "confirm", "cancel"}
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
EVENT_TYPES_BY_ENDPOINT = {
    "check": "payment.check",
    "pay": "payment.succeeded",
    "fail": "payment.failed",
    "refund": "payment.refunded",
    "confirm": "payment.confirmed",
    "cancel": "payment.canceled",
    "recurrent": "subscription.updated",
}
CLOUDPAYMENTS_RESPONSE_CODES = {
    "order_not_found": 10,
    "missing_account_id": 11,
    "account_mismatch": 11,
    "missing_amount": 12,
    "amount_mismatch": 12,
    "missing_currency": 12,
    "currency_mismatch": 12,
    "order_expired": 20,
    "payload_parse_error": 13,
    "payment_not_found": 13,
    "normalization_unexpected_error": 13,
    "invalid_cloudpayments_signature": 13,
}


def _flatten_form_payload(raw_body: bytes) -> dict[str, Any]:
    parsed = parse_qs(raw_body.decode("utf-8"), keep_blank_values=True)
    return {
        key: values[0] if len(values) == 1 else values
        for key, values in parsed.items()
    }


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


def _get_first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


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


def _provider_event_id(payload: dict[str, Any]) -> str | None:
    value = _get_first(
        payload,
        "EventId",
        "eventId",
        "NotificationId",
        "notificationId",
        "Id",
        "id",
    )
    return str(value) if value is not None else None


def _event_idempotency_key(
    endpoint: str,
    provider_event_id: str | None,
    invoice_id: str | None,
    transaction_id: str | None,
    refund_id: str | None,
    payload_hash: str,
) -> str:
    if provider_event_id:
        return f"{CLOUDPAYMENTS_PROVIDER_CODE}:event:{provider_event_id}"
    if endpoint == "refund" and refund_id:
        return f"{CLOUDPAYMENTS_PROVIDER_CODE}:refund:{refund_id}"
    if transaction_id:
        return f"{CLOUDPAYMENTS_PROVIDER_CODE}:{endpoint}:transaction:{transaction_id}"
    if invoice_id:
        return f"{CLOUDPAYMENTS_PROVIDER_CODE}:{endpoint}:invoice:{invoice_id}:{payload_hash}"
    return f"{CLOUDPAYMENTS_PROVIDER_CODE}:{endpoint}:payload:{payload_hash}"


def verify_cloudpayments_signature(raw_body: bytes, headers: dict[str, str]) -> bool:
    if not settings.cloudpayments_api_secret:
        return not settings.cloudpayments_enabled

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

    def default_account_fields(self, *, tenant_id: str, region: str) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "region": region,
            "provider": self.provider_code,
            "public_identifier": None,
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
        if mode != "charge":
            raise PaymentProviderConfigurationError(
                "cloudpayments_one_stage_charge_required"
            )
        public_identifier = (
            provider_account.public_identifier or settings.cloudpayments_public_id or None
        )
        if public_identifier is None or not public_identifier.strip():
            raise PaymentProviderConfigurationError(
                "cloudpayments_public_terminal_id_missing"
            )
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

        invoice_id = _get_first(payload, "InvoiceId", "invoiceId", "invoice_id")
        transaction_id = _get_first(payload, "TransactionId", "transactionId", "transaction_id")
        refund_id = _get_first(payload, "RefundId", "refundId", "refund_id")
        amount = _parse_amount(_get_first(payload, "Amount", "amount"))
        amount_minor = _amount_minor(amount)
        currency = _get_first(payload, "Currency", "currency")
        provider_event_id = _provider_event_id(payload)
        payload_hash = _payload_hash(raw_body, payload)

        return NormalizedPaymentEvent(
            endpoint=endpoint,
            event_type=EVENT_TYPES_BY_ENDPOINT.get(endpoint, endpoint),
            provider_event_id=provider_event_id,
            idempotency_key=_event_idempotency_key(
                endpoint,
                provider_event_id,
                str(invoice_id) if invoice_id is not None else None,
                str(transaction_id) if transaction_id is not None else None,
                str(refund_id) if refund_id is not None else None,
                payload_hash,
            ),
            payload_hash=payload_hash,
            invoice_id=str(invoice_id) if invoice_id is not None else None,
            transaction_id=str(transaction_id) if transaction_id is not None else None,
            refund_id=str(refund_id) if refund_id is not None else None,
            account_id=_get_first(payload, "AccountId", "accountId", "account_id"),
            amount_minor=amount_minor,
            amount=amount,
            currency=str(currency) if currency is not None else None,
            safe_payload=_safe_payload(payload),
            safe_headers=redact(headers),
            verified=verified,
            error_code=status,
            error_message=error_message,
        )

    def webhook_success_response(self, event: NormalizedPaymentEvent) -> dict[str, Any]:
        return {"code": self.webhook_response_code(error_code=event.error_code)}

    def webhook_event_response(self, *, error_code: str | None) -> dict[str, Any]:
        return {"code": self.webhook_response_code(error_code=error_code)}

    def webhook_response_code(self, *, error_code: str | None) -> int:
        if error_code is None:
            return 0
        return CLOUDPAYMENTS_RESPONSE_CODES.get(error_code, 13)


cloudpayments_adapter = CloudPaymentsAdapter()
