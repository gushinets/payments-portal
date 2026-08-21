from __future__ import annotations

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
)
from app.integrations.cloudpayments.api_client import (  # noqa: E402
    CloudPaymentsApiClient,
    CloudPaymentsApiClientConfig,
    CloudPaymentsCreateSubscriptionRequest,
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
            return httpx.Response(429, json={"Success": False, "Message": "slow down"})
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
                CultureName="ru-RU",
            ),
            idempotency_key="sub-create-1",
        )

    assert error.value.code == "cloudpayments_operation_declined"
    assert error.value.provider == "cloudpayments"
    assert error.value.operation == "create_subscription"


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
            CultureName="ru-RU",
        ),
        idempotency_key="sub-create-2",
    )

    assert response.model is not None
    assert response.model.subscription_id == "sc_1"


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
