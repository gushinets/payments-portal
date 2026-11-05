"""Synthetic original proof and durable deadline execution for DB fixtures."""

from dataclasses import replace
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.purchase_recovery import original_command
from app.core.time import utc_now
from app.domains.billing import background_recovery, work
from app.domains.billing.operator_contracts import OriginalOperationProof
from app.domains.billing.operator_review import digest
from app.domains.billing.reconciliation_contracts import SubscriptionCandidateSubject
from app.domains.billing.work_contracts import WorkLane
from app.domains.purchases import service
from app.domains.purchases.contracts import FinancialOperation, Purchase
from app.integrations.lbx.customer import LbxUser
from app.integrations.lbx.financial import Agreement, Subscription
from app.integrations.lbx.reconciliation import normalize_subscription
from app.models import ExternalCreateOperation, ExternalCreateOperationState as State
from apps.api.tests.factories.reconciliation import tariff_factory
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport


def original_proof(
    factory: sessionmaker[Session], purchase: Purchase, operation: FinancialOperation, transport: PurchaseTransport
) -> OriginalOperationProof:
    configuration = step1_settings()
    customer = service.customer_for_purchase(factory, configuration, purchase)
    started = utc_now()
    proof = None
    if operation.kind == "subscription":
        agreement = next(op for op in purchase.operations if op.kind == "agreement")
        point = next(row for row in transport.subscriptions if str(row["agreement_id"]) == agreement.bound_id)
        subject = SubscriptionCandidateSubject(
            purchase, customer, agreement.bound_id, agreement.key, str(point["subscription_id"])
        )
        owner = next(row for row in transport.agreements if str(row["agreement_id"]) == agreement.bound_id)
        proof = normalize_subscription(
            subject,
            configuration,
            user=LbxUser.model_validate(transport.customer),
            agreement=Agreement.model_validate(owner),
            tariff=tariff_factory(subject),
            subscription=Subscription.model_validate(point),
        )
        proof = replace(proof, read_started_at=started, read_finished_at=utc_now())
    return OriginalOperationProof(
        started, utc_now(), digest(original_command(purchase, operation, customer)), customer, proof
    )


def advance_deadlines(factory: sessionmaker[Session], *, now: datetime) -> int:
    """Use the production queue/claim/apply owner, never the removed scanner."""
    with factory() as db:
        before = set(
            db.scalars(
                select(ExternalCreateOperation.create_operation_id).where(
                    ExternalCreateOperation.operation_state == State.MANUAL_REVIEW
                )
            )
        )
    with patch("app.infrastructure.queries.billing_reconciliation.database_now", return_value=now):
        while claim := work.claim_work(factory, step1_settings(), WorkLane.LOCAL):
            assert claim.kind == background_recovery.DEADLINE
            background_recovery.apply_deadline(factory, claim)
    with factory() as db:
        after = set(
            db.scalars(
                select(ExternalCreateOperation.create_operation_id).where(
                    ExternalCreateOperation.operation_state == State.MANUAL_REVIEW
                )
            )
        )
    return len(after - before)
