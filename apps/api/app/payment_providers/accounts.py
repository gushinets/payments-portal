from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.queries.payment_provider import (
    get_default_payment_provider_code,
    get_enabled_checkout_provider_account,
    get_enabled_provider_account,
)
from app.models import PaymentProviderAccount, User
from app.payment_providers.contracts import PaymentProviderAdapter
from app.payment_providers.exceptions import CheckoutProviderUnavailableError
from app.payment_providers.registry import PaymentProviderRegistry


def get_or_create_checkout_provider_account(
    db: Session,
    *,
    user: User,
    registry: PaymentProviderRegistry,
) -> tuple[PaymentProviderAccount, PaymentProviderAdapter]:
    provider_code = get_default_payment_provider_code(db, region=user.region)
    account = get_enabled_checkout_provider_account(
        db,
        tenant_id=user.tenant_id,
        region=user.region,
        provider_code=provider_code,
    )

    if account is not None:
        try:
            return account, registry.get(account.provider)
        except LookupError as exc:
            raise CheckoutProviderUnavailableError(
                reason="provider_not_registered",
            ) from exc

    if provider_code is None:
        adapter = registry.sole_adapter()
        if adapter is None:
            raise CheckoutProviderUnavailableError(
                reason="provider_not_resolved",
            )
    else:
        try:
            adapter = registry.get(provider_code)
        except LookupError as exc:
            raise CheckoutProviderUnavailableError(
                reason="provider_not_registered",
            ) from exc

    account = PaymentProviderAccount(**adapter.default_account_fields(tenant_id=user.tenant_id, region=user.region))
    try:
        with db.begin_nested():
            db.add(account)
            db.flush()
    except IntegrityError:
        account = get_enabled_provider_account(
            db,
            tenant_id=user.tenant_id,
            region=user.region,
            provider_code=adapter.provider_code,
        )
        if account is None:
            raise
    return account, adapter
