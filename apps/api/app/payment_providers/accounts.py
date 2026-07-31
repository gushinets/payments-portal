from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import CountryRegionRule, PaymentProviderAccount, User
from app.payment_providers.contracts import PaymentProviderAdapter
from app.payment_providers.registry import PaymentProviderRegistry


def _default_provider_code(db: Session, *, region: str) -> str | None:
    rule = (
        db.query(CountryRegionRule)
        .filter(
            CountryRegionRule.region == region,
            CountryRegionRule.market_enabled.is_(True),
        )
        .order_by(CountryRegionRule.country_code.asc())
        .first()
    )
    return rule.default_payment_provider if rule else None


def get_or_create_checkout_provider_account(
    db: Session,
    *,
    user: User,
    registry: PaymentProviderRegistry,
) -> tuple[PaymentProviderAccount, PaymentProviderAdapter]:
    provider_code = _default_provider_code(db, region=user.region)
    query = db.query(PaymentProviderAccount).filter(
        PaymentProviderAccount.tenant_id == user.tenant_id,
        PaymentProviderAccount.region == user.region,
        PaymentProviderAccount.enabled.is_(True),
    )
    if provider_code:
        query = query.filter(PaymentProviderAccount.provider == provider_code)
    account = query.order_by(PaymentProviderAccount.created_at.asc()).first()

    if account is not None:
        try:
            return account, registry.get(account.provider)
        except LookupError as exc:
            raise HTTPException(status_code=503, detail="payment_provider_unavailable") from exc

    if provider_code is None:
        adapter = registry.sole_adapter()
        if adapter is None:
            raise HTTPException(status_code=503, detail="payment_provider_unavailable")
    else:
        try:
            adapter = registry.get(provider_code)
        except LookupError as exc:
            raise HTTPException(status_code=503, detail="payment_provider_unavailable") from exc

    account = PaymentProviderAccount(
        **adapter.default_account_fields(tenant_id=user.tenant_id, region=user.region)
    )
    db.add(account)
    db.flush()
    return account, adapter
