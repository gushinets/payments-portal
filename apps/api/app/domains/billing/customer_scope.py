"""Customer account admission inside the caller's short locked transaction."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.domains.billing.contracts import BillingRefused
from app.infrastructure.persistence.billing_connections import ConnectionScopeBusy, lock_connection_scope
from app.infrastructure.queries.billing_customers import connection_accounts, foreign_customer
from app.infrastructure.queries.commercial_mappings import connection_heads


def lock_customer_connection(db: Session, configuration: Settings) -> None:
    """User lock precedes origin; acquire origin before any product/row locks."""
    try:
        lock_connection_scope(
            db,
            tenant_id=configuration.instance_tenant_id,
            region=configuration.instance_region,
            provider_origin=configuration.lbx_provider_origin,
        )
    except ConnectionScopeBusy:
        raise BillingRefused("billing_busy", 503) from None


def customer_account(db: Session, configuration: Settings, user_id: UUID) -> str:
    """Prove scope under the shared lock before reserving a permanent identity.

    The caller already holds its user lock. Purchase admission acquires origin
    before product locking; reacquiring that same transaction lock is safe.
    """
    lock_customer_connection(db, configuration)
    accounts = connection_accounts(db, configuration.lbx_provider_origin)
    if len(accounts) > 1:
        raise BillingRefused("billing_connection_conflict", 409)
    account = next(iter(accounts), configuration.lbx_external_billing_account_id)
    # Only authorized publication can attach origin proof to a retained head.
    if any(
        head.provider_origin is None and head.external_billing_account_id != account
        for head in connection_heads(
            db,
            account_id=configuration.lbx_external_billing_account_id,
            provider_origin=configuration.lbx_provider_origin,
            legacy_account_id=configuration.lbx_legacy_credential_scope,
        )
    ):
        raise BillingRefused("billing_connection_conflict", 409)
    if foreign_customer(db, user_id, account):
        raise BillingRefused("billing_connection_conflict", 409)
    return account
