"""Outer transaction boundaries for the durable reservation/send protocol only."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.persistence import external_creates, purchase_scopes
from app.infrastructure.persistence.external_creates import ExternalCreateClaim
from app.infrastructure.persistence.purchase_scopes import (
    PurchaseScopeIdentity,
    PurchaseScopeReleaseEvidence,
    PurchaseScopeReservation,
)
from app.models import PurchaseIntent


def reserve_purchase_scope(
    factory: sessionmaker[Session],
    *,
    scope: PurchaseScopeIdentity,
    client_idempotency_key: str,
    create_intent: Callable[[Session], PurchaseIntent],
    replay_matches: Callable[[PurchaseIntent], bool],
) -> PurchaseScopeReservation:
    """Retry the entire short transaction, never a poisoned session or source I/O."""
    retryable = {
        "uq_purchase_scope_user_product",
        "uq_purchase_intents_client_idempotency",
        "uq_external_billing_customers_account_user",
        "uq_external_billing_customers_billing_customer_key",
    }
    for attempt in range(3):
        try:
            with factory.begin() as db:
                db.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
                return purchase_scopes.reserve_purchase_scope(
                    db,
                    scope=scope,
                    client_idempotency_key=client_idempotency_key,
                    create_intent=create_intent,
                    replay_matches=replay_matches,
                )
        except IntegrityError as error:
            constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            if constraint not in retryable or attempt == 2:
                raise
    raise AssertionError("unreachable purchase reservation retry")


def release_purchase_scope(
    factory: sessionmaker[Session],
    *,
    scope: PurchaseScopeIdentity,
    expected_epoch: int,
    evidence: PurchaseScopeReleaseEvidence,
) -> None:
    with factory.begin() as db:
        purchase_scopes.release_purchase_scope(db, scope=scope, expected_epoch=expected_epoch, evidence=evidence)


def claim_external_create(
    factory: sessionmaker[Session],
    operation_id: UUID,
    *,
    now: datetime,
) -> ExternalCreateClaim | None:
    """Send permission escapes only after the claim/clock/due item commit succeeds."""
    with factory.begin() as db:
        return external_creates.claim_external_create(db, operation_id, now=now)


def bind_external_create(
    factory: sessionmaker[Session],
    claim: ExternalCreateClaim,
    *,
    verified_external_object_id: str,
    now: datetime,
) -> bool:
    with factory.begin() as db:
        return external_creates.bind_external_create(
            db, claim, verified_external_object_id=verified_external_object_id, now=now
        )
