"""Local ownership evidence for customer-wide subscription inventory."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.catalog.publication import SessionFactory
from app.domains.billing.customers import lock_user
from app.domains.purchases.contracts import Purchase
from app.domains.purchases.service import _locked, _snapshot, _verify_original_consent
from app.infrastructure.queries.billing_customers import open_customer_reviews
from app.infrastructure.queries import purchases as queries
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State
from app.models import PurchaseIntentState as IntentState


def _deadline_only_review(db: Session, purchase: Purchase) -> bool:
    subscription = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    if purchase.state != IntentState.MANUAL_REVIEW or subscription.state != State.MANUAL_REVIEW:
        return False
    reviews = [case for op in purchase.operations for case in open_customer_reviews(db, op.id)]
    return bool(reviews) and all(
        case.scope_reference == str(subscription.id)
        and case.reason_code == "external_create_outcome_unknown:subscription"
        for case in reviews
    )


def deadline_only_inventory_recovery(factory: SessionFactory, purchase: Purchase) -> bool:
    """Classify inventory waiting only; the shared financial writer owns binding."""
    if purchase.state != IntentState.MANUAL_REVIEW:
        return False
    with factory() as db:
        _locked(db, purchase)
        return _deadline_only_review(db, purchase)


def other_inventory_purchase(
    factory: SessionFactory, purchase: Purchase, provider_id: int, agreement_id: int
) -> Purchase | None:
    """Identify the owning purchase by its permanent dedicated-agreement binding."""
    with factory() as db:
        # Purchase transitions take this same bounded lock. Keep the row and
        # operation reads consistent; release it before any provider I/O.
        lock_user(db, purchase.user_id)
        row = queries.agreement_purchase(
            db,
            user_id=purchase.user_id,
            customer_id=purchase.customer_id,
            account_id=purchase.account_id,
            agreement_id=str(agreement_id),
        )
        if row is None or row.product_id == purchase.accepted.selection.product_id:
            return None
        other = _snapshot(db, row)
        _verify_original_consent(db, row, other.accepted)
        bindings = {op.kind: op for op in other.operations}
        if (
            not other.held
            or other.accepted.provider_origin != purchase.accepted.provider_origin
            or not {Kind.AGREEMENT, Kind.SUBSCRIPTION}.issubset(bindings)
            or bindings[Kind.AGREEMENT].state not in {State.BOUND, State.MANUAL_REVIEW}
            or bindings[Kind.AGREEMENT].bound_id != str(agreement_id)
        ):
            return None
        subscription = bindings[Kind.SUBSCRIPTION]
        # Review does not erase a permanent binding to another product. The
        # caller still proves its original agreement and effective terms.
        if (
            subscription.bound_id is not None
            and other.state in {IntentState.LINKED, IntentState.MANUAL_REVIEW}
            and subscription.state in {State.BOUND, State.MANUAL_REVIEW}
        ):
            return other if subscription.bound_id == str(provider_id) else None
        # LBX can expose a successful send before its receipt or final binding
        # commits locally. This only identifies work to wait for, never a binding
        # or permission to send. Point proof remains the caller's responsibility.
        if (
            (
                (
                    other.state in {IntentState.PREPARING, IntentState.AWAITING_EXTERNAL_RESULT}
                    and subscription.state in {State.POSSIBLE_SEND, State.UNKNOWN}
                )
                or _deadline_only_review(db, other)
            )
            and bindings[Kind.AGREEMENT].state == State.BOUND
            and subscription.bound_id is None
            and subscription.candidate_id in {None, str(provider_id)}
        ):
            return other
        return None
