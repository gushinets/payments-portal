"""Atomic, negative-only source transitions. All HTTP belongs to Composition."""

from dataclasses import asdict, replace
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.domains.billing.contracts import BillingRefused, CustomerOpen
from app.domains.billing.customer_scope import connection_account
from app.domains.billing.customers import lock_customer, lock_user
from app.domains.billing.readback_contracts import (
    NEGATIVE_SCHEMA,
    BoundReadbackSubject,
    BoundSourceNegative,
    NegativeBasis,
    OriginalCreateReadbackSubject,
    ReadbackApplyResult,
    ReadbackRecheck,
    ReadbackSubject,
    ScopedReadbackFinding,
)
from app.domains.billing.reconciliation_facts import apply_negative_facts
from app.domains.billing.work import enroll_subscription, preserve_trust_deadline, verify_claim, verify_operation_claim
from app.domains.billing.work_contracts import WorkClaim
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import service
from app.domains.purchases.contracts import FINANCIAL_HINT_SCHEMA, Purchase
from app.infrastructure.queries import billing_reconciliation as queries, purchases
from app.infrastructure.queries.billing_customers import customer_operation
from app.models import (
    BillingProductAccessScope,
    BillingStateObservation,
    BillingStateObservationKind,
    ExternalBillingCustomerBindingState as Binding,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ExternalSubscription,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
    PurchaseIntent,
)


def _permanent(purchase: Purchase) -> set[tuple]:
    return {(op.id, op.kind, op.key, op.bound_id) for op in purchase.operations}


def _lock_purchase(
    db: Session,
    configuration: Settings,
    purchase: Purchase,
    expected_customer: CustomerOpen | None = None,
) -> tuple[PurchaseIntent, CustomerOpen, list[ExternalCreateOperation]]:
    user = lock_user(db, purchase.user_id)
    customer = lock_customer(db, purchase.customer_id)
    customer_op = customer_operation(db, purchase.customer_id)
    row = service._locked(db, purchase)
    operations = purchases.operations(db, purchase.id, lock=True)
    if (
        (user.tenant_id, user.region) != (configuration.instance_tenant_id, configuration.instance_region)
        or (row.user_id, row.customer_id, row.external_billing_account_id, row.product_id, row.mapping_revision_id)
        != (
            purchase.user_id,
            purchase.customer_id,
            purchase.account_id,
            purchase.accepted.selection.product_id,
            purchase.accepted.meaning.revision_id,
        )
        or service.accepted(row) != purchase.accepted
        or row.external_billing_account_id != connection_account(db, configuration)
        or customer.external_billing_account_id != purchase.account_id
        or customer.user_id != purchase.user_id
        or customer.provider_origin != purchase.accepted.provider_origin
        or customer.provider_origin != configuration.lbx_provider_origin
        or customer.binding_state != Binding.BOUND
        or customer_op is None
        or customer_op.operation_state != State.BOUND
        or not customer.provider_customer_id
        or customer_op.bound_external_object_id != customer.provider_customer_id
        or customer_op.request_correlation_key != customer.billing_customer_key
    ):
        raise BillingRefused("subscription_provenance_changed", 409)
    current_customer = CustomerOpen(
        customer.customer_id,
        customer_op.create_operation_id,
        customer_op.send_fence,
        customer.billing_customer_key,
        customer.provider_customer_id,
    )
    if expected_customer is not None and current_customer != expected_customer:
        raise BillingRefused("subscription_provenance_changed", 409)
    service._verify_original_consent(db, row, purchase.accepted)
    return row, current_customer, operations


def _verify_subject(
    db: Session,
    configuration: Settings,
    subject: ReadbackSubject,
) -> tuple[PurchaseIntent, list[ExternalCreateOperation]]:
    if (subject.tenant_id, subject.region) != (configuration.instance_tenant_id, configuration.instance_region):
        raise BillingRefused("subscription_provenance_changed", 409)
    row, _, operations = _lock_purchase(db, configuration, subject.purchase, subject.customer)
    if row.legal_acceptance_event_id != subject.legal_acceptance_event_id:
        raise BillingRefused("subscription_provenance_changed", 409)
    return row, operations


def _verify_bound(
    subject: ReadbackSubject, sub: ExternalSubscription, operations: list[ExternalCreateOperation]
) -> None:
    purchase = subject.purchase
    provider_id = (
        subject.provider_subscription_id if isinstance(subject, BoundReadbackSubject) else sub.external_subscription_id
    )
    if (
        (
            sub.purchase_intent_id,
            sub.customer_id,
            sub.user_id,
            sub.external_billing_account_id,
            sub.product_id,
            sub.mapping_revision_id,
        )
        != (
            purchase.id,
            purchase.customer_id,
            purchase.user_id,
            purchase.account_id,
            purchase.accepted.selection.product_id,
            purchase.accepted.meaning.revision_id,
        )
        or (sub.external_agreement_id, sub.external_subscription_id) != (subject.agreement_id, provider_id)
        or {
            (op.create_operation_id, op.operation_kind, op.request_correlation_key, op.bound_external_object_id)
            for op in operations
        }
        != _permanent(purchase)
    ):
        raise BillingRefused("subscription_provenance_changed", 409)


def _verify_refresh(expected: ReadbackSubject, current: Purchase, candidate_id: str | None) -> None:
    permanent = _permanent(expected.purchase)
    if isinstance(expected, OriginalCreateReadbackSubject) and candidate_id is not None:
        permanent = {
            (op_id, kind, key, candidate_id if op_id == expected.operation.id else bound)
            for op_id, kind, key, bound in permanent
        }
    if _permanent(current) != permanent:
        raise BillingRefused("subscription_provenance_changed", 409)


def capture_readback(
    factory: SessionFactory,
    configuration: Settings,
    purchase: Purchase,
    *,
    deadline: datetime,
    expected: ReadbackSubject | None = None,
    candidate_id: str | None = None,
) -> ReadbackSubject:
    """Short snapshot, never a claim or a renewal of the supplied deadline."""
    with factory() as db:
        subject = capture_readback_in_transaction(
            db, configuration, purchase, deadline=deadline, expected=expected, candidate_id=candidate_id
        )
        db.commit()
        return subject


def capture_readback_in_transaction(
    db: Session,
    configuration: Settings,
    purchase: Purchase,
    *,
    deadline: datetime,
    expected: ReadbackSubject | None = None,
    candidate_id: str | None = None,
) -> ReadbackSubject:
    row, customer, operations = _lock_purchase(db, configuration, purchase, expected.customer if expected else None)
    if expected is not None:
        if row.legal_acceptance_event_id != expected.legal_acceptance_event_id:
            raise BillingRefused("subscription_provenance_changed", 409)
        if deadline != expected.deadline:
            raise BillingRefused("subscription_reconciliation_stale", 409)
    now = as_utc(queries.database_now(db))
    if deadline <= now:
        raise BillingRefused("subscription_reconciliation_stale", 409)
    queries.scope(db, purchase.user_id, row.product_id)
    sub = purchases.linked_subscription(db, purchase.id)
    current = service._snapshot(db, row)
    if expected is not None:
        _verify_refresh(expected, current, candidate_id)
    agreement = next((op for op in operations if op.operation_kind == Kind.AGREEMENT), None)
    if agreement is None or not agreement.bound_external_object_id:
        raise BillingRefused("subscription_provenance_unproven", 409)
    common = dict(
        purchase=current,
        customer=customer,
        tenant_id=configuration.instance_tenant_id,
        region=configuration.instance_region,
        legal_acceptance_event_id=row.legal_acceptance_event_id,
        agreement_id=agreement.bound_external_object_id,
        agreement_key=agreement.request_correlation_key,
        captured_at=now,
        deadline=deadline,
    )
    if sub is not None:
        subject = BoundReadbackSubject(
            **common,
            provider_subscription_id=sub.external_subscription_id,
            subscription_id=sub.subscription_id,
            fence=sub.reconciliation_fencing_token,
            supporting_observation_id=sub.latest_observation_id,
        )
        _verify_bound(subject, sub, operations)
        if isinstance(expected, BoundReadbackSubject) and subject.subscription_id != expected.subscription_id:
            raise BillingRefused("subscription_provenance_changed", 409)
    else:
        operation = next(op for op in operations if op.operation_kind == Kind.SUBSCRIPTION)
        snapshot = next(op for op in current.operations if op.id == operation.create_operation_id)
        if (
            operation.operation_state not in {State.POSSIBLE_SEND, State.UNKNOWN, State.MANUAL_REVIEW}
            or operation.bound_external_object_id is not None
            or operation.unknown_since is None
            or operation.unknown_recovery_deadline_at is None
            or operation.recovery_hint_schema_version != FINANCIAL_HINT_SCHEMA
            or not isinstance(operation.recovery_hint_document, dict)
            or not isinstance(operation.recovery_hint_document.get("request"), dict)
        ):
            raise BillingRefused("purchase_history_unproven", 409)
        subject = OriginalCreateReadbackSubject(
            **common,
            operation=snapshot,
            saved_command=operation.recovery_hint_document["request"],
            original_send_at=as_utc(operation.unknown_since),
            original_deadline=as_utc(operation.unknown_recovery_deadline_at),
        )
    return subject


def _window_valid(subject: ReadbackSubject, negative: BoundSourceNegative, now: datetime) -> bool:
    return subject.captured_at <= negative.read_started_at <= negative.read_finished_at <= now < subject.deadline


def _authority_window(observation: BillingStateObservation) -> tuple[datetime | None, datetime]:
    """Legacy observed_at is an upper bound, never an invented source start."""
    document = observation.evidence_document
    if observation.evidence_schema_version in {NEGATIVE_SCHEMA, "subscription-reconciliation:v1"}:
        try:
            start = datetime.fromisoformat(document["read_started_at"])
            end = datetime.fromisoformat(document["read_finished_at"])
            if (
                start.utcoffset() is not None
                and end.utcoffset() is not None
                and start <= end == as_utc(observation.observed_at)
            ):
                return start, end
        except (KeyError, TypeError, ValueError):
            pass
        raise ReadbackRecheck()
    return None, as_utc(observation.observed_at)


def _check_order(
    db: Session, subject: BoundReadbackSubject, sub: ExternalSubscription, negative: BoundSourceNegative
) -> ReadbackApplyResult | None:
    latest = db.get(BillingStateObservation, sub.latest_observation_id) if sub.latest_observation_id else None
    if latest is None and sub.latest_observation_id is not None:
        raise ReadbackRecheck()
    if latest is not None:
        if (latest.subscription_id, latest.user_id, latest.product_id, latest.external_billing_account_id) != (
            sub.subscription_id,
            sub.user_id,
            sub.product_id,
            sub.external_billing_account_id,
        ):
            raise ReadbackRecheck()
        start, finish = _authority_window(latest)
        if start is not None and start > negative.read_finished_at:
            return ReadbackApplyResult.SUPERSEDED
        if finish > negative.read_started_at:
            raise ReadbackRecheck()
    if sub.reconciliation_fencing_token != subject.fence:
        raise ReadbackRecheck()
    return None


def _scope(db: Session, sub: ExternalSubscription) -> BillingProductAccessScope:
    scope = queries.scope(db, sub.user_id, sub.product_id)
    if scope is None:
        scope = BillingProductAccessScope(user_id=sub.user_id, product_id=sub.product_id, primary_subscription_id=None)
        db.add(scope)
        db.flush()
    return scope


def _write_negative(
    db: Session, subject: ReadbackSubject, sub: ExternalSubscription, negative: BoundSourceNegative
) -> None:
    scope = _scope(db, sub)
    document = asdict(negative)
    document.update(
        read_started_at=negative.read_started_at.isoformat(),
        read_finished_at=negative.read_finished_at.isoformat(),
        completeness_classification="negative_only",
        financial=Financial.BLOCKED,
        provenance={
            "purchase_intent_id": str(subject.purchase.id),
            "subscription_id": str(sub.subscription_id),
            "customer_id": str(subject.purchase.customer_id),
            "mapping_revision_id": str(subject.purchase.accepted.meaning.revision_id),
            "accepted_fingerprint": subject.purchase.accepted.offer.fingerprint,
            "legal_acceptance_event_id": str(subject.legal_acceptance_event_id),
            "legal_document_version_ids": [str(doc.document_version_id) for doc in subject.purchase.accepted.documents],
            "provider_origin": subject.purchase.accepted.provider_origin,
            "customer_operation_id": str(subject.customer.operation_id),
            "customer_fence": str(subject.customer.fence),
            "agreement_key": subject.agreement_key,
            "financial_bindings": [
                {"id": str(op.id), "kind": op.kind, "key": op.key, "bound_id": op.bound_id}
                for op in subject.purchase.operations
            ],
            "tenant_id": subject.tenant_id,
            "region": subject.region,
        },
        captured_supporting_observation_id=(
            str(subject.supporting_observation_id)
            if isinstance(subject, BoundReadbackSubject) and subject.supporting_observation_id
            else None
        ),
        original_create=(
            {
                "id": str(subject.operation.id),
                "kind": subject.operation.kind,
                "state": subject.operation.state,
                "key": subject.operation.key,
                "fence": str(subject.operation.fence),
                "candidate_id": subject.operation.candidate_id,
                "original_send_at": subject.original_send_at.isoformat(),
                "original_deadline": subject.original_deadline.isoformat(),
            }
            if isinstance(subject, OriginalCreateReadbackSubject)
            else None
        ),
        previous_supporting_observation_id=str(sub.latest_observation_id) if sub.latest_observation_id else None,
        expected_fence=subject.fence if isinstance(subject, BoundReadbackSubject) else None,
        previous_fence=sub.reconciliation_fencing_token,
        captured_at=subject.captured_at.isoformat(),
        deadline=subject.deadline.isoformat(),
    )
    observation = BillingStateObservation(
        observation_kind=BillingStateObservationKind.AUTHORITATIVE_SUBSCRIPTION_READ,
        external_billing_account_id=sub.external_billing_account_id,
        user_id=sub.user_id,
        product_id=sub.product_id,
        access_scope_id=scope.access_scope_id,
        subscription_id=sub.subscription_id,
        observed_at=negative.read_finished_at,
        evidence_schema_version=NEGATIVE_SCHEMA,
        evidence_document=document,
        completeness_classification="negative_only",
        result_classification="source_negative",
        resulting_access_revision=None,
    )
    db.add(observation)
    db.flush()
    apply_negative_facts(sub, negative.lifecycle, observation.observation_id)
    sub.reconciliation_fencing_token += 1
    sub.reconciliation_lease_owner = None
    sub.reconciliation_lease_expires_at = None
    enroll_subscription(db, sub, hint=True)
    preserve_trust_deadline(db, sub)


def _verify_negative(subject: ReadbackSubject, sub: ExternalSubscription, negative: BoundSourceNegative) -> None:
    if (negative.agreement_id, negative.provider_subscription_id) != (
        subject.agreement_id,
        sub.external_subscription_id,
    ):
        raise BillingRefused("subscription_provenance_changed", 409)
    required = {"customer", "agreement"} | ({"subscription"} if negative.basis == NegativeBasis.SUBSCRIPTION else set())
    if not required.issubset(negative.reads) or (
        negative.basis == NegativeBasis.AGREEMENT and negative.lifecycle != Lifecycle.ENDED
    ):
        raise BillingRefused("subscription_provenance_unproven", 409)


def _verify_work_claim(db: Session, sub: ExternalSubscription, claim: WorkClaim | None) -> None:
    if claim is not None:
        if claim.kind == "external_create_recovery":
            operations = purchases.operations(db, sub.purchase_intent_id, lock=True)
            if not any(str(op.create_operation_id) == claim.reference for op in operations):
                raise BillingRefused("billing_work_stale", 409)
            verify_operation_claim(db, claim, UUID(claim.reference))
            return
        if claim.kind != "subscription_reconciliation" or claim.reference != str(sub.subscription_id):
            raise BillingRefused("billing_work_stale", 409)
        verify_claim(db, claim)


def apply_readback_in_transaction(
    db: Session,
    configuration: Settings,
    finding: ScopedReadbackFinding,
    *,
    hint_only: bool = False,
    work_claim: WorkClaim | None = None,
) -> ReadbackApplyResult:
    """Caller owns commit. Recheck decisions have no acknowledged/written effect."""
    subject = finding.subject
    row, operations = _verify_subject(db, configuration, subject)
    queries.scope(db, subject.purchase.user_id, subject.purchase.accepted.selection.product_id)
    sub = purchases.linked_subscription(db, subject.purchase.id)
    if sub is None:
        if hint_only:
            raise BillingRefused("subscription_reconciliation_stale", 409)
        raise ReadbackRecheck()
    if not isinstance(subject, BoundReadbackSubject):
        # A concurrently created canonical row is foreign authority, never own binding.
        if not hint_only:
            raise ReadbackRecheck()
        candidate_id = (
            finding.negative.provider_subscription_id
            if finding.negative
            else (finding.candidate_id or subject.operation.candidate_id)
        )
        current_purchase = service._snapshot(db, row)
        _verify_refresh(subject, current_purchase, candidate_id)
        _verify_bound(replace(subject, purchase=current_purchase), sub, operations)
        if candidate_id is None or (sub.external_subscription_id, sub.external_agreement_id) != (
            candidate_id,
            subject.agreement_id,
        ):
            raise BillingRefused("subscription_provenance_changed", 409)
        _verify_work_claim(db, sub, work_claim)
        enroll_subscription(db, sub, hint=True)
        return ReadbackApplyResult.HINT_ONLY
    if sub.subscription_id != subject.subscription_id:
        raise BillingRefused("subscription_provenance_changed", 409)
    _verify_bound(subject, sub, operations)
    negative = finding.negative
    if negative is not None:
        _verify_negative(subject, sub, negative)
    now = as_utc(queries.database_now(db))
    if hint_only or negative is None or not _window_valid(subject, negative, now):
        _verify_work_claim(db, sub, work_claim)
        enroll_subscription(db, sub, hint=True)
        return ReadbackApplyResult.HINT_ONLY
    ordered = _check_order(db, subject, sub, negative)
    if ordered is not None:
        _verify_work_claim(db, sub, work_claim)
        return ordered
    _scope(db, sub)
    _verify_work_claim(db, sub, work_claim)
    _write_negative(db, subject, sub, negative)
    return ReadbackApplyResult.APPLIED_NEGATIVE


def apply_readback(
    factory: SessionFactory,
    configuration: Settings,
    finding: ScopedReadbackFinding,
    *,
    hint_only: bool = False,
    work_claim: WorkClaim | None = None,
) -> ReadbackApplyResult:
    with factory() as db:
        outcome = apply_readback_in_transaction(db, configuration, finding, hint_only=hint_only, work_claim=work_claim)
        db.commit()
        return outcome
