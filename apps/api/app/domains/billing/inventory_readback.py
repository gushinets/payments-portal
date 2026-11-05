"""Capture and apply canonical inventory findings in stable business order."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.domains.billing.customers import lock_user, lock_customer
from app.domains.billing.readback import capture_readback_in_transaction, apply_readback_in_transaction
from app.domains.billing.readback_contracts import BoundReadbackSubject, ScopedReadbackFinding, ReadbackRecheck
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases import service
from app.infrastructure.queries import billing_background, purchases


def capture_inventory_in_transaction(
    db: Session,
    configuration: Settings,
    customer_id: UUID,
    *,
    deadline: datetime,
) -> tuple[BoundReadbackSubject, ...]:
    customer = billing_background.customer(db, customer_id)
    lock_user(db, customer.user_id)
    lock_customer(db, customer_id)
    rows = sorted(
        billing_background.customer_purchases(db, customer_id),
        key=lambda row: (row.product_id, str(row.purchase_intent_id)),
    )
    result = []
    for row in rows:
        # Unbound neighbors have no hypothetical subscription scheduling subject.
        if purchases.linked_subscription(db, row.purchase_intent_id, lock=False) is None:
            continue
        purchase = service._snapshot(db, row)
        subject = capture_readback_in_transaction(db, configuration, purchase, deadline=deadline)
        if isinstance(subject, BoundReadbackSubject):
            result.append(subject)
    return tuple(result)


def capture_inventory(
    factory: SessionFactory,
    configuration: Settings,
    customer_id: UUID,
    *,
    deadline: datetime,
) -> tuple[BoundReadbackSubject, ...]:
    with factory() as db:
        result = capture_inventory_in_transaction(db, configuration, customer_id, deadline=deadline)
        db.commit()
        return result


def apply_findings(
    db: Session,
    configuration: Settings,
    findings: tuple[ScopedReadbackFinding, ...],
) -> list[dict[str, str]]:
    outcomes = []
    for finding in sorted(
        findings, key=lambda item: (item.subject.purchase.accepted.selection.product_id, str(item.subject.purchase.id))
    ):
        # An inventory attempt has no extra source-read budget. Ordering uncertainty
        # retains only its exact original subject's urgent hint.
        try:
            outcome = apply_readback_in_transaction(db, configuration, finding)
        except ReadbackRecheck:
            outcome = apply_readback_in_transaction(db, configuration, finding, hint_only=True)
        outcomes.append({"purchase_intent_id": str(finding.subject.purchase.id), "outcome": outcome})
    return outcomes


def apply_inventory_findings(
    factory: SessionFactory,
    configuration: Settings,
    findings: tuple[ScopedReadbackFinding, ...],
) -> None:
    with factory() as db:
        apply_findings(db, configuration, findings)
        db.commit()
