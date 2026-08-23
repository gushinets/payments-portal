#!/usr/bin/env python3
"""Opt-in CloudPayments sandbox verification for provider-neutral operations."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("APP_PUBLIC_BASE_URL", "http://localhost:3000")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("POSTGRES_DB", "payments")
os.environ.setdefault("POSTGRES_USER", "payments")
os.environ.setdefault("POSTGRES_PASSWORD", "payments")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CLOUDPAYMENTS_ENABLED", "false")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:3000")

from app.core.observability import redact  # noqa: E402
from app.integrations.cloudpayments.adapter import CloudPaymentsAdapter  # noqa: E402
from app.integrations.cloudpayments.api_client import (  # noqa: E402
    CloudPaymentsApiClient,
    CloudPaymentsApiClientConfig,
)
from app.payment_providers.contracts import (  # noqa: E402
    CancelRecurringSubscriptionRequest,
    CreateRecurringSubscriptionRequest,
    RefundRequest,
    TransactionLookupRequest,
    UpdateRecurringSubscriptionRequest,
)


class SandboxConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class SandboxProviderAccount:
    id: object = field(default_factory=uuid4)
    provider: str = "cloudpayments"
    enabled: bool = True
    public_identifier: str = ""
    default_currency: str = "RUB"
    config: dict[str, Any] = field(default_factory=dict)


def main() -> int:
    if os.getenv("CLOUDPAYMENTS_SANDBOX_VERIFY") != "1":
        _print_safe(
            "sandbox",
            {"status": "skipped", "reason": "CLOUDPAYMENTS_SANDBOX_VERIFY is not 1"},
        )
        return 0

    try:
        adapter, provider_account = _build_adapter()
        _verify_lookup(adapter, provider_account)
        _verify_refund(adapter, provider_account)
        _verify_recurring_lifecycle(adapter, provider_account)
    except SandboxConfigError as exc:
        _print_safe("sandbox", {"status": "configuration_error", "code": str(exc)})
        return 2
    return 0


def _build_adapter() -> tuple[CloudPaymentsAdapter, SandboxProviderAccount]:
    public_id = _required_env("CLOUDPAYMENTS_PUBLIC_ID")
    api_secret = _required_env("CLOUDPAYMENTS_API_SECRET")
    provider_account = SandboxProviderAccount(
        public_identifier=public_id,
        default_currency=_env("CLOUDPAYMENTS_SANDBOX_CURRENCY") or "RUB",
    )
    client = CloudPaymentsApiClient(
        config=CloudPaymentsApiClientConfig(
            base_url=_env("CLOUDPAYMENTS_API_BASE_URL")
            or "https://api.cloudpayments.ru",
            public_id=public_id,
            api_secret=api_secret,
            max_retries=int(_env("CLOUDPAYMENTS_SANDBOX_MAX_RETRIES") or "0"),
        )
    )
    return CloudPaymentsAdapter(api_client=client), provider_account


def _verify_lookup(
    adapter: CloudPaymentsAdapter, provider_account: SandboxProviderAccount
) -> None:
    payment_id = _env("CLOUDPAYMENTS_SANDBOX_LOOKUP_TRANSACTION_ID")
    invoice_id = _env("CLOUDPAYMENTS_SANDBOX_LOOKUP_INVOICE_ID")
    if not payment_id and not invoice_id:
        _print_safe(
            "lookup",
            {"status": "skipped", "reason": "lookup identifiers are not configured"},
        )
        return

    amount = _decimal_env("CLOUDPAYMENTS_SANDBOX_LOOKUP_AMOUNT")
    currency = _required_env("CLOUDPAYMENTS_SANDBOX_LOOKUP_CURRENCY")
    result = adapter.lookup_transaction(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=TransactionLookupRequest(
            provider_payment_id=payment_id,
            provider_invoice_id=invoice_id,
            merchant_order_id=_env("CLOUDPAYMENTS_SANDBOX_LOOKUP_MERCHANT_ORDER_ID"),
            expected_amount_minor=_amount_minor(amount),
            expected_currency=currency,
        ),
    )
    _print_safe("lookup", result.model_dump(mode="json"))


def _verify_refund(
    adapter: CloudPaymentsAdapter, provider_account: SandboxProviderAccount
) -> None:
    payment_id = _env("CLOUDPAYMENTS_SANDBOX_REFUND_TRANSACTION_ID")
    if not payment_id:
        _print_safe(
            "refund",
            {"status": "skipped", "reason": "refund transaction is not configured"},
        )
        return

    amount = _decimal_env("CLOUDPAYMENTS_SANDBOX_REFUND_AMOUNT")
    currency = _required_env("CLOUDPAYMENTS_SANDBOX_REFUND_CURRENCY")
    result = adapter.refund_payment(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=RefundRequest(
            provider_payment_id=payment_id,
            amount_minor=_amount_minor(amount),
            amount=amount,
            currency=currency,
            reason=_env("CLOUDPAYMENTS_SANDBOX_REFUND_REASON"),
            idempotency_key=_required_env(
                "CLOUDPAYMENTS_SANDBOX_REFUND_IDEMPOTENCY_KEY"
            ),
        ),
    )
    _print_safe("refund", result.model_dump(mode="json"))


def _verify_recurring_lifecycle(
    adapter: CloudPaymentsAdapter, provider_account: SandboxProviderAccount
) -> None:
    token = _env("CLOUDPAYMENTS_SANDBOX_RECURRING_TOKEN")
    if not token:
        _print_safe(
            "recurring",
            {"status": "skipped", "reason": "recurring token is not configured"},
        )
        return

    amount = _decimal_env("CLOUDPAYMENTS_SANDBOX_RECURRING_AMOUNT")
    currency = _required_env("CLOUDPAYMENTS_SANDBOX_RECURRING_CURRENCY")
    create_result = adapter.create_recurring_subscription(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=CreateRecurringSubscriptionRequest(
            payment_method_reference=token,
            account_id=_required_env("CLOUDPAYMENTS_SANDBOX_RECURRING_ACCOUNT_ID"),
            description=_env("CLOUDPAYMENTS_SANDBOX_RECURRING_DESCRIPTION")
            or "Sandbox recurring verification",
            amount_minor=_amount_minor(amount),
            amount=amount,
            currency=currency,
            interval_unit=_env("CLOUDPAYMENTS_SANDBOX_RECURRING_INTERVAL_UNIT")
            or "month",
            interval_count=int(
                _env("CLOUDPAYMENTS_SANDBOX_RECURRING_INTERVAL_COUNT") or "1"
            ),
            require_confirmation=_bool_env(
                "CLOUDPAYMENTS_SANDBOX_RECURRING_REQUIRE_CONFIRMATION"
            ),
            email=_env("CLOUDPAYMENTS_SANDBOX_RECURRING_EMAIL"),
            start_at=_required_env("CLOUDPAYMENTS_SANDBOX_RECURRING_START_AT"),
            max_periods=_optional_int_env(
                "CLOUDPAYMENTS_SANDBOX_RECURRING_MAX_PERIODS"
            ),
            idempotency_key=_required_env(
                "CLOUDPAYMENTS_SANDBOX_RECURRING_CREATE_IDEMPOTENCY_KEY"
            ),
        ),
    )
    _print_safe("recurring_create", create_result.model_dump(mode="json"))
    subscription_id = create_result.provider_subscription_id
    if not subscription_id:
        _print_safe(
            "recurring_update_cancel",
            {"status": "skipped", "reason": "subscription was not created"},
        )
        return

    update_result = adapter.update_recurring_subscription(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=UpdateRecurringSubscriptionRequest(
            provider_subscription_id=subscription_id,
            description=_env("CLOUDPAYMENTS_SANDBOX_RECURRING_UPDATE_DESCRIPTION")
            or "Sandbox recurring verification updated",
            idempotency_key=_required_env(
                "CLOUDPAYMENTS_SANDBOX_RECURRING_UPDATE_IDEMPOTENCY_KEY"
            ),
        ),
    )
    _print_safe("recurring_update", update_result.model_dump(mode="json"))

    cancel_result = adapter.cancel_recurring_subscription(
        provider_account=provider_account,  # type: ignore[arg-type]
        request=CancelRecurringSubscriptionRequest(
            provider_subscription_id=subscription_id,
            idempotency_key=_required_env(
                "CLOUDPAYMENTS_SANDBOX_RECURRING_CANCEL_IDEMPOTENCY_KEY"
            ),
        ),
    )
    _print_safe("recurring_cancel", cancel_result.model_dump(mode="json"))


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _required_env(name: str) -> str:
    value = _env(name)
    if not value:
        raise SandboxConfigError(f"{name}_required")
    return value


def _decimal_env(name: str) -> Decimal:
    raw = _required_env(name)
    try:
        return Decimal(raw)
    except Exception as exc:
        raise SandboxConfigError(f"{name}_invalid_decimal") from exc


def _optional_int_env(name: str) -> int | None:
    raw = _env(name)
    return int(raw) if raw else None


def _bool_env(name: str) -> bool:
    return _env(name).casefold() == "true"


def _amount_minor(amount: Decimal) -> int:
    scaled = amount * Decimal("100")
    if scaled != scaled.to_integral_value():
        raise SandboxConfigError("amount_must_have_minor_unit_precision")
    return int(scaled)


def _print_safe(name: str, payload: dict[str, Any]) -> None:
    print(json.dumps({name: redact(payload)}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
