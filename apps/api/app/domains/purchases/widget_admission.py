"""One final local payment Widget decision, after all source I/O."""

from app.core.settings import Settings
from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.customers import require_widget_session
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases.contracts import Purchase, PurchaseRefused
from app.domains.purchases.service import _locked, _snapshot, _verify_original_consent
from app.models import PurchaseIntentState


def recheck_payment_purchase(
    factory: SessionFactory, configuration: Settings, token: str, expected: Purchase, customer: CustomerOpen
) -> None:
    """Hold user, customer and purchase locks until their combined check ends."""
    with factory() as db:
        user = require_widget_session(db, configuration, token, customer)
        if user.id != expected.user_id:
            raise PurchaseRefused("purchase_not_found", 404)
        if customer.customer_id != expected.customer_id:
            raise PurchaseRefused("billing_identity_unproven", 409)
        row = _locked(db, expected)
        _verify_original_consent(db, row, expected.accepted)
        current = _snapshot(db, row)
        if current.state != PurchaseIntentState.LINKED or tuple(
            op.admission_snapshot() for op in current.operations
        ) != tuple(op.admission_snapshot() for op in expected.operations):
            raise PurchaseRefused("purchase_not_prepared", 409)
