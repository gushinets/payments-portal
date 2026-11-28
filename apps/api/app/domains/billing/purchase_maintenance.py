"""Lock and verify the local state of a quiesced operator write."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.domains.billing.customer_scope import connection_account
from app.domains.billing.customers import lock_customer, lock_user
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases.contracts import PurchaseRefused
from app.infrastructure.persistence.billing_connections import ConnectionScopeBusy, billing_lock_key, lock_billing_key
from app.infrastructure.queries import billing_operator, billing_reconciliation, purchases
from app.models import (
    BillingPurchaseScopeHold,
    BillingWorkItem,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalSubscription,
    PurchaseIntent,
)


@dataclass(frozen=True)
class MaintenanceState:
    hold: BillingPurchaseScopeHold | None
    operations: list[ExternalCreateOperation]
    subscription: ExternalSubscription | None
    work: list[BillingWorkItem]
    owned_scopes: set[tuple[str, str]]
    now: datetime


@contextmanager
def maintenance_session(factory: SessionFactory) -> Iterator[Session]:
    try:
        with factory() as db:
            yield db
    except (ConnectionScopeBusy, DBAPIError) as error:
        if isinstance(error, ConnectionScopeBusy) or getattr(error.orig, "sqlstate", None) == "55P03":
            raise PurchaseRefused("billing_busy", 503) from None
        raise


def lock_owned_purchase(
    db: Session, configuration: Settings, user_id: UUID, purchase_id: UUID, *, stale_code: str
) -> tuple[PurchaseIntent, ExternalBillingCustomer]:
    customer_id = purchases.owned_customer_id(db, user_id, purchase_id)
    if customer_id is None:
        raise PurchaseRefused("purchase_not_found", 404)
    user = lock_user(db, user_id)
    if (user.tenant_id, user.region) != (configuration.instance_tenant_id, configuration.instance_region):
        raise PurchaseRefused("purchase_not_found", 404)
    customer = lock_customer(db, customer_id)
    row = purchases.owned(db, user_id, purchase_id, lock=True)
    if (
        row is None
        or row.customer_id != customer.customer_id
        or customer.user_id != user_id
        or row.external_billing_account_id != customer.external_billing_account_id
        or customer.external_billing_account_id != connection_account(db, configuration)
        or customer.provider_origin not in {None, configuration.lbx_provider_origin}
    ):
        raise PurchaseRefused(stale_code, 409)
    return row, customer


def lock_financial_object(db: Session, account_id: str, kind: Kind, external_id: str) -> None:
    """Serialize the writers that can first record a provider object's identity."""
    if db.get_bind().dialect.name != "postgresql":
        return
    try:
        lock_billing_key(
            db, billing_lock_key("payments-portal/financial-object/v1", account_id, kind.value, external_id)
        )
    except ConnectionScopeBusy:
        raise PurchaseRefused("billing_busy", 503) from None


def guard_maintenance_write(
    db: Session, row: PurchaseIntent, objects: set[tuple[Kind, str]], *, stale_code: str
) -> MaintenanceState:
    """Check visible activity after stop/drain, with the owner rows already locked."""
    account = row.external_billing_account_id
    if db.get_bind().dialect.name == "postgresql":
        lock_billing_key(db, billing_lock_key("payments-portal/purchase-maintenance/v1", account, str(row.customer_id)))
    for kind, external_id in sorted(objects):
        lock_financial_object(db, account, kind, external_id)

    hold = None if row.state.resolved else purchases.hold(db, row.user_id, row.product_id, lock=True)
    operations = purchases.operations(db, row.purchase_intent_id, lock=True)
    sub = purchases.linked_subscription(db, row.purchase_intent_id)
    by_kind = {op.operation_kind: op for op in operations}
    if len(operations) != 2 or set(by_kind) != {Kind.AGREEMENT, Kind.SUBSCRIPTION}:
        raise PurchaseRefused(stale_code, 409)
    if sub is not None and (
        sub.external_agreement_id != by_kind[Kind.AGREEMENT].bound_external_object_id
        or sub.external_subscription_id != by_kind[Kind.SUBSCRIPTION].bound_external_object_id
    ):
        raise PurchaseRefused(stale_code, 409)
    scopes = {("purchase_intent", str(row.purchase_intent_id))}
    scopes.update(("create_operation", str(op.create_operation_id)) for op in operations)
    if sub is not None:
        scopes.add(("subscription", str(sub.subscription_id)))
    work = [
        item
        for item in billing_operator.work(db, tuple(reference for _, reference in scopes), limit=None, lock=True)
        if (item.scope_kind, item.scope_reference) in scopes
    ]
    now = as_utc(billing_reconciliation.database_now(db))
    if billing_operator.customer_work_active(db, row.customer_id, account, now):
        raise PurchaseRefused("billing_busy", 503)
    return MaintenanceState(hold, operations, sub, work, scopes, now)
