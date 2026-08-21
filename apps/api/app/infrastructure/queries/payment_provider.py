from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import CountryRegionRule, PaymentProviderAccount


def get_default_payment_provider_code(
    db: Session,
    *,
    region: str,
) -> str | None:
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


def get_enabled_checkout_provider_account(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    provider_code: str | None = None,
) -> PaymentProviderAccount | None:
    query = db.query(PaymentProviderAccount).filter(
        PaymentProviderAccount.tenant_id == tenant_id,
        PaymentProviderAccount.region == region,
        PaymentProviderAccount.enabled.is_(True),
    )
    if provider_code:
        query = query.filter(PaymentProviderAccount.provider == provider_code)
    return query.order_by(PaymentProviderAccount.created_at.asc()).first()


def get_enabled_provider_account(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    provider_code: str,
) -> PaymentProviderAccount | None:
    return (
        db.query(PaymentProviderAccount)
        .filter(
            PaymentProviderAccount.tenant_id == tenant_id,
            PaymentProviderAccount.region == region,
            PaymentProviderAccount.provider == provider_code,
            PaymentProviderAccount.enabled.is_(True),
        )
        .order_by(PaymentProviderAccount.created_at.asc())
        .first()
    )
