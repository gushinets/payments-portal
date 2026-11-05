"""One final local payment Widget decision, after all source I/O."""

from app.core.settings import Settings
from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.customers import require_widget_session
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases.contracts import PurchaseRefused
from app.domains.billing.reconciliation_contracts import ReconciliationResult
from app.infrastructure.queries.billing_reconciliation import open_reviews
from app.domains.purchases.service import _locked, _snapshot, _verify_original_consent
from app.infrastructure.queries import purchases
from app.models import (
    ExternalSubscriptionLifecycleStatus as Lifecycle,
    PurchaseIntentState,
    ExternalSubscriptionCommercialAccessStatus as Commercial,
)


def recheck_payment_purchase(
    factory: SessionFactory, configuration: Settings, token: str, result: ReconciliationResult, customer: CustomerOpen
) -> None:
    """Hold user, customer and purchase locks until their combined check ends."""
    expected = result.subject.purchase
    with factory() as db:
        user = require_widget_session(db, configuration, token, customer)
        if user.id != expected.user_id:
            raise PurchaseRefused("purchase_not_found", 404)
        if customer.customer_id != expected.customer_id:
            raise PurchaseRefused("billing_identity_unproven", 409)
        row = _locked(db, expected)
        _verify_original_consent(db, row, expected.accepted)
        current = _snapshot(db, row)
        subscription = purchases.linked_subscription(db, row.purchase_intent_id)
        if (
            subscription is None
            or subscription.subscription_id != result.subject.subscription_id
            or subscription.commercial_access_status != Commercial.ELIGIBLE
            or open_reviews(db, subscription.subscription_id)
            or subscription.lifecycle_status == Lifecycle.ENDED
            or current.state != PurchaseIntentState.LINKED
            or current.accepted != expected.accepted
            or tuple(op.admission_snapshot() for op in current.operations)
            != tuple(op.admission_snapshot() for op in expected.operations)
        ):
            raise PurchaseRefused("purchase_not_prepared", 409)
