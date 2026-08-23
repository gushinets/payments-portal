from __future__ import annotations

import json
import logging
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from apps.api.tests.support.settings import configure_api_test_environment

configure_api_test_environment()

from app.core.errors import (  # noqa: E402
    PaymentsAuthenticationError,
    PaymentsOperationDeclinedError,
    PaymentsRateLimitError,
    PaymentsResponseDecodeError,
    PaymentsResponseValidationError,
    PaymentsTimeoutError,
    PaymentsUpstreamError,
)
from app.core.observability import JsonFormatter, redact  # noqa: E402
from app.integrations.cloudpayments.api_client import (  # noqa: E402
    CloudPaymentsApiClient,
    CloudPaymentsApiClientConfig,
    CloudPaymentsCreateSubscriptionRequest,
    CloudPaymentsUpdateSubscriptionRequest,
    build_cloudpayments_api_client,
)
from app.payment_providers.api_client import (  # noqa: E402
    BaseHttpPaymentsApiClient,
    PaymentsApiClientConfig,
    PaymentsApiRequest,
    PaymentsApiClientModel,
)
from app.core.settings import Settings  # noqa: E402


class DummyResponse(PaymentsApiClientModel):
    ok: bool


class DummyPaymentsApiClient(BaseHttpPaymentsApiClient):
    pass


def test_base_http_payments_api_client_validates_response_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        assert request.headers["content-type"] == "application/json"
        return httpx.Response(200, json={"ok": True})

    client = DummyPaymentsApiClient(
        config=PaymentsApiClientConfig(provider="dummy", base_url="https://provider.example"),
        transport=httpx.MockTransport(handler),
    )

    response = client.send(
        PaymentsApiRequest(operation="health", path="/health"),
        response_model=DummyResponse,
    )

    assert response.ok is True


def test_base_http_payments_api_client_raises_authentication_error() -> None:
    client = DummyPaymentsApiClient(
        config=PaymentsApiClientConfig(provider="dummy", base_url="https://provider.example"),
        transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"detail": "nope"})),
    )

    with pytest.raises(PaymentsAuthenticationError) as error:
        client.send(
            PaymentsApiRequest(operation="health", path="/health"),
            response_model=DummyResponse,
        )

    assert error.value.code == "payments_api_authentication_error"


def test_base_http_payments_api_client_retries_idempotent_requests() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"Success": False, "Message": "unavailable"})
        return httpx.Response(200, json={"ok": True})

    client = DummyPaymentsApiClient(
        config=PaymentsApiClientConfig(
            provider="dummy",
            base_url="https://provider.example",
            max_retries=1,
            retry_backoff_seconds=0.0,
        ),
        transport=httpx.MockTransport(handler),
    )

    response = client.send(
        PaymentsApiRequest(operation="health", path="/health", is_idempotent=True),
        response_model=DummyResponse,
    )

    assert response.ok is True
    assert attempts == 2


def test_base_http_payments_api_client_does_not_retry_non_idempotent_requests() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, json={"Success": False, "Message": "slow down"})

    client = DummyPaymentsApiClient(
        config=PaymentsApiClientConfig(
            provider="dummy",
            base_url="https://provider.example",
            max_retries=2,
            retry_backoff_seconds=0.0,
        ),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PaymentsRateLimitError):
        client.send(
            PaymentsApiRequest(operation="health", path="/health", is_idempotent=False),
            response_model=DummyResponse,
        )

    assert attempts == 1


def test_base_http_payments_api_client_does_not_retry_rate_limited_requests() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, json={"Success": False, "Message": "slow down"})

    client = DummyPaymentsApiClient(
        config=PaymentsApiClientConfig(
            provider="dummy",
            base_url="https://provider.example",
            max_retries=2,
            retry_backoff_seconds=0.0,
        ),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PaymentsRateLimitError) as error:
        client.send(
            PaymentsApiRequest(operation="health", path="/health", is_idempotent=True),
            response_model=DummyResponse,
        )

    assert attempts == 1
    assert error.value.retry_disposition.value == "non_retryable"


def test_base_http_payments_api_client_does_not_retry_mutation_without_key() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        assert "x-request-id" not in request.headers
        return httpx.Response(503, json={"Success": False, "Message": "unavailable"})

    client = DummyPaymentsApiClient(
        config=PaymentsApiClientConfig(
            provider="dummy",
            base_url="https://provider.example",
            max_retries=2,
            retry_backoff_seconds=0.0,
        ),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PaymentsUpstreamError):
        client.send(
            PaymentsApiRequest(
                operation="mutation",
                path="/mutation",
                is_idempotent=True,
                is_mutating=True,
            ),
            response_model=DummyResponse,
        )

    assert attempts == 1


def test_cloudpayments_client_retries_mutation_with_stable_request_id() -> None:
    request_ids: list[str] = []
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        request_ids.append(request.headers["x-request-id"])
        if attempts == 1:
            return httpx.Response(503, json={"Success": False, "Message": "unavailable"})
        return httpx.Response(200, json={"Success": True, "Message": None, "Model": {"TransactionId": 777}})

    client = CloudPaymentsApiClient(
        config=CloudPaymentsApiClientConfig(
            provider="cloudpayments",
            base_url="https://api.cloudpayments.ru",
            public_id="pk_test",
            api_secret="secret_test",
            max_retries=1,
            retry_backoff_seconds=0.0,
        ),
        transport=httpx.MockTransport(handler),
    )

    response = client.refund(
        transaction_id=455,
        amount=Decimal("100.00"),
        idempotency_key=" refund-455-10000 ",
    )

    assert response.model is not None
    assert attempts == 2
    assert request_ids == ["refund-455-10000", "refund-455-10000"]


def test_cloudpayments_client_does_not_send_blank_request_id() -> None:
    seen_headers: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(dict(request.headers))
        return httpx.Response(200, json={"Success": True, "Message": None, "Model": {"TransactionId": 777}})

    client = CloudPaymentsApiClient(
        config=CloudPaymentsApiClientConfig(
            provider="cloudpayments",
            base_url="https://api.cloudpayments.ru",
            public_id="pk_test",
            api_secret="secret_test",
            max_retries=0,
        ),
        transport=httpx.MockTransport(handler),
    )

    client.refund(transaction_id=455, amount=Decimal("100.00"), idempotency_key="   ")

    assert "x-request-id" not in seen_headers[0]


def test_base_http_payments_api_client_maps_timeout_to_custom_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    client = DummyPaymentsApiClient(
        config=PaymentsApiClientConfig(
            provider="dummy",
            base_url="https://provider.example",
            max_retries=0,
        ),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PaymentsTimeoutError):
        client.send(
            PaymentsApiRequest(operation="health", path="/health", is_idempotent=True),
            response_model=DummyResponse,
        )


def test_base_http_payments_api_client_keeps_component_timeout_bounds() -> None:
    client = DummyPaymentsApiClient(
        config=PaymentsApiClientConfig(
            provider="dummy",
            base_url="https://provider.example",
            timeout_seconds=10.0,
            connect_timeout_seconds=3.0,
            read_timeout_seconds=10.0,
            write_timeout_seconds=10.0,
            pool_timeout_seconds=3.0,
        ),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True})),
    )

    timeout = client._timeout_for_request(PaymentsApiRequest(operation="health", path="/health", timeout_seconds=30.0))

    assert timeout.connect == 3.0
    assert timeout.read == 10.0
    assert timeout.write == 10.0
    assert timeout.pool == 3.0


def test_base_http_payments_api_client_rejects_non_positive_request_timeout() -> None:
    with pytest.raises(ValidationError):
        PaymentsApiRequest(operation="health", path="/health", timeout_seconds=0)


def test_cloudpayments_client_sends_basic_auth_and_idempotency_header() -> None:
    seen_headers: dict[str, str] = {}
    seen_body: bytes = b""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_headers, seen_body
        assert request.method == "POST"
        assert request.url.path == "/payments/refund"
        seen_headers = dict(request.headers)
        seen_body = request.read()
        return httpx.Response(200, json={"Success": True, "Message": None, "Model": {"TransactionId": 777}})

    client = CloudPaymentsApiClient(
        config=CloudPaymentsApiClientConfig(
            provider="cloudpayments",
            base_url="https://api.cloudpayments.ru",
            public_id="pk_test",
            api_secret="secret_test",
            max_retries=0,
        ),
        transport=httpx.MockTransport(handler),
    )

    response = client.refund(
        transaction_id=455,
        amount=Decimal("100.00"),
        idempotency_key="refund-455-10000",
    )

    assert response.model is not None
    assert response.model.transaction_id == 777
    assert seen_headers["x-request-id"] == "refund-455-10000"
    assert seen_headers["authorization"].startswith("Basic ")
    assert b'"Amount":100' in seen_body


def test_cloudpayments_client_finds_transaction_by_invoice_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v2/payments/find"
        assert request.read() == b'{"InvoiceId":"inv-1"}'
        return httpx.Response(
            200,
            json={
                "Success": True,
                "Message": None,
                "Model": {"TransactionId": 777, "InvoiceId": "inv-1"},
            },
        )

    client = CloudPaymentsApiClient(
        config=CloudPaymentsApiClientConfig(
            base_url="https://api.cloudpayments.ru",
            public_id="pk_test",
            api_secret="secret_test",
            max_retries=0,
        ),
        transport=httpx.MockTransport(handler),
    )

    response = client.find_transaction(invoice_id="inv-1")

    assert response is not None
    assert response.model is not None
    assert response.model.transaction_id == 777


def test_cloudpayments_client_maps_not_found_to_none() -> None:
    client = CloudPaymentsApiClient(
        config=CloudPaymentsApiClientConfig(
            base_url="https://api.cloudpayments.ru",
            public_id="pk_test",
            api_secret="secret_test",
            max_retries=0,
        ),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"Success": False, "Message": "Not found"})
        ),
    )

    assert client.find_transaction(invoice_id="missing") is None


def test_cloudpayments_client_rejects_successful_refund_without_transaction_id() -> None:
    client = CloudPaymentsApiClient(
        config=CloudPaymentsApiClientConfig(
            base_url="https://api.cloudpayments.ru",
            public_id="pk_test",
            api_secret="secret_test",
            max_retries=0,
        ),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"Success": True, "Message": None, "Model": None})
        ),
    )

    with pytest.raises(PaymentsResponseValidationError):
        client.refund(transaction_id=455, amount=Decimal("100.00"))


def test_cloudpayments_client_raises_declined_error_for_success_false() -> None:
    client = CloudPaymentsApiClient(
        config=CloudPaymentsApiClientConfig(
            provider="cloudpayments",
            base_url="https://api.cloudpayments.ru",
            public_id="pk_test",
            api_secret="secret_test",
            max_retries=0,
        ),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"Success": False, "Message": "Invalid Amount value"})
        ),
    )

    with pytest.raises(PaymentsOperationDeclinedError) as error:
        client.create_subscription(
            request=CloudPaymentsCreateSubscriptionRequest(
                Token="tk_test",
                AccountId="user_1",
                Description="Monthly plan",
                Amount=Decimal("399.00"),
                Currency="RUB",
                RequireConfirmation=False,
                StartDate="2026-08-22T00:00:00Z",
                Interval="Month",
                Period=1,
            ),
            idempotency_key="sub-create-1",
        )

    assert error.value.code == "cloudpayments_operation_declined"
    assert error.value.provider == "cloudpayments"
    assert error.value.operation == "create_subscription"
    assert error.value.message_safe == "CloudPayments declined the operation."
    assert "Invalid Amount value" not in str(error.value)


def test_redact_covers_cloudpayments_sensitive_fields_and_variants() -> None:
    payload = {
        "ApiSecret": "api-secret-value",
        "CardCryptogramPacket": "cryptogram-value",
        "PAN": "4111111111111111",
        "CVV": "123",
        "Cvc": "456",
        "CardMask": "4111 11****** 1111",
        "ExpirationDate": "12/30",
        "Token": "token-value",
        "nested": {"api_secret": "nested-secret"},
    }

    safe_payload = redact(payload)

    assert safe_payload == {
        "ApiSecret": "[redacted]",
        "CardCryptogramPacket": "[redacted]",
        "PAN": "[redacted]",
        "CVV": "[redacted]",
        "Cvc": "[redacted]",
        "CardMask": "[redacted]",
        "ExpirationDate": "[redacted]",
        "Token": "[redacted]",
        "nested": {"api_secret": "[redacted]"},
    }


def test_json_formatter_redacts_structured_provider_fields() -> None:
    record = logging.LogRecord(
        name="payments",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="provider failure",
        args=(),
        exc_info=None,
    )
    record.structured = {"Authorization": "Basic secret", "PAN": "4111111111111111"}

    formatted = JsonFormatter().format(record)

    assert "Basic secret" not in formatted
    assert "4111111111111111" not in formatted
    assert "[redacted]" in formatted


def test_cloudpayments_client_create_subscription_uses_documented_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/subscriptions/create"
        return httpx.Response(200, json={"Success": True, "Message": None, "Model": {"Id": "sc_1"}})

    client = CloudPaymentsApiClient(
        config=CloudPaymentsApiClientConfig(
            provider="cloudpayments",
            base_url="https://api.cloudpayments.ru",
            public_id="pk_test",
            api_secret="secret_test",
            max_retries=0,
        ),
        transport=httpx.MockTransport(handler),
    )

    response = client.create_subscription(
        request=CloudPaymentsCreateSubscriptionRequest(
            Token="tk_test",
            AccountId="user_1",
            Description="Monthly plan",
            Amount=Decimal("399.00"),
            Currency="RUB",
            RequireConfirmation=False,
            StartDate="2026-08-22T00:00:00Z",
            Interval="Month",
            Period=1,
            CustomerReceipt={"Items": []},
        ),
        idempotency_key="sub-create-2",
    )

    assert response.model is not None
    assert response.model.subscription_id == "sc_1"


def test_cloudpayments_client_update_subscription_uses_documented_path_without_email() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/subscriptions/update"
        assert request.headers["x-request-id"] == "sub-update-1"
        payload = json.loads(request.content.decode("utf-8"))
        assert "Email" not in payload
        assert payload == {
            "Id": "sc_1",
            "Description": "Updated plan",
            "Amount": 499,
            "Currency": "RUB",
            "RequireConfirmation": False,
            "StartDate": "2026-09-22T00:00:00Z",
            "Interval": "Month",
            "Period": 1,
            "MaxPeriods": 12,
            "CustomerReceipt": {"Items": []},
        }
        return httpx.Response(200, json={"Success": True, "Message": None, "Model": {"Id": "sc_1"}})

    client = CloudPaymentsApiClient(
        config=CloudPaymentsApiClientConfig(
            provider="cloudpayments",
            base_url="https://api.cloudpayments.ru",
            public_id="pk_test",
            api_secret="secret_test",
            max_retries=0,
        ),
        transport=httpx.MockTransport(handler),
    )

    response = client.update_subscription(
        request=CloudPaymentsUpdateSubscriptionRequest(
            Id="sc_1",
            Description="Updated plan",
            Amount=Decimal("499.00"),
            Currency="RUB",
            RequireConfirmation=False,
            StartDate="2026-09-22T00:00:00Z",
            Interval="Month",
            Period=1,
            MaxPeriods=12,
            CustomerReceipt={"Items": []},
        ),
        idempotency_key="sub-update-1",
    )

    assert response.model is not None
    assert response.model.subscription_id == "sc_1"


def test_cloudpayments_client_cancel_subscription_uses_documented_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/subscriptions/cancel"
        assert request.headers["x-request-id"] == "sub-cancel-1"
        assert json.loads(request.content.decode("utf-8")) == {"Id": "sc_1"}
        return httpx.Response(200, json={"Success": True, "Message": None})

    client = CloudPaymentsApiClient(
        config=CloudPaymentsApiClientConfig(
            provider="cloudpayments",
            base_url="https://api.cloudpayments.ru",
            public_id="pk_test",
            api_secret="secret_test",
            max_retries=0,
        ),
        transport=httpx.MockTransport(handler),
    )

    response = client.cancel_subscription(subscription_id="sc_1", idempotency_key="sub-cancel-1")

    assert response.success is True


def test_cloudpayments_client_rejects_successful_subscription_without_subscription_id() -> None:
    client = CloudPaymentsApiClient(
        config=CloudPaymentsApiClientConfig(
            provider="cloudpayments",
            base_url="https://api.cloudpayments.ru",
            public_id="pk_test",
            api_secret="secret_test",
            max_retries=0,
        ),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"Success": True, "Message": None, "Model": None})
        ),
    )

    with pytest.raises(PaymentsResponseValidationError):
        client.create_subscription(
            request=CloudPaymentsCreateSubscriptionRequest(
                Token="tk_test",
                AccountId="user_1",
                Description="Monthly plan",
                Amount=Decimal("399.00"),
                Currency="RUB",
                RequireConfirmation=False,
                StartDate="2026-08-22T00:00:00Z",
                Interval="Month",
                Period=1,
            ),
            idempotency_key="sub-create-3",
        )


def test_base_http_payments_api_client_raises_response_decode_error() -> None:
    client = DummyPaymentsApiClient(
        config=PaymentsApiClientConfig(provider="dummy", base_url="https://provider.example"),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="not-json")),
    )

    with pytest.raises(PaymentsResponseDecodeError):
        client.send(
            PaymentsApiRequest(operation="health", path="/health"),
            response_model=DummyResponse,
        )


def test_base_http_payments_api_client_raises_response_validation_error() -> None:
    client = DummyPaymentsApiClient(
        config=PaymentsApiClientConfig(provider="dummy", base_url="https://provider.example"),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"unexpected": True})),
    )

    with pytest.raises(PaymentsResponseValidationError):
        client.send(
            PaymentsApiRequest(operation="health", path="/health"),
            response_model=DummyResponse,
        )


def test_build_cloudpayments_api_client_uses_required_settings() -> None:
    app_settings = Settings(
        _env_file=None,
        app_env="test",
        app_public_base_url="https://payments.example.com",
        database_url="sqlite+pysqlite:///:memory:",
        postgres_db="payments",
        postgres_user="payments",
        postgres_password="secret",
        postgres_host="postgres",
        postgres_port=5432,
        cloudpayments_enabled=True,
        cloudpayments_public_id="pk_test",
        cloudpayments_api_secret="secret_test",
        cors_allow_origins=("https://payments.example.com",),
    )

    client = build_cloudpayments_api_client(app_settings=app_settings)

    assert client.config.base_url == "https://api.cloudpayments.ru"
    assert client.config.public_id == "pk_test"
    assert client.config.api_secret == "secret_test"
    assert client.config.timeout_seconds == 10.0
    client.close()


def test_build_cloudpayments_api_client_settings_reject_invalid_timeout() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="test",
            app_public_base_url="https://payments.example.com",
            database_url="sqlite+pysqlite:///:memory:",
            postgres_db="payments",
            postgres_user="payments",
            postgres_password="secret",
            postgres_host="postgres",
            postgres_port=5432,
            cloudpayments_enabled=True,
            cloudpayments_public_id="pk_test",
            cloudpayments_api_secret="secret_test",
            cloudpayments_api_timeout_seconds=0,
            cors_allow_origins=("https://payments.example.com",),
        )
