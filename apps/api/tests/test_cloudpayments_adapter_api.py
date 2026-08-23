from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from apps.api.tests.support.settings import configure_api_test_environment

configure_api_test_environment()

from app.integrations.cloudpayments.adapter import CloudPaymentsAdapter  # noqa: E402
from app.integrations.cloudpayments.api_client import (  # noqa: E402
    CloudPaymentsApiClient,
    CloudPaymentsApiClientConfig,
)
from app.payment_providers.contracts import (  # noqa: E402
    CancelRecurringSubscriptionRequest,
    CreateRecurringSubscriptionRequest,
    RefundRequest,
    RefundStatus,
    RecurringSubscriptionStatus,
    TransactionLookupRequest,
    TransactionStatus,
    UpdateRecurringSubscriptionRequest,
)


def _provider_account() -> object:
    class _ProviderAccount:
        id = uuid4()
        provider = "cloudpayments"
        enabled = True
        public_identifier = "pk_test"
        default_currency = "RUB"
        config = {}

    return _ProviderAccount()


def _adapter_with_transport(handler: httpx.MockTransport) -> CloudPaymentsAdapter:
    return CloudPaymentsAdapter(
        api_client=CloudPaymentsApiClient(
            config=CloudPaymentsApiClientConfig(
                base_url="https://api.cloudpayments.ru",
                public_id="pk_test",
                api_secret="secret_test",
                max_retries=0,
            ),
            transport=handler,
        )
    )


def _create_subscription_request(**overrides: object) -> CreateRecurringSubscriptionRequest:
    values = {
        "payment_method_reference": "tk_test",
        "account_id": "user_1",
        "description": "Monthly plan",
        "amount_minor": 39900,
        "amount": Decimal("399.00"),
        "currency": "RUB",
        "interval_unit": "month",
        "interval_count": 1,
        "require_confirmation": False,
        "email": "user@example.com",
        "start_at": "2026-09-22T00:00:00Z",
        "max_periods": 12,
        "idempotency_key": "sub-create-1",
    }
    values.update(overrides)
    return CreateRecurringSubscriptionRequest.model_validate(values)


def test_cloudpayments_adapter_lookup_transaction_maps_completed_to_succeeded() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/payments/get"
        return httpx.Response(
            200,
            json={
                "Success": True,
                "Message": None,
                "Model": {
                    "PublicId": "pk_test",
                    "TransactionId": 897749645,
                    "InvoiceId": "inv-1",
                    "OperationType": "Payment",
                    "Status": "Completed",
                    "ReasonCode": 0,
                    "Amount": 159,
                    "Currency": "RUB",
                    "PaymentAmount": 159,
                    "PaymentCurrency": "RUB",
                },
            },
        )

    adapter = CloudPaymentsAdapter(
        api_client=CloudPaymentsApiClient(
            config=CloudPaymentsApiClientConfig(
                base_url="https://api.cloudpayments.ru",
                public_id="pk_test",
                api_secret="secret_test",
                max_retries=0,
            ),
            transport=httpx.MockTransport(handler),
        )
    )

    result = adapter.lookup_transaction(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=TransactionLookupRequest(
            provider_payment_id="897749645",
            provider_invoice_id="inv-1",
            merchant_order_id="merchant-1",
            expected_amount_minor=15900,
            expected_currency="RUB",
        ),
    )

    assert result.provider == "cloudpayments"
    assert result.provider_payment_id == "897749645"
    assert result.provider_invoice_id == "inv-1"
    assert result.status == TransactionStatus.SUCCEEDED
    assert result.amount_minor == 15900
    assert result.currency == "RUB"
    assert result.meta.outcome.value == "succeeded"


def test_cloudpayments_adapter_lookup_transaction_maps_declined_model_to_failed() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/payments/find"
        return httpx.Response(
            200,
            json={
                "Success": False,
                "Message": None,
                "Model": {
                    "PublicId": "pk_test",
                    "TransactionId": 897749645,
                    "InvoiceId": "inv-1",
                    "OperationType": "Payment",
                    "Status": "Declined",
                    "ReasonCode": 5051,
                    "Amount": 159,
                    "Currency": "RUB",
                    "PaymentAmount": 159,
                    "PaymentCurrency": "RUB",
                },
            },
        )

    adapter = _adapter_with_transport(httpx.MockTransport(handler))

    result = adapter.lookup_transaction(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=TransactionLookupRequest(
            provider_invoice_id="inv-1",
            merchant_order_id="merchant-1",
            expected_amount_minor=15900,
            expected_currency="RUB",
        ),
    )

    assert result.provider_payment_id == "897749645"
    assert result.provider_invoice_id == "inv-1"
    assert result.status == TransactionStatus.FAILED
    assert result.amount_minor == 15900
    assert result.currency == "RUB"
    assert result.meta.outcome.value == "succeeded"


def test_cloudpayments_adapter_lookup_transaction_maps_awaiting_authentication_to_pending() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/payments/get"
        return httpx.Response(
            200,
            json={
                "Success": True,
                "Message": None,
                "Model": {
                    "PublicId": "pk_test",
                    "TransactionId": 897749645,
                    "InvoiceId": "inv-1",
                    "OperationType": "Payment",
                    "Status": "AwaitingAuthentication",
                    "Amount": 159,
                    "Currency": "RUB",
                    "PaymentAmount": 159,
                    "PaymentCurrency": "RUB",
                },
            },
        )

    adapter = _adapter_with_transport(httpx.MockTransport(handler))

    result = adapter.lookup_transaction(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=TransactionLookupRequest(
            provider_payment_id="897749645",
            provider_invoice_id="inv-1",
            expected_amount_minor=15900,
            expected_currency="RUB",
        ),
    )

    assert result.status == TransactionStatus.PENDING
    assert result.meta.outcome.value == "succeeded"


def test_cloudpayments_adapter_lookup_uses_order_amount_when_settlement_fields_differ() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/payments/get"
        return httpx.Response(
            200,
            json={
                "Success": True,
                "Message": None,
                "Model": {
                    "PublicId": "pk_test",
                    "TransactionId": 897749645,
                    "InvoiceId": "inv-1",
                    "OperationType": "Payment",
                    "Status": "Completed",
                    "Amount": 159,
                    "Currency": "RUB",
                    "PaymentAmount": 2,
                    "PaymentCurrency": "USD",
                },
            },
        )

    adapter = _adapter_with_transport(httpx.MockTransport(handler))

    result = adapter.lookup_transaction(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=TransactionLookupRequest(
            provider_payment_id="897749645",
            provider_invoice_id="inv-1",
            expected_amount_minor=15900,
            expected_currency="RUB",
        ),
    )

    assert result.status == TransactionStatus.SUCCEEDED
    assert result.amount_minor == 15900
    assert result.currency == "RUB"
    assert result.meta.outcome.value == "succeeded"


def test_cloudpayments_adapter_lookup_transaction_fallback_maps_upstream_failure() -> None:
    provider_account = _provider_account()
    adapter = CloudPaymentsAdapter(
        api_client=CloudPaymentsApiClient(
            config=CloudPaymentsApiClientConfig(
                base_url="https://api.cloudpayments.ru",
                public_id="pk_test",
                api_secret="secret_test",
                max_retries=0,
            ),
            transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        )
    )

    result = adapter.lookup_transaction(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=TransactionLookupRequest(
            provider_invoice_id="inv-1",
            merchant_order_id="merchant-1",
            expected_amount_minor=15900,
            expected_currency="RUB",
        ),
    )

    assert result.status == TransactionStatus.UNKNOWN
    assert result.meta.outcome.value == "failed"
    assert result.meta.retry_disposition.value == "retryable"
    assert result.meta.failure is not None
    assert result.meta.failure.code == "payments_api_upstream_error"
    assert result.provider_payment_id is None
    assert result.provider_invoice_id is None


def test_cloudpayments_adapter_lookup_transaction_falls_back_to_invoice_id() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/payments/find"
        return httpx.Response(
            200,
            json={
                "Success": True,
                "Message": None,
                "Model": {
                    "PublicId": "pk_test",
                    "TransactionId": 897749645,
                    "InvoiceId": "inv-1",
                    "OperationType": "Payment",
                    "Status": "Completed",
                    "Amount": 159,
                    "Currency": "RUB",
                    "PaymentAmount": 159,
                    "PaymentCurrency": "RUB",
                },
            },
        )

    adapter = CloudPaymentsAdapter(
        api_client=CloudPaymentsApiClient(
            config=CloudPaymentsApiClientConfig(
                base_url="https://api.cloudpayments.ru",
                public_id="pk_test",
                api_secret="secret_test",
                max_retries=0,
            ),
            transport=httpx.MockTransport(handler),
        )
    )

    result = adapter.lookup_transaction(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=TransactionLookupRequest(
            provider_invoice_id="inv-1",
            merchant_order_id="merchant-1",
            expected_amount_minor=15900,
            expected_currency="RUB",
        ),
    )

    assert result.provider_payment_id == "897749645"
    assert result.provider_invoice_id == "inv-1"
    assert result.status == TransactionStatus.SUCCEEDED
    assert result.meta.outcome.value == "succeeded"


def test_cloudpayments_adapter_lookup_transaction_maps_not_found_to_safe_unknown() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/payments/get"
        return httpx.Response(200, json={"Success": False, "Message": "Not found"})

    adapter = _adapter_with_transport(httpx.MockTransport(handler))

    result = adapter.lookup_transaction(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=TransactionLookupRequest(
            provider_payment_id="897749645",
            provider_invoice_id="inv-1",
            expected_amount_minor=15900,
            expected_currency="RUB",
        ),
    )

    assert result.status == TransactionStatus.UNKNOWN
    assert result.provider_payment_id is None
    assert result.provider_invoice_id is None
    assert result.meta.failure is not None
    assert result.meta.failure.code == "cloudpayments_payment_not_found"
    assert result.meta.failure.message_safe == "CloudPayments transaction was not found."


def test_cloudpayments_adapter_lookup_rejects_amount_mismatch() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "Success": True,
                "Message": None,
                "Model": {
                    "PublicId": "pk_test",
                    "TransactionId": 897749645,
                    "InvoiceId": "inv-1",
                    "OperationType": "Payment",
                    "Status": "Completed",
                    "Amount": 160,
                    "Currency": "RUB",
                },
            },
        )

    adapter = CloudPaymentsAdapter(
        api_client=CloudPaymentsApiClient(
            config=CloudPaymentsApiClientConfig(
                base_url="https://api.cloudpayments.ru",
                public_id="pk_test",
                api_secret="secret_test",
                max_retries=0,
            ),
            transport=httpx.MockTransport(handler),
        )
    )

    result = adapter.lookup_transaction(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=TransactionLookupRequest(
            provider_invoice_id="inv-1",
            expected_amount_minor=15900,
            expected_currency="RUB",
        ),
    )

    assert result.status == TransactionStatus.UNKNOWN
    assert result.meta.failure is not None
    assert result.meta.failure.code == "cloudpayments_amount_mismatch"
    assert result.provider_payment_id is None


@pytest.mark.parametrize(
    ("model_patch", "expected_code"),
    [
        ({"TransactionId": 897749646}, "cloudpayments_transaction_id_mismatch"),
        ({"InvoiceId": "inv-other"}, "cloudpayments_invoice_id_mismatch"),
        ({"Currency": "USD", "PaymentCurrency": "USD"}, "cloudpayments_currency_mismatch"),
    ],
)
def test_cloudpayments_adapter_lookup_rejects_provider_fact_mismatch(
    model_patch: dict[str, object],
    expected_code: str,
) -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        model: dict[str, object] = {
            "PublicId": "pk_test",
            "TransactionId": 897749645,
            "InvoiceId": "inv-1",
            "OperationType": "Payment",
            "Status": "Completed",
            "Amount": 159,
            "Currency": "RUB",
            "PaymentAmount": 159,
            "PaymentCurrency": "RUB",
        }
        model.update(model_patch)
        return httpx.Response(200, json={"Success": True, "Message": None, "Model": model})

    adapter = CloudPaymentsAdapter(
        api_client=CloudPaymentsApiClient(
            config=CloudPaymentsApiClientConfig(
                base_url="https://api.cloudpayments.ru",
                public_id="pk_test",
                api_secret="secret_test",
                max_retries=0,
            ),
            transport=httpx.MockTransport(handler),
        )
    )

    result = adapter.lookup_transaction(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=TransactionLookupRequest(
            provider_payment_id="897749645",
            provider_invoice_id="inv-1",
            expected_amount_minor=15900,
            expected_currency="RUB",
        ),
    )

    assert result.status == TransactionStatus.UNKNOWN
    assert result.meta.failure is not None
    assert result.meta.failure.code == expected_code
    assert result.provider_payment_id is None


@pytest.mark.parametrize("operation_type", ["Refund", "CardPayout"])
def test_cloudpayments_adapter_lookup_rejects_non_payment_operation(operation_type: str) -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "Success": True,
                "Message": None,
                "Model": {
                    "PublicId": "pk_test",
                    "TransactionId": 897749645,
                    "InvoiceId": "inv-1",
                    "OperationType": operation_type,
                    "Status": "Completed",
                    "Amount": 159,
                    "Currency": "RUB",
                },
            },
        )

    adapter = CloudPaymentsAdapter(
        api_client=CloudPaymentsApiClient(
            config=CloudPaymentsApiClientConfig(
                base_url="https://api.cloudpayments.ru",
                public_id="pk_test",
                api_secret="secret_test",
                max_retries=0,
            ),
            transport=httpx.MockTransport(handler),
        )
    )

    result = adapter.lookup_transaction(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=TransactionLookupRequest(
            provider_invoice_id="inv-1",
            expected_amount_minor=15900,
            expected_currency="RUB",
        ),
    )

    assert result.status == TransactionStatus.UNKNOWN
    assert result.meta.failure is not None
    assert result.meta.failure.code == "cloudpayments_non_payment_operation"


@pytest.mark.parametrize("operation_type", ["Refund", "CardPayout"])
def test_cloudpayments_adapter_lookup_rejects_refund_or_payout_model_when_success_false(
    operation_type: str,
) -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/payments/find"
        return httpx.Response(
            200,
            json={
                "Success": False,
                "Message": None,
                "Model": {
                    "PublicId": "pk_test",
                    "TransactionId": 897749645,
                    "InvoiceId": "inv-1",
                    "OperationType": operation_type,
                    "Status": "Completed",
                    "Amount": 159,
                    "Currency": "RUB",
                    "PaymentAmount": 159,
                    "PaymentCurrency": "RUB",
                },
            },
        )

    adapter = _adapter_with_transport(httpx.MockTransport(handler))

    result = adapter.lookup_transaction(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=TransactionLookupRequest(
            provider_invoice_id="inv-1",
            expected_amount_minor=15900,
            expected_currency="RUB",
        ),
    )

    assert result.status == TransactionStatus.UNKNOWN
    assert result.provider_payment_id is None
    assert result.meta.failure is not None
    assert result.meta.failure.code == "cloudpayments_non_payment_operation"


def test_cloudpayments_adapter_lookup_rejects_missing_model() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/payments/get"
        return httpx.Response(200, json={"Success": True, "Message": None, "Model": None})

    adapter = _adapter_with_transport(httpx.MockTransport(handler))

    result = adapter.lookup_transaction(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=TransactionLookupRequest(
            provider_payment_id="897749645",
            provider_invoice_id="inv-1",
            expected_amount_minor=15900,
            expected_currency="RUB",
        ),
    )

    assert result.status == TransactionStatus.UNKNOWN
    assert result.provider_payment_id is None
    assert result.meta.failure is not None
    assert result.meta.failure.code == "cloudpayments_transaction_lookup_missing_model"


def test_cloudpayments_adapter_refund_maps_accepted_response_to_pending() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/payments/refund"
        return httpx.Response(
            200,
            json={
                "Success": True,
                "Message": None,
                "Model": {"TransactionId": 568},
            },
        )

    adapter = CloudPaymentsAdapter(
        api_client=CloudPaymentsApiClient(
            config=CloudPaymentsApiClientConfig(
                base_url="https://api.cloudpayments.ru",
                public_id="pk_test",
                api_secret="secret_test",
                max_retries=0,
            ),
            transport=httpx.MockTransport(handler),
        )
    )

    result = adapter.refund_payment(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=RefundRequest(
            provider_payment_id="455",
            amount_minor=10000,
            amount=Decimal("100.00"),
            currency="RUB",
            idempotency_key="refund-455-10000",
        ),
    )

    assert result.provider_refund_id == "568"
    assert result.status == RefundStatus.PENDING
    assert result.meta.outcome.value == "succeeded"
    assert result.meta.idempotency_key == "refund-455-10000"


def test_cloudpayments_adapter_refund_maps_transport_failure_to_retryable_result() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    adapter = CloudPaymentsAdapter(
        api_client=CloudPaymentsApiClient(
            config=CloudPaymentsApiClientConfig(
                base_url="https://api.cloudpayments.ru",
                public_id="pk_test",
                api_secret="secret_test",
                max_retries=0,
            ),
            transport=httpx.MockTransport(handler),
        )
    )

    result = adapter.refund_payment(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=RefundRequest(
            provider_payment_id="455",
            amount_minor=10000,
            amount=Decimal("100.00"),
            currency="RUB",
            idempotency_key="refund-455-10000",
        ),
    )

    assert result.status == RefundStatus.FAILED
    assert result.meta.outcome.value == "failed"
    assert result.meta.retry_disposition.value == "retryable"
    assert result.meta.failure is not None
    assert result.meta.failure.code == "payments_api_timeout"


def test_cloudpayments_adapter_refund_maps_provider_decline_safely() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/payments/refund"
        return httpx.Response(
            200,
            json={"Success": False, "Message": "Raw provider text with PAN 4111111111111111"},
        )

    adapter = _adapter_with_transport(httpx.MockTransport(handler))

    result = adapter.refund_payment(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=RefundRequest(
            provider_payment_id="455",
            amount_minor=10000,
            amount=Decimal("100.00"),
            currency="RUB",
            idempotency_key="refund-455-10000",
        ),
    )

    assert result.status == RefundStatus.FAILED
    assert result.provider_refund_id is None
    assert result.meta.failure is not None
    assert result.meta.failure.code == "cloudpayments_operation_declined"
    assert result.meta.failure.message_safe == "CloudPayments declined the operation."
    assert "4111111111111111" not in str(result.model_dump())


@pytest.mark.parametrize(
    "response_payload",
    [
        {"Success": True, "Message": None, "Model": {}},
        {"Success": True, "Message": None, "Model": {"TransactionId": "not-an-int"}},
    ],
)
def test_cloudpayments_adapter_refund_maps_schema_mismatch_and_missing_refund_id(
    response_payload: dict[str, object],
) -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/payments/refund"
        return httpx.Response(200, json=response_payload)

    adapter = _adapter_with_transport(httpx.MockTransport(handler))

    result = adapter.refund_payment(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=RefundRequest(
            provider_payment_id="455",
            amount_minor=10000,
            amount=Decimal("100.00"),
            currency="RUB",
            idempotency_key="refund-455-10000",
        ),
    )

    assert result.status == RefundStatus.FAILED
    assert result.provider_refund_id is None
    assert result.meta.failure is not None
    assert result.meta.failure.code == "payments_api_response_validation_error"


def test_cloudpayments_adapter_refund_maps_response_decode_error() -> None:
    provider_account = _provider_account()
    adapter = _adapter_with_transport(httpx.MockTransport(lambda request: httpx.Response(200, text="not-json")))

    result = adapter.refund_payment(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=RefundRequest(
            provider_payment_id="455",
            amount_minor=10000,
            amount=Decimal("100.00"),
            currency="RUB",
            idempotency_key="refund-455-10000",
        ),
    )

    assert result.status == RefundStatus.FAILED
    assert result.provider_refund_id is None
    assert result.meta.failure is not None
    assert result.meta.failure.code == "payments_api_response_decode_error"


def test_cloudpayments_adapter_lookup_transaction_rejects_wrong_provider_account_provider() -> None:
    provider_account = _provider_account()
    provider_account.provider = "other-provider"
    adapter = CloudPaymentsAdapter(
        api_client=CloudPaymentsApiClient(
            config=CloudPaymentsApiClientConfig(
                base_url="https://api.cloudpayments.ru",
                public_id="pk_test",
                api_secret="secret_test",
                max_retries=0,
            ),
            transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        )
    )

    result = adapter.lookup_transaction(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=TransactionLookupRequest(
            provider_payment_id="897749645",
            expected_amount_minor=15900,
            expected_currency="RUB",
        ),
    )

    assert result.meta.failure is not None
    assert result.meta.failure.code == "provider_account_invalid_provider"


def test_cloudpayments_adapter_lookup_transaction_rejects_public_id_mismatch() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "Success": True,
                "Message": None,
                "Model": {
                    "PublicId": "pk_other",
                    "TransactionId": 897749645,
                    "InvoiceId": "inv-1",
                    "OperationType": "Payment",
                    "Status": "Completed",
                    "ReasonCode": 0,
                    "Amount": 159,
                    "Currency": "RUB",
                    "PaymentAmount": 159,
                    "PaymentCurrency": "RUB",
                },
            },
        )

    adapter = CloudPaymentsAdapter(
        api_client=CloudPaymentsApiClient(
            config=CloudPaymentsApiClientConfig(
                base_url="https://api.cloudpayments.ru",
                public_id="pk_test",
                api_secret="secret_test",
                max_retries=0,
            ),
            transport=httpx.MockTransport(handler),
        )
    )

    result = adapter.lookup_transaction(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=TransactionLookupRequest(
            provider_payment_id="897749645",
            expected_amount_minor=15900,
            expected_currency="RUB",
        ),
    )

    assert result.meta.failure is not None
    assert result.meta.failure.code == "cloudpayments_public_id_mismatch"


def test_cloudpayments_adapter_refund_rejects_currency_mismatch() -> None:
    provider_account = _provider_account()
    adapter = CloudPaymentsAdapter(
        api_client=CloudPaymentsApiClient(
            config=CloudPaymentsApiClientConfig(
                base_url="https://api.cloudpayments.ru",
                public_id="pk_test",
                api_secret="secret_test",
                max_retries=0,
            ),
            transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        )
    )

    result = adapter.refund_payment(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=RefundRequest(
            provider_payment_id="455",
            amount_minor=10000,
            amount=Decimal("100.00"),
            currency="USD",
        ),
    )

    assert result.meta.failure is not None
    assert result.meta.failure.code == "refund_currency_mismatch"


def test_cloudpayments_adapter_create_recurring_subscription_maps_success() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/subscriptions/create"
        assert request.headers["x-request-id"] == "sub-create-1"
        payload = request.read()
        assert b'"Token":"tk_test"' in payload
        assert b'"Interval":"Month"' in payload
        return httpx.Response(
            200,
            json={
                "Success": True,
                "Message": None,
                "Model": {
                    "Id": "sc_1",
                    "AccountId": "user_1",
                    "Amount": 399,
                    "Currency": "RUB",
                    "Interval": "Month",
                    "Period": 1,
                    "Status": "Active",
                },
            },
        )

    adapter = _adapter_with_transport(httpx.MockTransport(handler))

    result = adapter.create_recurring_subscription(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=_create_subscription_request(),
    )

    assert result.provider_subscription_id == "sc_1"
    assert result.account_id == "user_1"
    assert result.status == RecurringSubscriptionStatus.ACTIVE
    assert result.amount_minor == 39900
    assert result.currency == "RUB"
    assert result.interval_unit == "month"
    assert result.interval_count == 1
    assert result.meta.outcome.value == "succeeded"
    assert result.meta.idempotency_key == "sub-create-1"


def test_cloudpayments_adapter_update_recurring_subscription_maps_success_without_email() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/subscriptions/update"
        assert request.headers["x-request-id"] == "sub-update-1"
        payload = request.read()
        assert b'"Email"' not in payload
        assert b'"Description":"Updated plan"' in payload
        return httpx.Response(
            200,
            json={
                "Success": True,
                "Message": None,
                "Model": {
                    "Id": "sc_1",
                    "Amount": 499,
                    "Currency": "RUB",
                    "Interval": "Week",
                    "Period": 2,
                    "Status": "PastDue",
                },
            },
        )

    adapter = _adapter_with_transport(httpx.MockTransport(handler))

    result = adapter.update_recurring_subscription(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=UpdateRecurringSubscriptionRequest(
            provider_subscription_id="sc_1",
            description="Updated plan",
            amount_minor=49900,
            amount=Decimal("499.00"),
            currency="RUB",
            interval_unit="week",
            interval_count=2,
            require_confirmation=False,
            start_at="2026-10-22T00:00:00Z",
            max_periods=6,
            idempotency_key="sub-update-1",
        ),
    )

    assert result.provider_subscription_id == "sc_1"
    assert result.status == RecurringSubscriptionStatus.PAST_DUE
    assert result.amount_minor == 49900
    assert result.interval_unit == "week"
    assert result.interval_count == 2
    assert result.meta.outcome.value == "succeeded"


def test_cloudpayments_adapter_cancel_recurring_subscription_maps_success_to_canceled() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/subscriptions/cancel"
        assert request.headers["x-request-id"] == "sub-cancel-1"
        assert request.read() == b'{"Id":"sc_1"}'
        return httpx.Response(200, json={"Success": True, "Message": None})

    adapter = _adapter_with_transport(httpx.MockTransport(handler))

    result = adapter.cancel_recurring_subscription(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=CancelRecurringSubscriptionRequest(
            provider_subscription_id="sc_1",
            idempotency_key="sub-cancel-1",
        ),
    )

    assert result.provider_subscription_id == "sc_1"
    assert result.status == RecurringSubscriptionStatus.CANCELED
    assert result.meta.outcome.value == "succeeded"
    assert result.meta.idempotency_key == "sub-cancel-1"


@pytest.mark.parametrize(
    ("provider_status", "expected"),
    [
        ("Active", RecurringSubscriptionStatus.ACTIVE),
        ("PastDue", RecurringSubscriptionStatus.PAST_DUE),
        ("Cancelled", RecurringSubscriptionStatus.CANCELED),
        ("Rejected", RecurringSubscriptionStatus.FAILED),
        ("Expired", RecurringSubscriptionStatus.ENDED),
        ("active", RecurringSubscriptionStatus.UNKNOWN),
        ("Paused", RecurringSubscriptionStatus.UNKNOWN),
    ],
)
def test_cloudpayments_adapter_recurring_subscription_status_mapping_is_exact(
    provider_status: str,
    expected: RecurringSubscriptionStatus,
) -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"Success": True, "Message": None, "Model": {"Id": "sc_1", "Status": provider_status}},
        )

    adapter = _adapter_with_transport(httpx.MockTransport(handler))

    result = adapter.create_recurring_subscription(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=_create_subscription_request(idempotency_key=f"sub-create-{provider_status}"),
    )

    assert result.status == expected


def test_cloudpayments_adapter_recurring_subscription_rejects_public_id_mismatch() -> None:
    provider_account = _provider_account()
    provider_account.public_identifier = "pk_other"
    adapter = _adapter_with_transport(httpx.MockTransport(lambda request: httpx.Response(500)))

    result = adapter.create_recurring_subscription(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=_create_subscription_request(),
    )

    assert result.status == RecurringSubscriptionStatus.FAILED
    assert result.meta.failure is not None
    assert result.meta.failure.code == "cloudpayments_public_id_mismatch"


def test_cloudpayments_adapter_create_recurring_subscription_rejects_missing_start_date() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("provider should not be called")

    adapter = _adapter_with_transport(httpx.MockTransport(handler))

    result = adapter.create_recurring_subscription(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=_create_subscription_request(start_at=None),
    )

    assert result.status == RecurringSubscriptionStatus.FAILED
    assert result.meta.failure is not None
    assert result.meta.failure.code == "recurring_start_at_required"


def test_cloudpayments_adapter_update_recurring_subscription_rejects_empty_patch() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("provider should not be called")

    adapter = _adapter_with_transport(httpx.MockTransport(handler))

    result = adapter.update_recurring_subscription(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=UpdateRecurringSubscriptionRequest(
            provider_subscription_id="sc_1",
            idempotency_key="sub-update-empty",
        ),
    )

    assert result.status == RecurringSubscriptionStatus.FAILED
    assert result.meta.failure is not None
    assert result.meta.failure.code == "recurring_update_patch_empty"


def test_cloudpayments_adapter_create_recurring_subscription_maps_transport_failure() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    adapter = _adapter_with_transport(httpx.MockTransport(handler))

    result = adapter.create_recurring_subscription(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=_create_subscription_request(),
    )

    assert result.status == RecurringSubscriptionStatus.FAILED
    assert result.meta.retry_disposition.value == "retryable"
    assert result.meta.failure is not None
    assert result.meta.failure.code == "payments_api_timeout"


def test_cloudpayments_adapter_update_recurring_subscription_maps_provider_decline_safely() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Success": False, "Message": "Invalid Amount value"})

    adapter = _adapter_with_transport(httpx.MockTransport(handler))

    result = adapter.update_recurring_subscription(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=UpdateRecurringSubscriptionRequest(
            provider_subscription_id="sc_1",
            amount_minor=49900,
            amount=Decimal("499.00"),
            currency="RUB",
            idempotency_key="sub-update-2",
        ),
    )

    assert result.status == RecurringSubscriptionStatus.FAILED
    assert result.meta.failure is not None
    assert result.meta.failure.code == "cloudpayments_operation_declined"
    assert result.meta.failure.message_safe == "CloudPayments declined the operation."


def test_cloudpayments_adapter_create_recurring_subscription_maps_schema_mismatch() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Success": True, "Message": None, "Model": None})

    adapter = _adapter_with_transport(httpx.MockTransport(handler))

    result = adapter.create_recurring_subscription(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=_create_subscription_request(),
    )

    assert result.status == RecurringSubscriptionStatus.FAILED
    assert result.meta.failure is not None
    assert result.meta.failure.code == "payments_api_response_validation_error"


def test_cloudpayments_adapter_cancel_recurring_subscription_maps_transport_failure() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    adapter = _adapter_with_transport(httpx.MockTransport(handler))

    result = adapter.cancel_recurring_subscription(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=CancelRecurringSubscriptionRequest(
            provider_subscription_id="sc_1",
            idempotency_key="sub-cancel-2",
        ),
    )

    assert result.status == RecurringSubscriptionStatus.FAILED
    assert result.meta.retry_disposition.value == "retryable"
    assert result.meta.failure is not None
    assert result.meta.failure.code == "payments_api_timeout"


def test_cloudpayments_adapter_cancel_recurring_subscription_maps_provider_decline_safely() -> None:
    provider_account = _provider_account()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Success": False, "Message": "Do not leak this provider message"})

    adapter = _adapter_with_transport(httpx.MockTransport(handler))

    result = adapter.cancel_recurring_subscription(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=CancelRecurringSubscriptionRequest(
            provider_subscription_id="sc_1",
            idempotency_key="sub-cancel-3",
        ),
    )

    assert result.status == RecurringSubscriptionStatus.FAILED
    assert result.meta.failure is not None
    assert result.meta.failure.code == "cloudpayments_operation_declined"
    assert result.meta.failure.message_safe == "CloudPayments declined the operation."
    assert "Do not leak this provider message" not in str(result.model_dump())


def test_cloudpayments_adapter_cancel_recurring_subscription_maps_schema_mismatch() -> None:
    provider_account = _provider_account()
    adapter = _adapter_with_transport(httpx.MockTransport(lambda request: httpx.Response(200, json={"Model": None})))

    result = adapter.cancel_recurring_subscription(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=CancelRecurringSubscriptionRequest(
            provider_subscription_id="sc_1",
            idempotency_key="sub-cancel-4",
        ),
    )

    assert result.status == RecurringSubscriptionStatus.FAILED
    assert result.meta.failure is not None
    assert result.meta.failure.code == "payments_api_response_validation_error"


def test_cloudpayments_adapter_recurring_subscription_rejects_wrong_provider_account_provider() -> None:
    provider_account = _provider_account()
    provider_account.provider = "other-provider"
    adapter = _adapter_with_transport(httpx.MockTransport(lambda request: httpx.Response(500)))

    result = adapter.create_recurring_subscription(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=_create_subscription_request(),
    )

    assert result.status == RecurringSubscriptionStatus.FAILED
    assert result.meta.failure is not None
    assert result.meta.failure.code == "provider_account_invalid_provider"
