"""Local, audited completion. Operator confirmations are evidence, never GET absence."""

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.domains.billing.customer_scope import connection_account
from app.domains.billing.customers import lock_customer, lock_user
from app.domains.billing.operator_review import digest, operation_digest, case_digest
from app.domains.billing.paid_access import reduce_paid_access
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import service
from app.domains.purchases.financial import RECOVERY_WINDOW
from app.domains.purchases.contracts import Purchase, PurchaseRefused, PurchaseInventoryIncomplete
from app.infrastructure.queries import billing_operator as queries, billing_reconciliation, purchases
from app.models import (
    ExternalBillingCustomer,
    ExternalCreateOperationState as OperationState,
    ManualReviewCase,
    PurchaseIntent,
    PurchaseIntentState as IntentState,
)

SCHEMA = "purchase-terminal-resolution:v1"
TERMINAL_REASON = "purchase_terminal_resolution"
LATE_SCHEMA = "purchase-late-object:v1"
LATE_REASON = "purchase_late_external_object"
SafeText = Annotated[str, Field(min_length=1, max_length=500, pattern=r"^[^\x00-\x1f\x7f]+$")]
ProviderId = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$")]


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
            raise ValueError("terminal objects require an ID; absence/no-send cannot name an object")
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
    expected_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    reason: SafeText
    reference: SafeText
    evidence: TerminalEvidence
    case_id: UUID | None = None


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


class LateObjectEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    purchase_intent_id: UUID
    operation_id: UUID
    external_object_id: ProviderId
    read_started_at: AwareDatetime
    latest_read_started_at: AwareDatetime

    @model_validator(mode="after")
    def ordered_reads(self) -> "LateObjectEvidence":
        if self.latest_read_started_at < self.read_started_at:
            raise ValueError("reversed late-object reads")
        return self


def state_digest(db: Session, row: PurchaseIntent) -> str:
    """Read-only diagnostic; the writer repeats this under business locks."""
    customer = db.get(ExternalBillingCustomer, row.customer_id)
    hold = purchases.hold(db, row.user_id, row.product_id)
    sub = queries.subscription(db, row.purchase_intent_id)
    return digest(
        {
            "purchase": str(row.purchase_intent_id),
            "state": row.state,
            "accepted": row.accepted_snapshot,
            "hold": str(hold.purchase_intent_id) if hold else None,
            "customer": [customer.provider_origin, customer.provider_customer_id, customer.binding_state],
            "operations": operation_digest(db, purchases.operations(db, row.purchase_intent_id)),
            "subscription": [str(sub.latest_observation_id), sub.reconciliation_fencing_token] if sub else None,
            "open_cases": sorted(
                case_digest(case)
                for case in queries.reviews(
                    db, row.purchase_intent_id, row.customer_id, sub.subscription_id if sub else None, open_only=True
                )
            ),
        }
    )


def resolve_purchase(
    factory: SessionFactory, configuration: Settings, request: TerminalRequest, principal: str
) -> TerminalResult:
    if not re.fullmatch(r"os-euid:[0-9]+", principal):
        raise PurchaseRefused("mapping_operator_identity_unavailable", 403)
    purchase = service.inspect_purchase(factory, configuration, request.user_id, request.purchase_id)
    command = digest({"request": request.model_dump(mode="json"), "principal": principal})
    with factory() as db:
        lock_user(db, purchase.user_id)
        customer = lock_customer(db, purchase.customer_id)
        row = purchases.owned(db, purchase.user_id, purchase.id, lock=True)
        operations = purchases.operations(db, purchase.id, lock=True)
        sub = purchases.linked_subscription(db, purchase.id)
        cases = queries.reviews(db, purchase.id, purchase.customer_id, sub.subscription_id if sub else None, lock=True)
        if len(cases) > 100:
            raise PurchaseRefused("billing_review_unrelated_cases", 409)
        # A successful release removes the hold and rotates fences. Replay must
        # inspect the saved command before consulting either current value.
        for case in cases:
            audit_owner = (
                case.review_case_id == request.case_id if request.case_id else case.reason_code == TERMINAL_REASON
            )
            if audit_owner and case.resolution_schema_version == SCHEMA:
                audit = TerminalAudit.model_validate(case.resolution_document)
                if audit.command_digest == command:
                    return TerminalResult(
                        review_case_id=case.review_case_id,
                        purchase_intent_id=purchase.id,
                        state=audit.after_state,
                        already_resolved=True,
                    )
        if (
            customer.external_billing_account_id != connection_account(db, configuration)
            or customer.provider_origin not in {None, configuration.lbx_provider_origin}
            or purchase.account_id != customer.external_billing_account_id
            or state_digest(db, row) != request.expected_digest
        ):
            raise PurchaseRefused("purchase_resolution_stale", 409)
        service._verify_original_consent(db, row, purchase.accepted)
        hold = purchases.hold(db, row.user_id, row.product_id)
        late_case = next((case for case in cases if case.review_case_id == request.case_id), None)
        late = None
        if request.case_id is not None:
            if (
                not row.state.resolved
                or late_case is None
                or late_case.case_state != "open"
                or (late_case.reason_code != LATE_REASON or late_case.evidence_schema_version != LATE_SCHEMA)
            ):
                raise PurchaseRefused("billing_review_stale", 409)
            late = LateObjectEvidence.model_validate(late_case.evidence_document)
            if late.purchase_intent_id != purchase.id:
                raise PurchaseRefused("billing_review_unrelated_cases", 409)
        elif row.state.resolved or hold is None or hold.purchase_intent_id != purchase.id:
            raise PurchaseRefused("purchase_scope_released", 409)
        now = as_utc(billing_reconciliation.database_now(db))
        proof = {item.operation_id: item for item in request.evidence.operations}
        if set(proof) != {op.create_operation_id for op in operations}:
            raise PurchaseRefused("purchase_resolution_proof_incomplete", 409)
        external = False
        for op in operations:
            item = proof[op.create_operation_id]
            snapshot = service._operation(db, op)
            unsent = op.operation_state in {OperationState.PENDING, OperationState.PROVEN_NOT_SENT} and not (
                snapshot.bound_id or snapshot.candidate_id
            )
            if item.outcome == TerminalEvidenceKind.NOT_SENT:
                if not unsent or (late and late.operation_id == op.create_operation_id):
                    raise PurchaseRefused("purchase_resolution_proof_incomplete", 409)
                continue
            evidence = request.evidence
            if not (
                evidence.senders_stopped_at
                and evidence.confirmed_at
                and evidence.senders_stopped_at <= evidence.confirmed_at <= now
            ):
                raise PurchaseRefused("purchase_resolution_confirmation_required", 409)
            if op.unknown_since and evidence.senders_stopped_at < as_utc(op.unknown_since):
                raise PurchaseRefused("purchase_resolution_confirmation_required", 409)
            if snapshot.deadline and evidence.senders_stopped_at < snapshot.deadline - RECOVERY_WINDOW:
                raise PurchaseRefused("purchase_resolution_confirmation_required", 409)
            if late and evidence.confirmed_at < late.latest_read_started_at:
                raise PurchaseRefused("purchase_resolution_confirmation_required", 409)
            known_ids = {value for value in (snapshot.bound_id, snapshot.candidate_id) if value}
            if late and late.operation_id == op.create_operation_id:
                known_ids = {late.external_object_id}
            if known_ids and (
                item.outcome != TerminalEvidenceKind.EXTERNAL_TERMINAL or known_ids != {item.external_object_id}
            ):
                raise PurchaseRefused("purchase_resolution_proof_incomplete", 409)
            external |= item.outcome == TerminalEvidenceKind.EXTERNAL_TERMINAL
        before = row.state
        if late_case is None:
            row.state = IntentState.RESOLVED_EXTERNAL_TERMINAL if external else IntentState.RESOLVED_NO_EXTERNAL_EFFECT
            row.resolved_at = now
            row.state_updated_at = now
            db.delete(hold)
            for op in operations:
                op.send_fence = uuid4()
            if sub:
                sub.reconciliation_fencing_token += 1
                sub.reconciliation_lease_owner = None
                sub.reconciliation_lease_expires_at = None
        audit = TerminalAudit(request=request, command_digest=command, before_state=before, after_state=row.state)
        case = late_case or ManualReviewCase(
            reason_code=TERMINAL_REASON,
            scope_kind="purchase_intent",
            scope_reference=str(purchase.id),
            evidence_schema_version=SCHEMA,
            evidence_document={"expected_digest": request.expected_digest},
            case_state="open",
        )
        db.add(case)
        owned_scopes = {str(purchase.id), *(str(op.create_operation_id) for op in operations)}
        if sub:
            owned_scopes.add(str(sub.subscription_id))
        for previous in [*cases, case]:
            if (
                previous.case_state == "open"
                and previous.scope_reference in owned_scopes
                and (late_case is None or previous is late_case)
            ):
                previous.case_state = "resolved"
                previous.resolved_at = now
                previous.resolved_by_principal = principal
                previous.resolution_schema_version = SCHEMA
                previous.resolution_document = audit.model_dump(mode="json")
        # Flush restrictions before the existing paid writer reads dependencies.
        db.flush()
        reduce_paid_access(db, row.user_id)
        if late_case is None:
            scope = billing_reconciliation.scope(db, row.user_id, row.product_id)
            if sub is not None and scope is not None and scope.primary_subscription_id == sub.subscription_id:
                scope.primary_subscription_id = None
                scope.primary_retired_at = now
            for work in queries.work(db, tuple(owned_scopes)):
                work.work_state = "invalid"
                work.enqueue_generation += 1
                work.lease_owner = None
                work.lease_expires_at = None
                work.last_error_classification = "purchase_resolved"
        db.flush()
        result = TerminalResult(
            review_case_id=case.review_case_id, purchase_intent_id=purchase.id, state=row.state, already_resolved=False
        )
        db.commit()
        return result


def released_object_owners(
    factory: SessionFactory, customer_id: UUID, agreement_ids: tuple[str, ...], subscription_ids: tuple[str, ...]
) -> tuple[Purchase, ...]:
    with factory() as db:
        rows = queries.released_object_owners(db, customer_id, agreement_ids, subscription_ids)
        if len(rows) > 100:
            raise PurchaseInventoryIncomplete()
        return tuple(service._snapshot(db, row) for row in rows)


def record_late_object(
    factory: SessionFactory,
    purchase: Purchase,
    operation_id: UUID,
    external_object_id: str,
    read_started_at: datetime,
) -> None:
    """Caller proved the original agreement/customer by authenticated point GET.

    This only records a restriction. It never binds, resumes, or changes another
    purchase's primary source. The terminal decision and accepted history stay intact.
    """
    evidence = LateObjectEvidence(
        purchase_intent_id=purchase.id,
        operation_id=operation_id,
        external_object_id=external_object_id,
        read_started_at=read_started_at,
        latest_read_started_at=read_started_at,
    )
    with factory() as db:
        lock_user(db, purchase.user_id)
        row = purchases.owned(db, purchase.user_id, purchase.id, lock=True)
        if row is None or not row.state.resolved or service.accepted(row) != purchase.accepted:
            raise PurchaseRefused("purchase_resolution_stale", 409)
        operations = purchases.operations(db, purchase.id, lock=True)
        if operation_id not in {op.create_operation_id for op in operations}:
            raise PurchaseRefused("purchase_history_unproven", 409)
        for case in queries.reviews(db, purchase.id, purchase.customer_id, None):
            if case.reason_code == LATE_REASON and case.evidence_schema_version == LATE_SCHEMA:
                previous = LateObjectEvidence.model_validate(case.evidence_document)
                if (previous.operation_id, previous.external_object_id) == (operation_id, external_object_id):
                    if case.case_state == "open":
                        if read_started_at > previous.latest_read_started_at:
                            case.evidence_document = previous.model_copy(
                                update={"latest_read_started_at": read_started_at}
                            ).model_dump(mode="json")
                            db.commit()
                        return
                    audit = TerminalAudit.model_validate(case.resolution_document)
                    confirmed = audit.request.evidence.confirmed_at
                    if confirmed is not None and confirmed >= read_started_at:
                        return  # A delayed old GET cannot reopen an already resolved finding.
        db.add(
            ManualReviewCase(
                reason_code=LATE_REASON,
                scope_kind="purchase_intent",
                scope_reference=str(purchase.id),
                evidence_schema_version=LATE_SCHEMA,
                evidence_document=evidence.model_dump(mode="json"),
                case_state="open",
            )
        )
        db.commit()
