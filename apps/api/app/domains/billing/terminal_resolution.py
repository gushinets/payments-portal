"""Local, audited completion. Operator confirmations are evidence, never GET absence."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.domains.billing.customer_scope import connection_account
from app.domains.billing.customers import lock_customer, lock_user
from app.domains.billing.operator_contracts import (
    AuditedObjects,
    LATE_REASON,
    TERMINAL_AUDIT_REASONS,
    TERMINAL_REASON,
    TERMINAL_SCHEMA as SCHEMA,
    LateObjectDisposition,
    LateObjectEvidence,
    LateSubscriptionPoint,
    ProviderId,
    retained_agreement_ids,
)
from app.domains.billing.operator_review import digest, operation_digest, case_digest
from app.domains.billing.paid_access import reduce_paid_access
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import service
from app.domains.purchases.financial import RECOVERY_WINDOW
from app.domains.purchases.preparation import FinancialObjectConflict, verify_financial_owner
from app.domains.purchases.contracts import Purchase, PurchaseRefused, PurchaseInventoryIncomplete
from app.infrastructure.queries import billing_operator as queries, billing_reconciliation, purchases
from app.models import (
    ExternalBillingCustomer,
    ExternalCreateOperationState as OperationState,
    ExternalCreateOperationKind as Kind,
    ManualReviewCase,
    PurchaseIntent,
    PurchaseIntentState as IntentState,
)

LATE_SCHEMA = "purchase-late-object:v1"
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
    unrelated_object_ids: tuple[ProviderId, ...] = Field(default=(), exclude_if=lambda ids: not ids)

    @model_validator(mode="after")
    def object_required(self) -> "OperationEvidence":
        if (self.outcome == TerminalEvidenceKind.EXTERNAL_TERMINAL) != (self.external_object_id is not None):
            raise ValueError("terminal objects require an ID; absence/no-send cannot name an object")
        if (
            len(set(self.unrelated_object_ids)) != len(self.unrelated_object_ids)
            or self.external_object_id in self.unrelated_object_ids
            or (self.unrelated_object_ids and self.outcome == TerminalEvidenceKind.NOT_SENT)
        ):
            raise ValueError("unrelated IDs must identify distinct candidates from a possible send")
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


@dataclass(frozen=True)
class ReleasedPurchase:
    purchase: Purchase
    agreement_ids: frozenset[str]
    subscription_ids: frozenset[str]


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
        late_case = None
        if request.case_id is not None:
            late_case = queries.review(db, request.case_id, lock=True)
            if late_case is None or (
                late_case.scope_kind,
                late_case.scope_reference,
                late_case.reason_code,
                late_case.evidence_schema_version,
            ) != ("purchase_intent", str(purchase.id), LATE_REASON, LATE_SCHEMA):
                raise PurchaseRefused("billing_review_stale", 409)
        original_cases = queries.purchase_cases(
            db, purchase.id, reason=TERMINAL_REASON, schema=SCHEMA, resolved_only=True
        )
        # A successful release removes the hold and rotates fences. Replay must
        # inspect the saved command before consulting either current value.
        for case in [late_case] if late_case is not None else original_cases:
            if case.resolution_schema_version == SCHEMA:
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
        late = None
        if late_case is not None:
            if not row.state.resolved or late_case.case_state != "open":
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
        history = _audited_objects(db, purchase.id, original_cases) if late is not None else {}
        external = False
        for op in operations:
            item = proof[op.create_operation_id]
            snapshot = service._operation(db, op)
            retained = history.get(op.create_operation_id, AuditedObjects()).confirmed
            unsent = op.operation_state in {OperationState.PENDING, OperationState.PROVEN_NOT_SENT} and not (
                snapshot.bound_id or snapshot.candidate_id
            )
            if item.outcome == TerminalEvidenceKind.NOT_SENT:
                if not unsent or retained or (late and late.operation_id == op.create_operation_id):
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
            if late and evidence.confirmed_at < late.latest_observation_at:
                raise PurchaseRefused("purchase_resolution_confirmation_required", 409)
            if item.external_object_id is not None:
                try:
                    verify_financial_owner(db, op, item.external_object_id)
                except FinancialObjectConflict:
                    raise PurchaseRefused("purchase_resolution_proof_incomplete", 409) from None
            target = late.external_object_id if late and late.operation_id == op.create_operation_id else None
            known = {value for value in (snapshot.bound_id, snapshot.candidate_id, target) if value}
            unrelated = set(item.unrelated_object_ids)
            if unrelated - known or unrelated & (retained | {snapshot.bound_id}):
                raise PurchaseRefused("purchase_resolution_proof_incomplete", 409)
            required = known - unrelated
            if target is not None and item.external_object_id == target:
                # This exact case can attest a new object while retaining a
                # previous positive attestation for the original object.
                required -= retained - {target}
            if required and required != {item.external_object_id}:
                raise PurchaseRefused("purchase_resolution_proof_incomplete", 409)
            if not required and retained and item.external_object_id not in retained:
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
        cases = (
            [case]
            if late_case is not None
            else [
                *queries.reviews(
                    db,
                    purchase.id,
                    purchase.customer_id,
                    sub.subscription_id if sub else None,
                    open_only=True,
                    lock=True,
                    limit=None,
                ),
                case,
            ]
        )
        for previous in cases:
            if previous.case_state == "open" and previous.scope_reference in owned_scopes:
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


def _audited_objects(
    db: Session,
    purchase_id: UUID,
    original_cases: list[ManualReviewCase] | None = None,
) -> dict[UUID, AuditedObjects]:
    if original_cases is None:
        original_cases = queries.purchase_cases(
            db, purchase_id, reason=TERMINAL_REASON, schema=SCHEMA, resolved_only=True
        )
    cases = queries.purchase_cases(db, purchase_id, reason=LATE_REASON, schema=LATE_SCHEMA, resolved_only=True)
    history: dict[UUID, AuditedObjects] = {}
    for case in [*original_cases, *cases]:
        if case.resolution_schema_version != SCHEMA:
            continue
        audit = TerminalAudit.model_validate(case.resolution_document)
        for proof in audit.request.evidence.operations:
            objects = history.setdefault(proof.operation_id, AuditedObjects())
            if proof.external_object_id is not None:
                objects.confirmed.add(proof.external_object_id)
            objects.unrelated.update(proof.unrelated_object_ids)
    return history


def released_operation_objects(factory: SessionFactory, purchase_id: UUID) -> dict[UUID, AuditedObjects]:
    with factory() as db:
        return _audited_objects(db, purchase_id)


def released_object_owners(
    factory: SessionFactory, customer_id: UUID, agreement_ids: tuple[str, ...], subscription_ids: tuple[str, ...]
) -> tuple[ReleasedPurchase, ...]:
    if not agreement_ids and not subscription_ids:
        return ()
    with factory() as db:
        rows = queries.released_object_owners(
            db,
            customer_id,
            agreement_ids,
            subscription_ids,
            audit_schema=SCHEMA,
            audit_reasons=TERMINAL_AUDIT_REASONS,
        )
        if len(rows) > 100:
            raise PurchaseInventoryIncomplete()
        owners = []
        for row in rows:
            purchase = service._snapshot(db, row)
            agreement = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
            subscription = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
            history = _audited_objects(db, purchase.id)
            terminal_subscriptions = frozenset(history.get(subscription.id, AuditedObjects()).confirmed)
            owners.append(
                ReleasedPurchase(
                    purchase=purchase,
                    agreement_ids=frozenset(history.get(agreement.id, AuditedObjects()).confirmed)
                    | ({agreement.bound_id} if agreement.bound_id else set()),
                    subscription_ids=terminal_subscriptions
                    | ({subscription.bound_id} if subscription.bound_id else set()),
                )
            )
        return tuple(owners)


def record_late_object(
    factory: SessionFactory,
    purchase: Purchase,
    operation_id: UUID,
    external_object_id: str,
    read_started_at: datetime,
    *,
    read_finished_at: datetime,
    subscription_point: LateSubscriptionPoint | None = None,
) -> LateObjectDisposition:
    """Record a late restriction, preserving the terminal decision and purchase history."""
    with factory() as db:
        lock_user(db, purchase.user_id)
        row = purchases.owned(db, purchase.user_id, purchase.id, lock=True)
        if row is None or not row.state.resolved or service.accepted(row) != purchase.accepted:
            raise PurchaseRefused("purchase_resolution_stale", 409)
        operations = purchases.operations(db, purchase.id, lock=True)
        if operation_id not in {op.create_operation_id for op in operations}:
            raise PurchaseRefused("purchase_history_unproven", 409)
        conflict = foreign = False
        expected_ids = frozenset()
        history = None
        if subscription_point is not None:
            binding = queries.financial_binding(db, purchase.account_id, Kind.SUBSCRIPTION, external_object_id)
            foreign = binding is not None and binding.create_operation_id != operation_id
            if foreign:
                owner_operations = purchases.operations(db, binding.purchase_intent_id)
                owner_agreement = next(
                    op.bound_external_object_id for op in owner_operations if op.operation_kind == Kind.AGREEMENT
                )
                if owner_agreement == subscription_point.agreement_id:
                    return LateObjectDisposition.CLEAR  # The point agrees with its permanent owner.
            agreement = next(op for op in operations if op.operation_kind == Kind.AGREEMENT)
            if agreement.bound_external_object_id is None:
                history = _audited_objects(db, purchase.id)
            expected_ids = retained_agreement_ids(
                agreement.bound_external_object_id, history.get(agreement.create_operation_id) if history else None
            )
            if not expected_ids:
                raise PurchaseRefused("purchase_history_unproven", 409)
            conflict = foreign or subscription_point.agreement_id not in expected_ids
            if not conflict and not subscription_point.original_live_proven:
                return LateObjectDisposition.NEEDS_ORIGINAL_PROOF
        evidence = LateObjectEvidence(
            purchase_intent_id=purchase.id,
            operation_id=operation_id,
            external_object_id=external_object_id,
            read_started_at=read_started_at,
            latest_read_started_at=read_started_at,
            latest_read_finished_at=read_finished_at,
            observed_agreement_id=subscription_point.agreement_id if subscription_point else None,
            observed_tariff_id=subscription_point.tariff_id if subscription_point else None,
            relationship_conflict=conflict if subscription_point else None,
            bound_to_another_operation=foreign,
        )
        disposition = LateObjectDisposition.RELATIONSHIP_CONFLICT if conflict else LateObjectDisposition.OPEN_ORIGINAL
        cases = queries.purchase_cases(
            db,
            purchase.id,
            reason=LATE_REASON,
            schema=LATE_SCHEMA,
            object_identity=(operation_id, external_object_id),
        )
        disproved = False
        for case in cases:
            if case.case_state != "resolved":
                continue
            previous = LateObjectEvidence.model_validate(case.evidence_document)
            if not evidence.matches_relationship(previous):
                continue
            audit = TerminalAudit.model_validate(case.resolution_document)
            confirmed = audit.request.evidence.confirmed_at
            if confirmed is not None and confirmed >= read_finished_at:
                return LateObjectDisposition.CLEAR  # Only a delayed read of this same relationship is covered.
            if any(
                proof.operation_id == operation_id and external_object_id in proof.unrelated_object_ids
                for proof in audit.request.evidence.operations
            ):
                disproved = True
        if disproved:
            if history is None:
                history = _audited_objects(db, purchase.id)
            # Positive attestation of an original object supersedes disproof.
            if external_object_id not in history.get(operation_id, AuditedObjects()).confirmed:
                return LateObjectDisposition.CLEAR
        for case in cases:
            if case.case_state == "open":
                previous = LateObjectEvidence.model_validate(case.evidence_document)
                if not evidence.matches_relationship(previous, legacy_open_agreement_ids=expected_ids):
                    continue
                if read_finished_at > previous.latest_observation_at:
                    case.evidence_document = evidence.model_copy(
                        update={"read_started_at": min(previous.read_started_at, read_started_at)}
                    ).model_dump(mode="json")
                    db.commit()
                return disposition
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
        return disposition
