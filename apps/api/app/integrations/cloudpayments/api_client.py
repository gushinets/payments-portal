from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
from pydantic import ConfigDict, Field

from app.core.errors import PaymentsOperationDeclinedError
from app.core.settings import Settings, settings
from app.payment_providers.api_client import (
    BaseHttpPaymentsApiClient,
    PaymentsApiClientConfig,
    PaymentsApiRequest,
)
from app.payment_providers.contracts import ProviderContractModel

CLOUDPAYMENTS_API_PROVIDER_CODE = "cloudpayments"


class CloudPaymentsApiClientConfig(PaymentsApiClientConfig):
    provider: str = CLOUDPAYMENTS_API_PROVIDER_CODE
    public_id: str
    api_secret: str


class CloudPaymentsResponseModel(ProviderContractModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class CloudPaymentsApiResponse(CloudPaymentsResponseModel):
    success: bool = Field(alias="Success")
    message: str | None = Field(alias="Message", default=None)


class CloudPaymentsTransactionModel(CloudPaymentsResponseModel):
    transaction_id: int = Field(alias="TransactionId")
    invoice_id: str | None = Field(default=None, alias="InvoiceId")
    status: str | None = Field(default=None, alias="Status")
    status_code: int | None = Field(default=None, alias="StatusCode")
    reason_code: int | None = Field(default=None, alias="ReasonCode")
    amount: Decimal | None = Field(default=None, alias="Amount")
    currency: str | None = Field(default=None, alias="Currency")
    payment_amount: Decimal | None = Field(default=None, alias="PaymentAmount")
    payment_currency: str | None = Field(default=None, alias="PaymentCurrency")


class CloudPaymentsRefundModel(CloudPaymentsResponseModel):
    transaction_id: int = Field(alias="TransactionId")


class CloudPaymentsSubscriptionModel(CloudPaymentsResponseModel):
    subscription_id: str = Field(alias="Id")
    account_id: str | None = Field(default=None, alias="AccountId")
    description: str | None = Field(default=None, alias="Description")
    email: str | None = Field(default=None, alias="Email")
    amount: Decimal | None = Field(default=None, alias="Amount")
    currency: str | None = Field(default=None, alias="Currency")
    require_confirmation: bool | None = Field(default=None, alias="RequireConfirmation")
    start_date_iso: str | None = Field(default=None, alias="StartDateIso")
    interval: str | None = Field(default=None, alias="Interval")
    period: int | None = Field(default=None, alias="Period")
    max_periods: int | None = Field(default=None, alias="MaxPeriods")
    status: str | None = Field(default=None, alias="Status")
    status_code: int | None = Field(default=None, alias="StatusCode")


class CloudPaymentsTransactionResponse(CloudPaymentsApiResponse):
    model: CloudPaymentsTransactionModel | None = Field(alias="Model", default=None)


class CloudPaymentsRefundResponse(CloudPaymentsApiResponse):
    model: CloudPaymentsRefundModel | None = Field(alias="Model", default=None)


class CloudPaymentsSubscriptionResponse(CloudPaymentsApiResponse):
    model: CloudPaymentsSubscriptionModel | None = Field(alias="Model", default=None)


class CloudPaymentsVoidResponse(CloudPaymentsApiResponse):
    model: dict[str, Any] | list[Any] | None = Field(alias="Model", default=None)


class CloudPaymentsCreateSubscriptionRequest(CloudPaymentsResponseModel):
    token: str = Field(alias="Token")
    account_id: str = Field(alias="AccountId")
    description: str = Field(alias="Description")
    amount: Decimal = Field(alias="Amount")
    currency: str = Field(alias="Currency")
    require_confirmation: bool = Field(alias="RequireConfirmation")
    start_date: str = Field(alias="StartDate")
    interval: str = Field(alias="Interval")
    period: int = Field(alias="Period")
    email: str | None = Field(default=None, alias="Email")
    max_periods: int | None = Field(default=None, alias="MaxPeriods")
    customer_receipt: dict[str, Any] | None = Field(default=None, alias="CustomerReceipt")
    culture_name: str | None = Field(default=None, alias="CultureName")


class CloudPaymentsUpdateSubscriptionRequest(CloudPaymentsResponseModel):
    subscription_id: str = Field(alias="Id")
    description: str | None = Field(default=None, alias="Description")
    amount: Decimal | None = Field(default=None, alias="Amount")
    currency: str | None = Field(default=None, alias="Currency")
    require_confirmation: bool | None = Field(default=None, alias="RequireConfirmation")
    start_date: str | None = Field(default=None, alias="StartDate")
    interval: str | None = Field(default=None, alias="Interval")
    period: int | None = Field(default=None, alias="Period")
    email: str | None = Field(default=None, alias="Email")
    max_periods: int | None = Field(default=None, alias="MaxPeriods")
    customer_receipt: dict[str, Any] | None = Field(default=None, alias="CustomerReceipt")
    culture_name: str | None = Field(default=None, alias="CultureName")


class CloudPaymentsApiClient(BaseHttpPaymentsApiClient):
    config: CloudPaymentsApiClientConfig

    def __init__(
        self,
        *,
        config: CloudPaymentsApiClientConfig,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(config=config, transport=transport)
        self.config = config

    def get_transaction(self, *, transaction_id: int) -> CloudPaymentsTransactionResponse:
        response = self.send(
            PaymentsApiRequest(
                operation="get_transaction",
                path="/payments/get",
                payload={"TransactionId": transaction_id},
                is_idempotent=True,
            ),
            response_model=CloudPaymentsTransactionResponse,
        )
        return self._require_success("get_transaction", response)

    def refund(
        self,
        *,
        transaction_id: int,
        amount: Decimal,
        json_data: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> CloudPaymentsRefundResponse:
        payload: dict[str, Any] = {
            "TransactionId": transaction_id,
            "Amount": amount,
        }
        if json_data is not None:
            payload["JsonData"] = json_data
        response = self.send(
            PaymentsApiRequest(
                operation="refund",
                path="/payments/refund",
                payload=payload,
                idempotency_key=idempotency_key,
                is_idempotent=True,
            ),
            response_model=CloudPaymentsRefundResponse,
        )
        return self._require_success("refund", response)

    def create_subscription(
        self,
        *,
        request: CloudPaymentsCreateSubscriptionRequest,
        idempotency_key: str | None = None,
    ) -> CloudPaymentsSubscriptionResponse:
        response = self.send(
            PaymentsApiRequest(
                operation="create_subscription",
                path="/subscriptions/create",
                payload=request.model_dump(mode="json", by_alias=True, exclude_none=True),
                idempotency_key=idempotency_key,
                is_idempotent=True,
            ),
            response_model=CloudPaymentsSubscriptionResponse,
        )
        return self._require_success("create_subscription", response)

    def update_subscription(
        self,
        *,
        request: CloudPaymentsUpdateSubscriptionRequest,
        idempotency_key: str | None = None,
    ) -> CloudPaymentsSubscriptionResponse:
        response = self.send(
            PaymentsApiRequest(
                operation="update_subscription",
                path="/subscriptions/update",
                payload=request.model_dump(mode="json", by_alias=True, exclude_none=True),
                idempotency_key=idempotency_key,
                is_idempotent=True,
            ),
            response_model=CloudPaymentsSubscriptionResponse,
        )
        return self._require_success("update_subscription", response)

    def cancel_subscription(
        self,
        *,
        subscription_id: str,
        idempotency_key: str | None = None,
    ) -> CloudPaymentsVoidResponse:
        response = self.send(
            PaymentsApiRequest(
                operation="cancel_subscription",
                path="/subscriptions/cancel",
                payload={"Id": subscription_id},
                idempotency_key=idempotency_key,
                is_idempotent=True,
            ),
            response_model=CloudPaymentsVoidResponse,
        )
        return self._require_success("cancel_subscription", response)

    def get_subscription(self, *, subscription_id: str) -> CloudPaymentsSubscriptionResponse:
        response = self.send(
            PaymentsApiRequest(
                operation="get_subscription",
                path="/subscriptions/get",
                payload={"Id": subscription_id},
                is_idempotent=True,
            ),
            response_model=CloudPaymentsSubscriptionResponse,
        )
        return self._require_success("get_subscription", response)

    def _build_auth(self) -> httpx.Auth | None:
        return httpx.BasicAuth(self.config.public_id, self.config.api_secret)

    def _require_success(
        self,
        operation: str,
        response: CloudPaymentsApiResponse,
    ) -> CloudPaymentsApiResponse:
        if response.success:
            return response
        raise PaymentsOperationDeclinedError(
            "cloudpayments_operation_declined",
            provider=self.config.provider,
            operation=operation,
            message_safe=response.message or "CloudPayments rejected the operation.",
        )


def build_cloudpayments_api_client(
    *,
    app_settings: Settings = settings,
    transport: httpx.BaseTransport | None = None,
) -> CloudPaymentsApiClient:
    return CloudPaymentsApiClient(
        config=CloudPaymentsApiClientConfig(
            base_url=app_settings.cloudpayments_api_base_url,
            public_id=app_settings.cloudpayments_public_id,
            api_secret=app_settings.cloudpayments_api_secret,
            timeout_seconds=app_settings.cloudpayments_api_timeout_seconds,
            connect_timeout_seconds=app_settings.cloudpayments_api_connect_timeout_seconds,
            read_timeout_seconds=app_settings.cloudpayments_api_read_timeout_seconds,
            write_timeout_seconds=app_settings.cloudpayments_api_write_timeout_seconds,
            pool_timeout_seconds=app_settings.cloudpayments_api_pool_timeout_seconds,
            max_retries=app_settings.cloudpayments_api_max_retries,
            retry_backoff_seconds=app_settings.cloudpayments_api_retry_backoff_seconds,
        ),
        transport=transport,
    )
