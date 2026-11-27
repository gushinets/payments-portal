"""Revalidate a payment Widget opening before attempting its optional enqueue."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.domains.billing.customers import lock_customer, lock_user
from app.domains.billing.reconciliation_contracts import RECONCILIATION_READ_SCHEMAS, SubscriptionLifecycleReason
from app.domains.catalog.publication import SessionFactory
from app.infrastructure.queries import billing_reconciliation as queries, purchases
from app.models import (
    BillingStateObservation,
    ExternalBillingCustomerBindingState as Binding,
    ExternalSubscription,
    ExternalSubscriptionCommercialAccessStatus as Commercial,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
    PurchaseIntent,
    PurchaseIntentState,
)

logger = logging.getLogger("payment_portal.billing")


@dataclass(frozen=True)
class WidgetActivationOpening:
    user_id: UUID
    purchase_id: UUID
    customer_id: UUID
    account_id: str
    subscription_id: UUID
    prepared_at: datetime


WidgetActivationWriter = Callable[[Session, WidgetActivationOpening], None]


class _LifecycleEvidence(BaseModel):
    reasons: tuple[str, ...]


def awaiting_first_activation(
    db: Session,
    purchase: PurchaseIntent,
    subscription: ExternalSubscription,
    *,
    existing_window: bool = False,
) -> bool:
    if subscription.commercial_access_status != Commercial.ELIGIBLE:
        return False
    if subscription.lifecycle_status == Lifecycle.INACTIVE:
        expected_reason = SubscriptionLifecycleReason.WAITING
    elif existing_window and subscription.lifecycle_status == Lifecycle.ACTIVE:
        if subscription.financial_access_status == Financial.BLOCKED:
            expected_reason = SubscriptionLifecycleReason.FINANCIAL_BLOCK
        elif subscription.financial_access_status == Financial.ALLOWED:
            # Regular reconciliation can verify activation before inventory selects the first primary.
            expected_reason = SubscriptionLifecycleReason.ACTIVE
        else:
            return False
    else:
        return False
    observation = (
        db.get(BillingStateObservation, subscription.latest_observation_id)
        if subscription.latest_observation_id
        else None
    )
    if observation is None or observation.evidence_schema_version not in RECONCILIATION_READ_SCHEMAS:
        return False
    try:
        evidence = _LifecycleEvidence.model_validate(observation.evidence_document)
    except ValidationError:
        return False
    if expected_reason not in evidence.reasons:
        return False
    scope = queries.scope(db, purchase.user_id, purchase.product_id)
    return (
        scope is not None
        and scope.primary_subscription_id is None
        and not queries.has_primary_selection(db, subscription.subscription_id)
    )


def enqueue_widget_activation(
    factory: SessionFactory, opening: WidgetActivationOpening, writer: WidgetActivationWriter, *, request_id: str
) -> None:
    try:
        with factory() as db:
            # The shared user/customer locks bound PostgreSQL lock and statement
            # waits for this transaction, including the writer's enqueue.
            lock_user(db, opening.user_id)
            customer = lock_customer(db, opening.customer_id)
            if customer.binding_state != Binding.BOUND:
                return
            row = purchases.owned(db, opening.user_id, opening.purchase_id, lock=True)
            if (
                row is None
                or row.state != PurchaseIntentState.LINKED
                or row.customer_id != opening.customer_id
                or row.external_billing_account_id != opening.account_id
            ):
                return
            hold = purchases.hold(db, row.user_id, row.product_id)
            if hold is None or hold.purchase_intent_id != opening.purchase_id:
                return
            sub = purchases.linked_subscription(db, opening.purchase_id)
            if (
                sub is None
                or sub.subscription_id != opening.subscription_id
                or not awaiting_first_activation(db, row, sub)
                or queries.open_reviews(db, sub.subscription_id)
            ):
                return
            writer(db, opening)
            db.commit()
    except Exception as error:
        logger.warning(
            "widget_activation_enqueue_failed",
            extra={
                "structured": {
                    "request_id": request_id,
                    "purchase_id": str(opening.purchase_id),
                    "subscription_id": str(opening.subscription_id),
                    "error_type": type(error).__name__,
                }
            },
        )
