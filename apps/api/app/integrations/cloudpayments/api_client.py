from __future__ import annotations

import logging
from decimal import Decimal
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import PaymentsOperationDeclinedError, PaymentsResponseValidationError
from app.core.settings import Settings, settings
from app.payment_providers.api_client import (
    BaseHttpPaymentsApiClient,
    PaymentsApiOperationOutcome,
    PaymentsApiClientConfig,
    PaymentsApiRequest,
)
from app.payment_providers.contracts import ProviderContractModel

CLOUDPAYMENTS_API_PROVIDER_CODE = "cloudpayments"
logger = logging.getLogger(__name__)


class CloudPaymentsApiClientConfig(PaymentsApiClientConfig):
    provider: str = CLOUDPAYMENTS_API_PROVIDER_CODE
    public_id: str
    api_secret: str


class CloudPaymentsResponseModel(ProviderContractModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class CloudPaymentsApiResponse(CloudPaymentsResponseModel):
    success: bool = Field(alias="Success")
    message: str | None = Field(alias="Message", default=None)


class CloudPaymentsTransactionStatus(StrEnum):
    AWAITING_AUTHENTICATION = "AwaitingAuthentication"
    AUTHORIZED = "Authorized"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"
    DECLINED = "Declined"


class CloudPaymentsTransactionModel(CloudPaymentsResponseModel):
    transaction_id: int = Field(alias="TransactionId")
    public_id: str | None = Field(default=None, alias="PublicId")
    invoice_id: str | None = Field(default=None, alias="InvoiceId")
    operation_type: str | None = Field(default=None, alias="OperationType")
    transaction_type: int | None = Field(default=None, alias="Type")
    original_transaction_id: int | None = Field(default=None, alias="OriginalTransactionId")
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


class CloudPaymentsUpdateSubscriptionRequest(CloudPaymentsResponseModel):
    subscription_id: str = Field(alias="Id")
    description: str | None = Field(default=None, alias="Description")
    amount: Decimal | None = Field(default=None, alias="Amount")
    currency: str | None = Field(default=None, alias="Currency")
    require_confirmation: bool | None = Field(default=None, alias="RequireConfirmation")
    start_date: str | None = Field(default=None, alias="StartDate")
    interval: str | None = Field(default=None, alias="Interval")
    period: int | None = Field(default=None, alias="Period")
    max_periods: int | None = Field(default=None, alias="MaxPeriods")
    customer_receipt: dict[str, Any] | None = Field(default=None, alias="CustomerReceipt")


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

    def get_transaction(self, *, transaction_id: int) -> CloudPaymentsTransactionResponse | None:
        response = self.send(
            PaymentsApiRequest(
                operation="get_transaction",
                path="/payments/get",
                payload={"TransactionId": transaction_id},
                is_idempotent=True,
            ),
            response_model=CloudPaymentsTransactionResponse,
        )
        if self._is_not_found(response):
            return None
        return self._transaction_lookup_response("get_transaction", response)

    def find_transaction(self, *, invoice_id: str) -> CloudPaymentsTransactionResponse | None:
        response = self.send(
            PaymentsApiRequest(
                operation="find_transaction",
                path="/v2/payments/find",
                payload={"InvoiceId": invoice_id},
                is_idempotent=True,
            ),
            response_model=CloudPaymentsTransactionResponse,
        )
        if self._is_not_found(response):
            return None
        return self._transaction_lookup_response("find_transaction", response)

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
                is_mutating=True,
            ),
            response_model=CloudPaymentsRefundResponse,
        )
        response = self._require_success("refund", response)
        if response.model is None or response.model.transaction_id <= 0:
            raise PaymentsResponseValidationError(
                "payments_api_response_validation_error",
                message_safe="Payment provider refund response is missing a transaction id.",
                details_safe={"provider": self.config.provider, "operation": "refund"},
            )
        return response

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
                payload=request.model_dump(mode="python", by_alias=True, exclude_none=True),
                idempotency_key=idempotency_key,
                is_idempotent=True,
                is_mutating=True,
            ),
            response_model=CloudPaymentsSubscriptionResponse,
        )
        response = self._require_success("create_subscription", response)
        self._require_subscription_model("create_subscription", response)
        return response

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
                payload=request.model_dump(mode="python", by_alias=True, exclude_none=True),
                idempotency_key=idempotency_key,
                is_idempotent=True,
                is_mutating=True,
            ),
            response_model=CloudPaymentsSubscriptionResponse,
        )
        response = self._require_success("update_subscription", response)
        self._require_subscription_model("update_subscription", response)
        return response

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
                is_mutating=True,
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

    def _outcome_from_response(
        self,
        request: PaymentsApiRequest,
        response: BaseModel,
    ) -> PaymentsApiOperationOutcome:
        if (
            isinstance(response, CloudPaymentsTransactionResponse)
            and request.operation in {"get_transaction", "find_transaction"}
            and response.model is not None
        ):
            return PaymentsApiOperationOutcome.SUCCEEDED
        if isinstance(response, CloudPaymentsApiResponse) and not response.success and not self._is_not_found(response):
            return PaymentsApiOperationOutcome.OPERATION_DECLINED
        return super()._outcome_from_response(request, response)

    @staticmethod
    def _is_not_found(response: CloudPaymentsApiResponse) -> bool:
        return (
            not response.success and response.message is not None and response.message.strip().casefold() == "not found"
        )

    def _require_success(
        self,
        operation: str,
        response: CloudPaymentsApiResponse,
    ) -> CloudPaymentsApiResponse:
        if response.success:
            return response
        error = PaymentsOperationDeclinedError(
            "cloudpayments_operation_declined",
            provider=self.config.provider,
            operation=operation,
            message_safe="CloudPayments declined the operation.",
        )
        logger.warning(
            "CloudPayments operation declined.",
            extra={
                "structured": {
                    "provider": self.config.provider,
                    "operation": operation,
                    "code": error.code,
                }
            },
        )
        raise error

    def _transaction_lookup_response(
        self,
        operation: str,
        response: CloudPaymentsTransactionResponse,
    ) -> CloudPaymentsTransactionResponse:
        if response.success or response.model is not None:
            return response
        return self._require_success(operation, response)

    def _require_subscription_model(
        self,
        operation: str,
        response: CloudPaymentsSubscriptionResponse,
    ) -> None:
        if response.model is not None and response.model.subscription_id.strip():
            return
        raise PaymentsResponseValidationError(
            "payments_api_response_validation_error",
            message_safe="Payment provider subscription response is missing a subscription id.",
            details_safe={"provider": self.config.provider, "operation": operation},
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
