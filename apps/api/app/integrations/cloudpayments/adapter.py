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
    PaymentsError,
    PaymentsTransportError,
)
from app.core.observability import redact
from app.core.settings import settings
from app.integrations.cloudpayments.api_client import (
    CloudPaymentsApiClient,
    CloudPaymentsTransactionModel,
    build_cloudpayments_api_client,
)
from app.integrations.cloudpayments.contracts import (
    CloudPaymentsWebhookPayload,
    cloudpayments_event_idempotency_key,
)
from app.integrations.cloudpayments.payload import (
    get_first,
    normalized_recurrent_status,
)
from app.models import Order, PaymentProviderAccount
from app.payment_providers.contracts import (
    OperationOutcome,
    OperationResultMeta,
    ProviderFailure,
    RefundRequest,
    RefundResult,
    RefundStatus,
    RetryDisposition,
    CheckoutAction,
    TransactionLookupRequest,
    TransactionLookupResult,
    TransactionStatus,
    NormalizedPaymentEvent,
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
        account_error = self._validate_provider_account_context(provider_account=provider_account)
        if account_error is not None:
            return TransactionLookupResult(
                provider=self.provider_code,
                provider_account_id=str(provider_account.id),
                provider_payment_id=request.provider_payment_id,
                provider_invoice_id=request.provider_invoice_id,
                merchant_order_id=request.merchant_order_id,
                status=TransactionStatus.UNKNOWN,
                amount_minor=None,
                amount=None,
                currency=None,
                meta=account_error,
            )

        provider_transaction_id = self._provider_transaction_id(request.provider_payment_id)
        if provider_transaction_id is None:
            return TransactionLookupResult(
                provider=self.provider_code,
                provider_account_id=str(provider_account.id),
                provider_payment_id=request.provider_payment_id,
                provider_invoice_id=request.provider_invoice_id,
                merchant_order_id=request.merchant_order_id,
                status=TransactionStatus.UNKNOWN,
                amount_minor=None,
                amount=None,
                currency=None,
                meta=self._failed_meta(
                    code="cloudpayments_transaction_id_required",
                    message_safe="CloudPayments lookup requires provider_payment_id as TransactionId.",
                    retry_disposition=RetryDisposition.NON_RETRYABLE,
                ),
            )
        try:
            response = self._api_client.get_transaction(transaction_id=provider_transaction_id)
        except PaymentsError as exc:
            return TransactionLookupResult(
                provider=self.provider_code,
                provider_account_id=str(provider_account.id),
                provider_payment_id=request.provider_payment_id,
                provider_invoice_id=request.provider_invoice_id,
                merchant_order_id=request.merchant_order_id,
                status=TransactionStatus.UNKNOWN,
                amount_minor=None,
                amount=None,
                currency=None,
                meta=self._failed_meta_from_error(exc),
            )

        model = response.model
        if model is None:
            return TransactionLookupResult(
                provider=self.provider_code,
                provider_account_id=str(provider_account.id),
                provider_payment_id=request.provider_payment_id,
                provider_invoice_id=request.provider_invoice_id,
                merchant_order_id=request.merchant_order_id,
                status=TransactionStatus.UNKNOWN,
                amount_minor=None,
                amount=None,
                currency=None,
                meta=self._failed_meta(
                    code="cloudpayments_transaction_lookup_missing_model",
                    message_safe="CloudPayments transaction lookup returned no model.",
                    retry_disposition=RetryDisposition.NON_RETRYABLE,
                ),
            )

        if provider_account.public_identifier and model.public_id:
            if provider_account.public_identifier.strip() != model.public_id.strip():
                return TransactionLookupResult(
                    provider=self.provider_code,
                    provider_account_id=str(provider_account.id),
                    provider_payment_id=request.provider_payment_id,
                    provider_invoice_id=request.provider_invoice_id,
                    merchant_order_id=request.merchant_order_id,
                    status=TransactionStatus.UNKNOWN,
                    amount_minor=None,
                    amount=None,
                    currency=None,
                    meta=self._failed_meta(
                        code="cloudpayments_public_id_mismatch",
                        message_safe="CloudPayments transaction belongs to a different provider account.",
                        retry_disposition=RetryDisposition.NON_RETRYABLE,
                    ),
                )

        return TransactionLookupResult(
            provider=self.provider_code,
            provider_account_id=str(provider_account.id),
            provider_payment_id=str(model.transaction_id),
            provider_invoice_id=model.invoice_id or request.provider_invoice_id,
            merchant_order_id=request.merchant_order_id,
            status=self._map_transaction_status(model),
            amount_minor=self._amount_minor(model.payment_amount or model.amount),
            amount=model.payment_amount or model.amount,
            currency=model.payment_currency or model.currency,
            meta=self._succeeded_meta(),
        )

    def refund_payment(
        self,
        *,
        provider_account: PaymentProviderAccount,
        request: RefundRequest,
    ) -> RefundResult:
        account_error = self._validate_provider_account_context(provider_account=provider_account)
        if account_error is not None:
            return RefundResult(
                provider=self.provider_code,
                provider_account_id=str(provider_account.id),
                provider_payment_id=request.provider_payment_id,
                provider_refund_id=None,
                status=RefundStatus.FAILED,
                amount_minor=request.amount_minor,
                amount=request.amount,
                currency=request.currency,
                meta=account_error,
            )

        if provider_account.default_currency.strip().upper() != request.currency.strip().upper():
            return RefundResult(
                provider=self.provider_code,
                provider_account_id=str(provider_account.id),
                provider_payment_id=request.provider_payment_id,
                provider_refund_id=None,
                status=RefundStatus.FAILED,
                amount_minor=request.amount_minor,
                amount=request.amount,
                currency=request.currency,
                meta=self._failed_meta(
                    code="refund_currency_mismatch",
                    message_safe="Refund currency does not match provider account default currency.",
                    retry_disposition=RetryDisposition.NON_RETRYABLE,
                    idempotency_key=request.idempotency_key,
                ),
            )

        if request.amount_minor <= 0 or request.amount <= Decimal("0"):
            return RefundResult(
                provider=self.provider_code,
                provider_account_id=str(provider_account.id),
                provider_payment_id=request.provider_payment_id,
                provider_refund_id=None,
                status=RefundStatus.FAILED,
                amount_minor=request.amount_minor,
                amount=request.amount,
                currency=request.currency,
                meta=self._failed_meta(
                    code="refund_amount_invalid",
                    message_safe="Refund amount must be positive.",
                    retry_disposition=RetryDisposition.NON_RETRYABLE,
                    idempotency_key=request.idempotency_key,
                ),
            )

        provider_transaction_id = self._provider_transaction_id(request.provider_payment_id)
        if provider_transaction_id is None:
            return RefundResult(
                provider=self.provider_code,
                provider_account_id=str(provider_account.id),
                provider_payment_id=request.provider_payment_id,
                provider_refund_id=None,
                status=RefundStatus.FAILED,
                amount_minor=request.amount_minor,
                amount=request.amount,
                currency=request.currency,
                meta=self._failed_meta(
                    code="cloudpayments_transaction_id_required",
                    message_safe="CloudPayments refund requires provider_payment_id as TransactionId.",
                    retry_disposition=RetryDisposition.NON_RETRYABLE,
                    idempotency_key=request.idempotency_key,
                ),
            )

        expected_amount_minor = self._amount_minor(request.amount)
        if expected_amount_minor is None or expected_amount_minor != request.amount_minor:
            return RefundResult(
                provider=self.provider_code,
                provider_account_id=str(provider_account.id),
                provider_payment_id=request.provider_payment_id,
                provider_refund_id=None,
                status=RefundStatus.FAILED,
                amount_minor=request.amount_minor,
                amount=request.amount,
                currency=request.currency,
                meta=self._failed_meta(
                    code="refund_amount_mismatch",
                    message_safe="Refund amount and amount_minor must match.",
                    retry_disposition=RetryDisposition.NON_RETRYABLE,
                    idempotency_key=request.idempotency_key,
                ),
            )

        json_data = {"reason": request.reason} if request.reason else None
        try:
            response = self._api_client.refund(
                transaction_id=provider_transaction_id,
                amount=request.amount,
                json_data=json_data,
                idempotency_key=request.idempotency_key,
            )
        except PaymentsError as exc:
            return RefundResult(
                provider=self.provider_code,
                provider_account_id=str(provider_account.id),
                provider_payment_id=request.provider_payment_id,
                provider_refund_id=None,
                status=RefundStatus.FAILED,
                amount_minor=request.amount_minor,
                amount=request.amount,
                currency=request.currency,
                meta=self._failed_meta_from_error(exc, idempotency_key=request.idempotency_key),
            )

        return RefundResult(
            provider=self.provider_code,
            provider_account_id=str(provider_account.id),
            provider_payment_id=request.provider_payment_id,
            provider_refund_id=str(response.model.transaction_id) if response.model is not None else None,
            status=RefundStatus.PENDING,
            amount_minor=request.amount_minor,
            amount=request.amount,
            currency=request.currency,
            meta=self._succeeded_meta(idempotency_key=request.idempotency_key),
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


    def _provider_transaction_id(self, value: str | None) -> int | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or not normalized.isdigit():
            return None
        return int(normalized)

    def _map_transaction_status(self, model: CloudPaymentsTransactionModel) -> TransactionStatus:
        normalized_status = str(model.status or "").strip().lower().replace("-", "_")
        if normalized_status == "authorized":
            return TransactionStatus.AUTHORIZED
        if normalized_status in {"completed", "succeeded", "success"}:
            return TransactionStatus.SUCCEEDED
        if normalized_status in {"cancelled", "canceled"}:
            return TransactionStatus.CANCELED
        if normalized_status in {"declined", "failed", "rejected"}:
            return TransactionStatus.FAILED
        if normalized_status == "refunded":
            return TransactionStatus.REFUNDED
        if normalized_status in {"pending", "created", "in_progress"}:
            return TransactionStatus.PENDING
        if normalized_recurrent_status(normalized_status) == "unknown" and model.reason_code == 0:
            return TransactionStatus.UNKNOWN
        return TransactionStatus.UNKNOWN

    def _validate_provider_account_context(
        self,
        *,
        provider_account: PaymentProviderAccount,
    ) -> OperationResultMeta | None:
        if provider_account.provider != self.provider_code:
            return self._failed_meta(
                code="provider_account_invalid_provider",
                message_safe="Selected provider account does not belong to CloudPayments.",
                retry_disposition=RetryDisposition.NON_RETRYABLE,
            )
        if not provider_account.enabled:
            return self._failed_meta(
                code="provider_account_disabled",
                message_safe="Selected provider account is disabled.",
                retry_disposition=RetryDisposition.NON_RETRYABLE,
            )
        return None

    def _succeeded_meta(self, *, idempotency_key: str | None = None) -> OperationResultMeta:
        return OperationResultMeta(
            outcome=OperationOutcome.SUCCEEDED,
            retry_disposition=RetryDisposition.NON_RETRYABLE,
            idempotency_key=idempotency_key,
        )

    def _failed_meta(
        self,
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

    def _failed_meta_from_error(
        self,
        error: PaymentsError,
        *,
        idempotency_key: str | None = None,
    ) -> OperationResultMeta:
        retry_disposition = (
            error.retry_disposition
            if isinstance(error, PaymentsTransportError)
            else RetryDisposition.NON_RETRYABLE
        )
        return self._failed_meta(
            code=error.code,
            message_safe=error.message_safe,
            retry_disposition=retry_disposition,
            idempotency_key=idempotency_key,
        )

    def _amount_minor(self, amount: Decimal | None) -> int | None:
        if amount is None:
            return None
        return int((amount * Decimal("100")).quantize(Decimal("1")))


cloudpayments_adapter = CloudPaymentsAdapter(api_client=build_cloudpayments_api_client())
