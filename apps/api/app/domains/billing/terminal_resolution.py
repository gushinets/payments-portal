"""Local, audited completion. Operator confirmations are evidence, never GET absence."""

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.domains.billing.operator_review import digest, operation_digest, case_digest
from app.domains.billing.paid_access import reduce_paid_access
from app.domains.billing.purchase_maintenance import guard_maintenance_write, lock_owned_purchase, maintenance_session
from app.domains.billing.reconciliation_contracts import (
    PREPARED_SUBSCRIPTION_SCHEMA,
    RECONCILIATION_READ_SCHEMAS,
    IdentityProof,
)
from app.domains.catalog.mapping_evidence import Digest
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import service
from app.domains.purchases.financial import RECOVERY_WINDOW
from app.domains.purchases.recovery_evidence import ProviderId, RetainedOriginalPointFacts, retained_points
from app.domains.purchases.contracts import (
    FINANCIAL_REVIEW_SCHEMA,
    FinancialOperation,
    FinancialReviewEvidence,
    PurchaseRefused,
)
from app.infrastructure.queries import (
    billing_operator as queries,
    billing_reconciliation,
    late_purchase_reviews,
    purchases,
)
from app.infrastructure.queries.billing_customers import open_customer_reviews
from app.models import (
    BillingWorkState,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as OperationState,
    ExternalSubscription,
    ManualReviewCase,
    PurchaseIntent,
    PurchaseIntentState as IntentState,
)

SCHEMA = "purchase-terminal-resolution:v1"
TERMINAL_REASON = "purchase_terminal_resolution"
SafeText = Annotated[str, Field(min_length=1, max_length=500, pattern=r"^[^\x00-\x1f\x7f]+$")]


class TerminalEvidenceKind(StrEnum):
    NOT_SENT = "not_sent"
    NO_EXTERNAL_EFFECT = "no_external_effect"
    EXTERNAL_TERMINAL = "external_terminal"


class OperationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operation_id: UUID
    outcome: TerminalEvidenceKind
    external_object_id: ProviderId | None = None

    @model_validator(mode="after")
    def object_required(self) -> "OperationEvidence":
        if (self.outcome == TerminalEvidenceKind.EXTERNAL_TERMINAL) != (self.external_object_id is not None):
            raise ValueError("Only external terminal evidence may and must name an object")
        return self


class TerminalEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["purchase-terminal-resolution:v1"] = SCHEMA
    senders_stopped_at: AwareDatetime | None = None
    confirmed_at: AwareDatetime | None = None
    operations: tuple[OperationEvidence, ...] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def distinct_operations(self) -> "TerminalEvidence":
        if len({item.operation_id for item in self.operations}) != len(self.operations):
            raise ValueError("duplicate operation evidence")
        return self


class TerminalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    user_id: UUID
    purchase_id: UUID
    expected_digest: Digest
    reason: SafeText
    reference: SafeText
    evidence: TerminalEvidence


class TerminalResult(BaseModel):
    review_case_id: UUID
    purchase_intent_id: UUID
    state: IntentState
    already_resolved: bool


class TerminalAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: TerminalRequest
    command_digest: str
    before_state: IntentState
    after_state: IntentState


def state_digest(db: Session, row: PurchaseIntent) -> str:
    """Compute the inspected digest again under business locks before a write."""
    customer = db.get(ExternalBillingCustomer, row.customer_id)
    hold = purchases.hold(db, row.user_id, row.product_id)
    sub = queries.subscription(db, row.purchase_intent_id)
    operations = purchases.operations(db, row.purchase_intent_id)
    return digest(
        {
            "purchase": str(row.purchase_intent_id),
            "state": row.state,
            "accepted": row.accepted_snapshot,
            "hold": str(hold.purchase_intent_id) if hold else None,
            "customer": [customer.provider_origin, customer.provider_customer_id, customer.binding_state],
            "operations": operation_digest(db, operations),
            "original_points": [
                value.model_dump(mode="json") for op in operations if (value := retained_points(db, op)) is not None
            ],
            "subscription": [str(sub.latest_observation_id), sub.reconciliation_fencing_token] if sub else None,
            "open_cases": sorted(
                case_digest(case)
                for case in queries.reviews(
                    db,
                    row.purchase_intent_id,
                    row.customer_id,
                    sub.subscription_id if sub else None,
                    open_only=True,
                    limit=None,
                )
            ),
        }
    )


def locally_proven_not_sent(
    db: Session,
    op: ExternalCreateOperation,
    snapshot: FinancialOperation,
    points: RetainedOriginalPointFacts | None,
) -> bool:
    if points is not None or snapshot.bound_id is not None or snapshot.candidate_id is not None:
        return False
    if op.operation_state in {OperationState.PENDING, OperationState.PROVEN_NOT_SENT}:
        return True
    if op.operation_state != OperationState.MANUAL_REVIEW:
        return False
    # An open financial review prevents another send while preserving the
    # earlier state and fence, including an explicit no-send transport result.
    for case in open_customer_reviews(db, op.create_operation_id):
        if case.evidence_schema_version != FINANCIAL_REVIEW_SCHEMA:
            continue
        try:
            prior = FinancialReviewEvidence.model_validate(case.evidence_document)
        except ValidationError:
            continue
        if (prior.purchase_intent_id, prior.create_operation_id) != (op.purchase_intent_id, op.create_operation_id):
            continue
        if prior.operation_state_at_conflict == OperationState.PROVEN_NOT_SENT and prior.send_fence_at_conflict:
            return True
        if prior.operation_state_at_conflict == OperationState.PENDING and (
            op.unknown_since is None and snapshot.deadline is None and op.recovery_hint_schema_version is None
        ):
            return True
    return False


def _verify_proof(
    db: Session,
    op: ExternalCreateOperation,
    item: OperationEvidence,
    evidence: TerminalEvidence,
    subscription: ExternalSubscription | None,
    now: datetime,
) -> None:
    if item.outcome == TerminalEvidenceKind.NO_EXTERNAL_EFFECT:
        raise PurchaseRefused("purchase_resolution_proof_incomplete", 409)

    snapshot = service._operation(db, op)
    points = retained_points(db, op)
    unsent = locally_proven_not_sent(db, op, snapshot, points)
    if item.outcome == TerminalEvidenceKind.NOT_SENT:
        if not unsent:
            raise PurchaseRefused("purchase_resolution_proof_incomplete", 409)
        return

    external_id = item.external_object_id
    assert external_id is not None
    linked_id = None
    if subscription is not None:
        linked_id = (
            subscription.external_agreement_id
            if op.operation_kind == Kind.AGREEMENT
            else subscription.external_subscription_id
        )
    known_ids = {value for value in (snapshot.bound_id, snapshot.candidate_id, linked_id) if value is not None}
    if points is not None:
        if points.conflict is not None:
            raise PurchaseRefused("purchase_resolution_proof_incomplete", 409)
        known_ids.add(points.primary.external_object_id)
    if unsent or (known_ids and known_ids != {external_id}):
        raise PurchaseRefused("purchase_resolution_proof_incomplete", 409)
    if queries.other_financial_binding(db, op, external_id) or late_purchase_reviews.other_audited_owner(
        db, op, external_id, reason=TERMINAL_REASON, schema=SCHEMA
    ):
        raise PurchaseRefused("purchase_resolution_proof_incomplete", 409)

    # The operator attests actual sender shutdown and a definitive provider
    # confirmation. A worker flag, expired recovery window or empty GET is insufficient.
    stopped, confirmed = evidence.senders_stopped_at, evidence.confirmed_at
    if (
        stopped is None
        or confirmed is None
        or not stopped <= confirmed <= now
        or (op.unknown_since is not None and stopped < as_utc(op.unknown_since))
        or (snapshot.deadline is not None and stopped < as_utc(snapshot.deadline) - RECOVERY_WINDOW)
    ):
        raise PurchaseRefused("purchase_resolution_confirmation_required", 409)
    if (
        (points is not None and points.primary.point_read_finished_at > confirmed)
        or (
            points is None
            and op.operation_kind == Kind.AGREEMENT
            and snapshot.bound_id is not None
            and not snapshot.agreement_closed
            and op.resolved_at is not None
            and as_utc(op.resolved_at) > confirmed
        )
        or (
            subscription is not None
            and queries.has_newer_live_financial_point(
                db,
                subscription.subscription_id,
                op.operation_kind,
                external_id,
                confirmed,
                schemas=RECONCILIATION_READ_SCHEMAS,
                preparation_schema=PREPARED_SUBSCRIPTION_SCHEMA,
                matched_identity=IdentityProof.MATCH.value,
            )
        )
    ):
        raise PurchaseRefused("purchase_resolution_confirmation_required", 409)


def resolve_purchase(
    factory: SessionFactory, configuration: Settings, request: TerminalRequest, principal: str
) -> TerminalResult:
    if not re.fullmatch(r"os-euid:[0-9]+", principal):
        raise PurchaseRefused("mapping_operator_identity_unavailable", 403)
    command = digest({"request": request.model_dump(mode="json"), "principal": principal})
    with maintenance_session(factory) as db:
        row, _ = lock_owned_purchase(
            db, configuration, request.user_id, request.purchase_id, stale_code="purchase_resolution_stale"
        )
        purchase_id = row.purchase_intent_id
        # Replay consults the original audit before checking a hold that may
        # now belong to a different purchase.
        case = queries.purchase_resolution_audit(db, purchase_id, reason=TERMINAL_REASON, schema=SCHEMA)
        if case is not None:
            audit = TerminalAudit.model_validate(case.resolution_document)
            if audit.command_digest == command:
                return TerminalResult(
                    review_case_id=case.review_case_id,
                    purchase_intent_id=purchase_id,
                    state=audit.after_state,
                    already_resolved=True,
                )
        supplied = {item.operation_id: item for item in request.evidence.operations}
        identities = purchases.operation_kinds(db, purchase_id)
        if set(identities.values()) != {Kind.AGREEMENT, Kind.SUBSCRIPTION} or set(supplied) != set(identities):
            raise PurchaseRefused("purchase_resolution_proof_incomplete", 409)
        objects = {
            (identities[op_id], item.external_object_id)
            for op_id, item in supplied.items()
            if item.external_object_id is not None
        }
        current = guard_maintenance_write(db, row, objects, stale_code="purchase_resolution_stale")
        operations, sub, hold = current.operations, current.subscription, current.hold
        if (
            identities != {op.create_operation_id: op.operation_kind for op in operations}
            or state_digest(db, row) != request.expected_digest
        ):
            raise PurchaseRefused("purchase_resolution_stale", 409)
        service._verify_original_consent(db, row, service.accepted(row))
        if row.state.resolved or hold is None or hold.purchase_intent_id != purchase_id:
            raise PurchaseRefused("purchase_scope_released", 409)
        sub_id = sub.subscription_id if sub else None
        now = current.now
        for op in operations:
            _verify_proof(db, op, supplied[op.create_operation_id], request.evidence, sub, now)

        before = row.state
        external = any(item.outcome == TerminalEvidenceKind.EXTERNAL_TERMINAL for item in supplied.values())
        row.state = IntentState.RESOLVED_EXTERNAL_TERMINAL if external else IntentState.RESOLVED_NO_EXTERNAL_EFFECT
        row.resolved_at = now
        row.state_updated_at = now
        db.delete(hold)
        for op in operations:
            op.send_fence = uuid4()
        if sub is not None:
            sub.reconciliation_fencing_token += 1
            sub.reconciliation_lease_owner = None
            sub.reconciliation_lease_expires_at = None

        audit = TerminalAudit(request=request, command_digest=command, before_state=before, after_state=row.state)
        case = ManualReviewCase(
            reason_code=TERMINAL_REASON,
            scope_kind="purchase_intent",
            scope_reference=str(purchase_id),
            evidence_schema_version=SCHEMA,
            evidence_document={"expected_digest": request.expected_digest},
            case_state="open",
        )
        db.add(case)
        cases = queries.reviews(db, purchase_id, row.customer_id, sub_id, open_only=True, lock=True, limit=None)
        for previous in [*cases, case]:
            if (previous.scope_kind, previous.scope_reference) in current.owned_scopes:
                previous.case_state = "resolved"
                previous.resolved_at = now
                previous.resolved_by_principal = principal
                previous.resolution_schema_version = SCHEMA
                previous.resolution_document = audit.model_dump(mode="json")

        db.flush()
        reduce_paid_access(db, row.user_id)
        scope = billing_reconciliation.scope(db, row.user_id, row.product_id)
        if sub_id is not None and scope is not None and scope.primary_subscription_id == sub_id:
            scope.primary_subscription_id = None
            scope.primary_retired_at = now
        for work in current.work:
            work.work_state = BillingWorkState.INVALID
            work.enqueue_generation += 1
            work.lease_owner = None
            work.lease_expires_at = None
            work.last_error_classification = "purchase_resolved"

        db.flush()
        result = TerminalResult(
            review_case_id=case.review_case_id, purchase_intent_id=purchase_id, state=row.state, already_resolved=False
        )
        db.commit()
        return result
