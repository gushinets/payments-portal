"""Exact review relationships accepted by the existing audited operator actions."""

from datetime import datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.operator_contracts import (
    AUDITED_SUBSCRIPTION_SCHEMA,
    TERMINAL_AUDIT_REASONS,
    TERMINAL_SCHEMA,
    AuditedSubscriptionCandidate,
    AuditedSubscriptionEvidence,
    AuditedSubscriptionObservation,
    ResolutionRequest,
    TerminalAudit,
)
from app.domains.billing.reconciliation_contracts import PREPARED_AGREEMENT_SCHEMA, AgreementClosure
from app.domains.catalog.commercial_offer import canonical_document, commercial_digest
from app.domains.identity.services.auth import as_utc
from app.domains.purchases.contracts import (
    FINANCIAL_REVIEW_SCHEMA,
    FinancialOperation,
    FinancialReviewEvidence,
    Purchase,
    PurchaseInventoryIncomplete,
    PurchaseRefused,
)
from app.infrastructure.queries import billing_operator as queries
from app.infrastructure.queries.billing_customers import open_customer_reviews
from app.models import (
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ExternalSubscription,
    ManualReviewCase,
    BillingStateObservation,
    PurchaseIntentState,
)

RESTORABLE = {
    "subscription_identity_conflict",
    "subscription_commercial_mismatch",
    "financial_binding_conflict",
    "accepted_terms_changed_after_preparation",
    "customer_inventory_conflict",
}
BINDABLE = {"financial_binding_conflict", "accepted_terms_changed_after_preparation", "customer_inventory_conflict"}


def digest(value: object) -> str:
    return commercial_digest(canonical_document(value))


def case_digest(case: ManualReviewCase) -> str:
    return digest(
        {
            "id": str(case.review_case_id),
            "reason": case.reason_code,
            "scope": [case.scope_kind, case.scope_reference],
            "schema": case.evidence_schema_version,
            "evidence": case.evidence_document,
        }
    )


def audited_subscription_candidates(
    db: Session, customer_id: UUID, account_id: str
) -> frozenset[AuditedSubscriptionCandidate]:
    disproved: set[tuple[UUID, AuditedSubscriptionCandidate]] = set()
    originals: set[tuple[UUID, str]] = set()
    for operation_id, case in queries.released_subscription_audits(
        db, customer_id, account_id, audit_schema=TERMINAL_SCHEMA, audit_reasons=TERMINAL_AUDIT_REASONS
    ):
        try:
            audit = TerminalAudit.model_validate(case.resolution_document)
        except ValidationError as error:
            raise PurchaseInventoryIncomplete() from error
        proof = next(item for item in audit.request.evidence.operations if item.operation_id == operation_id)
        if proof.external_object_id is not None:
            originals.add((operation_id, proof.external_object_id))
        disproved.update(
            (operation_id, AuditedSubscriptionCandidate(identity, case.review_case_id))
            for identity in proof.unrelated_object_ids
        )
    return frozenset(
        candidate for operation_id, candidate in disproved if (operation_id, candidate.external_id) not in originals
    )


def audited_subscription_reads(
    db: Session,
    customer: CustomerOpen,
    purchase: Purchase,
    candidates: frozenset[AuditedSubscriptionCandidate],
) -> dict[str, AuditedSubscriptionObservation]:
    if not candidates or customer.provider_id is None:
        return {}
    rows = queries.latest_audited_subscription_reads(
        db,
        customer.customer_id,
        purchase.account_id,
        purchase.user_id,
        customer.provider_id,
        {candidate.external_id for candidate in candidates},
        schema=AUDITED_SUBSCRIPTION_SCHEMA,
    )
    try:
        observations = [
            AuditedSubscriptionObservation(
                row.observation_id, row.observed_at, AuditedSubscriptionEvidence.model_validate(row.evidence_document)
            )
            for row in rows
        ]
    except ValidationError as error:
        raise PurchaseInventoryIncomplete() from error
    return {observation.evidence.external_id: observation for observation in observations}


def newer_open_agreement(db: Session, op: ExternalCreateOperation, agreement_id: str, confirmed_at: datetime) -> bool:
    observation = queries.prepared_agreement_observation(
        db, op.purchase_intent_id, agreement_id, schema=PREPARED_AGREEMENT_SCHEMA
    )
    if observation is None:
        # Older binders only persisted closed-agreement reads.
        return op.resolved_at is not None and as_utc(op.resolved_at) > confirmed_at
    observed_at, closure = observation
    return as_utc(observed_at) > confirmed_at and closure == AgreementClosure.OPEN


def possible_send_case(case: ManualReviewCase) -> bool:
    evidence = case.evidence_document
    if not isinstance(evidence, dict) or evidence.get("operation_state_at_conflict") not in {
        State.POSSIBLE_SEND.value,
        State.UNKNOWN.value,
    }:
        return False
    try:
        return str(UUID(evidence["send_fence_at_conflict"])) == evidence["send_fence_at_conflict"]
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def original_possible_send(case: ManualReviewCase, related: list[ManualReviewCase], purchase: Purchase) -> bool:
    evidence = case.evidence_document
    if (
        case.evidence_schema_version != FINANCIAL_REVIEW_SCHEMA
        or not isinstance(evidence, dict)
        or evidence.get("purchase_intent_id") != str(purchase.id)
        or evidence.get("create_operation_id") != case.scope_reference
    ):
        return False
    if possible_send_case(case):
        return True
    # Deadline escalation rotates the send fence and moves the operation to
    # MANUAL_REVIEW. Its preserved earlier evidence still proves possible-send;
    # no new send can be authorized while this review is open. Database-created
    # timestamps reflect transaction starts, not the causal order of these
    # locked transitions; the saved prior states establish that order.
    return evidence.get("operation_state_at_conflict") == State.MANUAL_REVIEW.value and any(
        possible_send_case(previous) for previous in related
    )


def reviewed_unsent_operation(db: Session, operation: ExternalCreateOperation, snapshot: FinancialOperation) -> bool:
    # An open financial review prevents a further send. Its evidence preserves
    # the state before the review rotated the operation's fence.
    for case in open_customer_reviews(db, operation.create_operation_id):
        if case.evidence_schema_version != FINANCIAL_REVIEW_SCHEMA:
            continue
        try:
            origin = FinancialReviewEvidence.model_validate(case.evidence_document)
        except ValidationError:
            continue
        if (origin.purchase_intent_id, origin.create_operation_id) != (
            operation.purchase_intent_id,
            operation.create_operation_id,
        ):
            continue
        if origin.operation_state_at_conflict == State.PROVEN_NOT_SENT and origin.send_fence_at_conflict is not None:
            return True
        if origin.operation_state_at_conflict == State.PENDING and (
            operation.unknown_since is None
            and snapshot.deadline is None
            and operation.recovery_hint_schema_version is None
        ):
            return True
    return False


def inventory_case(case: ManualReviewCase, purchase: Purchase, operations: list[ExternalCreateOperation]) -> bool:
    evidence = case.evidence_document
    target = next((op for op in operations if op.operation_kind == Kind.SUBSCRIPTION), None)
    return bool(
        target is not None
        and case.reason_code == "customer_inventory_conflict"
        and (case.scope_kind, case.scope_reference) == ("create_operation", str(target.create_operation_id))
        and case.evidence_schema_version == FINANCIAL_REVIEW_SCHEMA
        and isinstance(evidence, dict)
        and evidence.get("purchase_intent_id") == str(purchase.id)
        and evidence.get("create_operation_id") == str(target.create_operation_id)
        and evidence.get("operation_state_at_conflict")
        in {State.BOUND.value, State.POSSIBLE_SEND.value, State.UNKNOWN.value, State.MANUAL_REVIEW.value}
    )


def canonical_case(
    db: Session, case: ManualReviewCase, purchase: Purchase, subscription: ExternalSubscription | None
) -> bool:
    if (
        subscription is None
        or case.reason_code not in {"subscription_identity_conflict", "subscription_commercial_mismatch"}
        or (case.scope_kind, case.scope_reference) != ("subscription", str(subscription.subscription_id))
        or case.evidence_schema_version not in ("subscription-reconciliation:v1", "subscription-reconciliation:v2")
        or not isinstance(case.evidence_document, dict)
    ):
        return False
    try:
        identity = UUID(case.evidence_document["observation_id"])
    except (KeyError, ValueError, TypeError):
        return False
    observation = db.get(BillingStateObservation, identity)
    return bool(
        observation is not None
        and observation.subscription_id == subscription.subscription_id
        and observation.evidence_document.get("provenance", {}).get("purchase_intent_id") == str(purchase.id)
    )


def validate_case(
    db: Session,
    request: ResolutionRequest,
    purchase: Purchase,
    subscription: ExternalSubscription | None,
    operations: list[ExternalCreateOperation],
) -> tuple[ManualReviewCase, list[ManualReviewCase]]:
    case = queries.review(db, request.case_id, lock=True)
    cases = queries.reviews(
        db,
        purchase.id,
        purchase.customer_id,
        subscription.subscription_id if subscription else None,
        open_only=True,
        lock=True,
    )
    if case is None or len(cases) > 100 or not any(item.review_case_id == request.case_id for item in cases):
        raise PurchaseRefused("billing_review_unrelated_cases", 409)
    if case.case_state != "open" or case_digest(case) != request.expected_case_digest:
        raise PurchaseRefused("billing_review_stale", 409)
    supported = (
        {"primary_selection_required"}
        if request.resolution == "select-primary"
        else RESTORABLE
        if request.resolution == "restore-original"
        else BINDABLE
    )
    if case.reason_code not in supported:
        raise PurchaseRefused("billing_review_resolution_unsupported", 409)
    if request.resolution == "bind-original" and (case.scope_kind, case.scope_reference) != (
        "create_operation",
        str(request.operation_id),
    ):
        raise PurchaseRefused("billing_review_stale", 409)
    if case.reason_code == "customer_inventory_conflict" and not inventory_case(case, purchase, operations):
        raise PurchaseRefused("billing_review_resolution_unsupported", 409)
    related = [item for item in cases if item.review_case_id != case.review_case_id]
    if request.resolution == "select-primary":
        if subscription is None or (case.scope_kind, case.scope_reference) != (
            "subscription",
            str(subscription.subscription_id),
        ):
            raise PurchaseRefused("billing_review_stale", 409)
        if (
            related
            or purchase.state != PurchaseIntentState.LINKED
            or any(op.operation_state != State.BOUND for op in operations)
        ):
            raise PurchaseRefused("billing_review_unrelated_cases", 409)
        return case, []
    target = next((op for op in operations if op.create_operation_id == request.operation_id), None)
    for previous in related:
        if inventory_case(previous, purchase, operations) or (
            request.resolution == "restore-original" and canonical_case(db, previous, purchase, subscription)
        ):
            continue
        evidence = previous.evidence_document
        if (
            request.resolution != "bind-original"
            or target is None
            or (previous.scope_kind, previous.scope_reference) != (case.scope_kind, case.scope_reference)
            or previous.reason_code != "external_create_outcome_unknown:" + target.operation_kind.value
            or previous.evidence_schema_version != FINANCIAL_REVIEW_SCHEMA
            or not isinstance(evidence, dict)
            or evidence.get("purchase_intent_id") != str(purchase.id)
            or evidence.get("create_operation_id") != str(target.create_operation_id)
            or not possible_send_case(previous)
        ):
            raise PurchaseRefused("billing_review_unrelated_cases", 409)
    return case, related
