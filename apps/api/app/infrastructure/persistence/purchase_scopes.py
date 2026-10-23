"""Short PostgreSQL purchase transactions. No source or provider I/O belongs here.

The reservation callback and replay comparator must be DB-only/pure respectively.
An initial unique-key race retries the entire transaction in a fresh session,
including the callback; callers must not perform external effects in callbacks.
Application owns the retry and outer transaction (purchases/transactions.py).
Discovery/import writers must use this same scope lock and ownership epoch.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.models import (
    BillingPurchaseScopeHold,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    ExternalSubscription,
    ExternalSubscriptionLifecycleStatus,
    PurchaseIntent,
    PurchaseScopeHoldState,
    PurchaseScopeReleaseKind,
    User,
)


@dataclass(frozen=True)
class PurchaseScopeIdentity:
    user_id: UUID
    product_id: str
    tenant_id: str
    region: str
    external_billing_account_id: str


@dataclass(frozen=True)
class PurchaseScopeReservation:
    hold_id: UUID | None
    purchase_intent_id: UUID | None
    subscription_id: UUID | None
    ownership_epoch: int | None
    replay: bool
    occupied: bool


@dataclass(frozen=True)
class PurchaseScopeReleaseEvidence:
    kind: PurchaseScopeReleaseKind
    proof_reference: str
    principal: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PurchaseScopeReleaseKind):
            raise ValueError("typed release kind required")
        if not self.proof_reference.strip() or not self.principal.strip():
            raise ValueError("release proof and audited principal required")
        if self.observed_at.utcoffset() is None:
            raise ValueError("aware release evidence timestamp required")


class PurchaseScopeConflict(ValueError):
    """Ambiguous provenance, changed replay meaning, or a stale ownership fence."""


def lock_purchase_scope(db: Session, user_id: UUID, product_id: str) -> BillingPurchaseScopeHold | None:
    """All subscription discovery/import and purchase writers share this lock."""
    return db.scalar(
        select(BillingPurchaseScopeHold)
        .where(BillingPurchaseScopeHold.user_id == user_id, BillingPurchaseScopeHold.product_id == product_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _historical_owner(
    db: Session,
    scope: PurchaseScopeIdentity,
    previous: BillingPurchaseScopeHold | None,
) -> tuple[UUID | None, UUID | None, str] | None:
    rows = db.execute(
        text("""
        SELECT p.purchase_intent_id, s.subscription_id,
               COALESCE(p.external_billing_account_id, s.external_billing_account_id) AS account_id
        FROM purchase_intents p FULL JOIN external_subscriptions s ON s.purchase_intent_id = p.purchase_intent_id
        WHERE COALESCE(p.user_id, s.user_id) = :user_id
          AND COALESCE(p.product_id, s.product_id) = :product_id
          AND (s.lifecycle_status <> 'ended'
               OR (p.state NOT IN ('resolved_no_external_effect', 'failed_before_external_effect')
                   AND (p.state <> 'linked' OR s.lifecycle_status IS DISTINCT FROM 'ended'))
               OR EXISTS (SELECT 1 FROM external_create_operations o
                          WHERE o.purchase_intent_id = p.purchase_intent_id AND o.resolved_at IS NULL))
    """),
        {"user_id": scope.user_id, "product_id": scope.product_id},
    ).all()
    owners = [
        (row.purchase_intent_id, row.subscription_id, row.account_id)
        for row in rows
        if previous is None
        or not (
            (row.purchase_intent_id is not None and row.purchase_intent_id == previous.purchase_intent_id)
            or (row.subscription_id is not None and row.subscription_id == previous.subscription_id)
        )
    ]
    if len(owners) > 1:
        raise PurchaseScopeConflict("historical purchase scope requires ownership reconciliation")
    return owners[0] if owners else None


def reserve_purchase_scope(
    db: Session,
    *,
    scope: PurchaseScopeIdentity,
    client_idempotency_key: str,
    create_intent: Callable[[Session], PurchaseIntent],
    replay_matches: Callable[[PurchaseIntent], bool],
) -> PurchaseScopeReservation:
    """Reserve atomically with legal evidence/intent creation supplied by Application.

    Replay comparison must cover the canonical accepted meaning, not just a price.
    Existing subscriptions and replays are read from PostgreSQL without source reads.
    The caller owns the outer transaction and may use the result only after commit.
    """
    user = db.scalar(
        select(User).where(
            User.id == scope.user_id,
            User.tenant_id == scope.tenant_id,
            User.region == scope.region,
        )
    )
    if user is None:
        raise PurchaseScopeConflict("purchase user scope does not match")
    hold = lock_purchase_scope(db, scope.user_id, scope.product_id)
    replay = db.scalar(
        select(PurchaseIntent).where(
            PurchaseIntent.external_billing_account_id == scope.external_billing_account_id,
            PurchaseIntent.user_id == scope.user_id,
            PurchaseIntent.client_idempotency_key == client_idempotency_key,
        )
    )
    if replay is not None:
        if replay.product_id != scope.product_id or not replay_matches(replay):
            raise PurchaseScopeConflict("idempotency key has different accepted meaning")
        if hold is None:
            # READ COMMITTED can see the winner's atomic intent/hold commit in
            # the replay query after the earlier scope lookup saw no row.
            hold = lock_purchase_scope(db, scope.user_id, scope.product_id)
        return PurchaseScopeReservation(
            hold.hold_id if hold else None,
            replay.purchase_intent_id,
            hold.subscription_id if hold else None,
            hold.ownership_epoch if hold else None,
            True,
            False,
        )
    if hold is not None and hold.hold_state == PurchaseScopeHoldState.HELD:
        return PurchaseScopeReservation(
            hold.hold_id,
            hold.purchase_intent_id,
            hold.subscription_id,
            hold.ownership_epoch,
            False,
            True,
        )
    historical = _historical_owner(db, scope, hold)
    if historical is not None:
        purchase_id, subscription_id, account_id = historical
    else:
        intent = create_intent(db)
        db.flush()
        if (intent.user_id, intent.product_id, intent.external_billing_account_id, intent.client_idempotency_key) != (
            scope.user_id,
            scope.product_id,
            scope.external_billing_account_id,
            client_idempotency_key,
        ) or not replay_matches(intent):
            raise PurchaseScopeConflict("new purchase does not match reservation")
        purchase_id, subscription_id, account_id = intent.purchase_intent_id, None, scope.external_billing_account_id
    if hold is None:
        hold = BillingPurchaseScopeHold(
            user_id=scope.user_id,
            product_id=scope.product_id,
            tenant_id=scope.tenant_id,
            region=scope.region,
            external_billing_account_id=account_id,
            purchase_intent_id=purchase_id,
            subscription_id=subscription_id,
        )
        db.add(hold)
    else:
        hold.purchase_intent_id = purchase_id
        hold.subscription_id = subscription_id
        hold.external_billing_account_id = account_id
        hold.ownership_epoch += 1
        hold.hold_state = PurchaseScopeHoldState.HELD
        hold.released_at = None
    db.flush()
    return PurchaseScopeReservation(
        hold.hold_id,
        purchase_id,
        subscription_id,
        hold.ownership_epoch,
        False,
        historical is not None,
    )


def release_purchase_scope(
    db: Session,
    *,
    scope: PurchaseScopeIdentity,
    expected_epoch: int,
    evidence: PurchaseScopeReleaseEvidence,
) -> None:
    """Persist proven release and retain owner records and append-only audit.

    Evidence is produced by authoritative readback/support outside this transaction;
    elapsed time, source availability, payment state and browser state are not proof.
    """
    hold = lock_purchase_scope(db, scope.user_id, scope.product_id)
    if hold is None or hold.ownership_epoch != expected_epoch or hold.hold_state != PurchaseScopeHoldState.HELD:
        raise PurchaseScopeConflict("stale purchase scope release")
    if (hold.tenant_id, hold.region, hold.external_billing_account_id) != (
        scope.tenant_id,
        scope.region,
        scope.external_billing_account_id,
    ):
        raise PurchaseScopeConflict("release scope does not match")
    if evidence.kind != PurchaseScopeReleaseKind.AUDITED_SUPPORT:
        unresolved = db.scalar(
            select(ExternalCreateOperation.create_operation_id)
            .join(
                ExternalBillingCustomer,
                ExternalBillingCustomer.customer_id == ExternalCreateOperation.customer_id,
            )
            .outerjoin(PurchaseIntent, PurchaseIntent.purchase_intent_id == ExternalCreateOperation.purchase_intent_id)
            .where(
                ExternalBillingCustomer.user_id == scope.user_id,
                ExternalCreateOperation.resolved_at.is_(None),
                or_(
                    PurchaseIntent.product_id == scope.product_id, ExternalCreateOperation.purchase_intent_id.is_(None)
                ),
            )
            .limit(1)
        )
        nonterminal = db.scalar(
            select(ExternalSubscription.subscription_id)
            .where(
                ExternalSubscription.user_id == scope.user_id,
                ExternalSubscription.product_id == scope.product_id,
                ExternalSubscription.lifecycle_status != ExternalSubscriptionLifecycleStatus.ENDED,
            )
            .limit(1)
        )
        if unresolved is not None or nonterminal is not None:
            raise PurchaseScopeConflict("unresolved create or nonterminal subscription retains purchase hold")
        if evidence.kind == PurchaseScopeReleaseKind.VERIFIED_TERMINAL:
            if hold.subscription_id is None:
                raise PurchaseScopeConflict("terminal release requires a linked subscription")
            subscription = db.get(ExternalSubscription, hold.subscription_id)
            if subscription is None or subscription.lifecycle_status != ExternalSubscriptionLifecycleStatus.ENDED:
                raise PurchaseScopeConflict("terminal subscription proof does not match")
    audit = list((hold.release_evidence_document or {}).get("releases", []))
    audit.append(
        {
            "kind": evidence.kind.value,
            "proof_reference": evidence.proof_reference,
            "principal": evidence.principal,
            "observed_at": evidence.observed_at.isoformat(),
            "ownership_epoch": hold.ownership_epoch,
            "purchase_intent_id": str(hold.purchase_intent_id) if hold.purchase_intent_id else None,
            "subscription_id": str(hold.subscription_id) if hold.subscription_id else None,
        }
    )
    hold.release_evidence_schema_version = "v1"
    hold.release_evidence_document = {"releases": audit}
    hold.hold_state = PurchaseScopeHoldState.RELEASED
    hold.released_at = evidence.observed_at
    hold.updated_at = evidence.observed_at
    hold.ownership_epoch += 1
