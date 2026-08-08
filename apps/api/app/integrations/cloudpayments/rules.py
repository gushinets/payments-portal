from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import Order, PaymentProviderAccount


def find_default_provider_account(
    db: Session,
    *,
    for_update: bool = False,
) -> PaymentProviderAccount | None:
    query = (
        db.query(PaymentProviderAccount)
        .filter(
            PaymentProviderAccount.provider == "cloudpayments",
            PaymentProviderAccount.tenant_id == "anytoolai",
            PaymentProviderAccount.region == "ru",
            PaymentProviderAccount.enabled.is_(True),
        )
        .order_by(PaymentProviderAccount.created_at.asc())
    )
    if for_update:
        query = query.with_for_update()
    return query.first()


def payment_schema_error(
    *,
    order: Order,
    endpoint: str,
    payload: dict[str, Any],
) -> str | None:
    mode = str(order.metadata_.get("payment_mode") or "charge").strip().lower()
    provider_status = str(payload.get("Status") or payload.get("status") or "").strip().lower()
    if endpoint in {"confirm", "cancel"} and mode != "auth":
        return "payment_schema_mismatch"
    if endpoint == "confirm" and provider_status != "completed":
        return "payment_schema_mismatch"
    if endpoint == "check":
        if mode == "auth" and provider_status != "authorized":
            return "payment_schema_mismatch"
        if mode != "auth" and provider_status != "completed":
            return "payment_schema_mismatch"
    if endpoint == "pay":
        if mode == "auth" and provider_status != "authorized":
            return "payment_schema_mismatch"
        if mode != "auth" and provider_status != "completed":
            return "payment_schema_mismatch"
    return None
