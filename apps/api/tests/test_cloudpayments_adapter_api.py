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
    RefundRequest,
    RefundStatus,
    TransactionLookupRequest,
    TransactionStatus,
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
