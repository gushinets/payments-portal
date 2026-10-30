"""Customer account admission within the caller's locked transaction."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.domains.billing.contracts import BillingRefused
from app.infrastructure.queries.billing_customers import connection_accounts, foreign_customer
from app.infrastructure.queries.commercial_mappings import connection_heads


def customer_account(db: Session, configuration: Settings, user_id: UUID) -> str:
    """Prove the connection scope before reserving a permanent customer identity."""
    accounts = connection_accounts(db, configuration.lbx_provider_origin)
    if len(accounts) > 1:
        raise BillingRefused("billing_connection_conflict", 409)
    account = next(iter(accounts), configuration.lbx_external_billing_account_id)
    # An ordinary account opening cannot prove a legacy head's origin. Refuse
    # before reserving a competing permanent identity; authorized publication
    # can bind the mutable head, after which both paths reuse its original scope.
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
