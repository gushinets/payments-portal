"""Local, audited completion. Operator confirmations are evidence, never GET absence."""

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.domains.billing.customer_scope import connection_account
from app.domains.billing.customers import lock_customer, lock_user
from app.domains.billing.operator_cases import reviewed_unsent_operation
from app.domains.billing.operator_contracts import (
    AuditedObjects,
    LATE_REASON,
    TERMINAL_AUDIT_REASONS,
    TERMINAL_REASON,
    TERMINAL_SCHEMA as SCHEMA,
    LateObjectDisposition,
    LateObjectEvidence,
    LateObjectResult,
    LateReviewRef,
    LateSubscriptionPoint,
    OperationEvidence,
    TerminalAudit,
    TerminalEvidence as TerminalEvidence,
    TerminalEvidenceKind,
    TerminalRequest,
    TerminalResult,
    retained_agreement_ids,
)
from app.domains.billing.operator_review import digest, terminal_state_digest
from app.domains.billing.paid_access import reduce_paid_access
from app.domains.billing.reconciliation_contracts import RECONCILIATION_READ_SCHEMAS
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import service
from app.domains.purchases.financial import RECOVERY_WINDOW
from app.domains.purchases.preparation import FinancialObjectConflict, verify_financial_owner
from app.domains.purchases.contracts import Purchase, PurchaseRefused, PurchaseInventoryIncomplete
from app.infrastructure.queries import billing_operator as queries, billing_reconciliation, purchases
from app.models import (
    ExternalCreateOperationState as OperationState,
    ExternalCreateOperationKind as Kind,
    ManualReviewCase,
    PurchaseIntentState as IntentState,
)

LATE_SCHEMA = "purchase-late-object:v1"


@dataclass(frozen=True)
class ReleasedPurchase:
    purchase: Purchase
    agreement_ids: frozenset[str]
    subscription_ids: frozenset[str]


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
            or terminal_state_digest(db, row) != request.expected_digest
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
        supplied = {item.operation_id: item for item in request.evidence.operations}
        if set(supplied) != {op.create_operation_id for op in operations}:
            raise PurchaseRefused("purchase_resolution_proof_incomplete", 409)
        original_proofs = _saved_proofs(original_cases) if late else frozenset()
        saved_proofs = original_proofs
        if late:
            saved_proofs |= _saved_proofs(
                queries.purchase_cases(db, purchase.id, reason=LATE_REASON, schema=LATE_SCHEMA, resolved_only=True)
            )
        external = False
        for op in operations:
            item = supplied[op.create_operation_id]
            if late and item.operation_id != late.operation_id:
                # This entry is context for the v1 command, not a second decision.
                if item not in saved_proofs:
                    raise PurchaseRefused("purchase_resolution_proof_incomplete", 409)
                continue
            snapshot = service._operation(db, op)
            previous = [proof for proof in saved_proofs if proof.operation_id == item.operation_id]
            retained = {proof.external_object_id for proof in previous if proof.external_object_id is not None}
            unsent = not (snapshot.bound_id or snapshot.candidate_id) and (
                op.operation_state in {OperationState.PENDING, OperationState.PROVEN_NOT_SENT}
                or (op.operation_state == OperationState.MANUAL_REVIEW and reviewed_unsent_operation(db, op, snapshot))
            )
            if late:
                _check_case_evidence(late, item, original_proofs, previous)
            if unsent and item.external_object_id is not None and item.external_object_id not in retained:
                raise PurchaseRefused("purchase_resolution_proof_incomplete", 409)
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
            if (
                late is None
                and op.operation_kind == Kind.SUBSCRIPTION
                and sub is not None
                and item.external_object_id == sub.external_subscription_id
                and queries.has_newer_live_subscription_read(
                    db, sub.subscription_id, evidence.confirmed_at, schemas=RECONCILIATION_READ_SCHEMAS
                )
            ):
                raise PurchaseRefused("purchase_resolution_confirmation_required", 409)
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


def _saved_proofs(cases: list[ManualReviewCase]) -> frozenset[OperationEvidence]:
    return frozenset(
        item
        for case in cases
        if case.resolution_schema_version == SCHEMA
        for item in TerminalAudit.model_validate(case.resolution_document).request.evidence.operations
    )


def _check_case_evidence(
    case: LateObjectEvidence,
    item: OperationEvidence,
    original: frozenset[OperationEvidence],
    previous: list[OperationEvidence],
) -> None:
    target = case.external_object_id
    known_ids = {proof.external_object_id for proof in previous}
    excluded = {identity for proof in previous for identity in proof.unrelated_object_ids}
    if target != item.external_object_id and target not in item.unrelated_object_ids:
        raise PurchaseRefused("purchase_resolution_proof_incomplete", 409)
    if set(item.unrelated_object_ids) - excluded - {target}:
        raise PurchaseRefused("purchase_resolution_proof_incomplete", 409)
    if item.external_object_id is not None and item.external_object_id not in known_ids:
        if item.external_object_id != target or any(
            proof.operation_id == item.operation_id and proof.outcome == TerminalEvidenceKind.NOT_SENT
            for proof in original
        ):
            raise PurchaseRefused("purchase_resolution_proof_incomplete", 409)


def _audited_objects(db: Session, purchase_id: UUID) -> dict[UUID, AuditedObjects]:
    original_cases = queries.purchase_cases(db, purchase_id, reason=TERMINAL_REASON, schema=SCHEMA, resolved_only=True)
    cases = queries.purchase_cases(db, purchase_id, reason=LATE_REASON, schema=LATE_SCHEMA, resolved_only=True)
    history: dict[UUID, AuditedObjects] = {}
    for proof in _saved_proofs([*original_cases, *cases]):
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
) -> LateObjectResult:
    """Record a late restriction, preserving the terminal decision and purchase history."""
    with factory() as db:
        lock_user(db, purchase.user_id)
        row = purchases.owned(db, purchase.user_id, purchase.id, lock=True)
        if row is None or not row.state.resolved or service.accepted(row) != purchase.accepted:
            raise PurchaseRefused("purchase_resolution_stale", 409)
        operations = purchases.operations(db, purchase.id, lock=True)
        if operation_id not in {op.create_operation_id for op in operations}:
            raise PurchaseRefused("purchase_history_unproven", 409)
        purchase_id = row.purchase_intent_id
        conflict = foreign = False
        expected_ids = frozenset()
        history = None
        if subscription_point is not None:
            binding = queries.financial_binding(db, purchase.account_id, Kind.SUBSCRIPTION, external_object_id)
            # A point on this agreement can still contradict another purchase's
            # confirmed subscription. Resolve audit ownership under the user lock.
            if binding is None:
                owners = queries.released_object_owners(
                    db,
                    row.customer_id,
                    (),
                    (external_object_id,),
                    audit_schema=SCHEMA,
                    audit_reasons=TERMINAL_AUDIT_REASONS,
                )
                if len(owners) > 1:
                    raise PurchaseInventoryIncomplete()
                if owners and owners[0].purchase_intent_id != purchase_id:
                    purchase_id = owners[0].purchase_intent_id
                    operations = purchases.operations(db, purchase_id, lock=True)
                    operation_id = next(
                        op.create_operation_id for op in operations if op.operation_kind == Kind.SUBSCRIPTION
                    )
            foreign = binding is not None and binding.create_operation_id != operation_id
            if foreign:
                owner_operations = purchases.operations(db, binding.purchase_intent_id)
                owner_agreement = next(
                    op.bound_external_object_id for op in owner_operations if op.operation_kind == Kind.AGREEMENT
                )
                if owner_agreement == subscription_point.agreement_id:
                    return LateObjectResult(LateObjectDisposition.CLEAR)  # The point agrees with its permanent owner.
            agreement = next(op for op in operations if op.operation_kind == Kind.AGREEMENT)
            if agreement.bound_external_object_id is None:
                history = _audited_objects(db, purchase_id)
            expected_ids = retained_agreement_ids(
                agreement.bound_external_object_id, history.get(agreement.create_operation_id) if history else None
            )
            if not expected_ids:
                raise PurchaseRefused("purchase_history_unproven", 409)
            conflict = foreign or subscription_point.agreement_id not in expected_ids
            if purchase_id != purchase.id and not conflict:
                return LateObjectResult(LateObjectDisposition.CLEAR)  # The point agrees with its attested owner.
            if not conflict and not subscription_point.original_live_proven:
                return LateObjectResult(LateObjectDisposition.NEEDS_ORIGINAL_PROOF)
        evidence = LateObjectEvidence(
            purchase_intent_id=purchase_id,
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
            purchase_id,
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
            if any(
                proof.operation_id == operation_id and external_object_id in proof.unrelated_object_ids
                for proof in audit.request.evidence.operations
            ):
                disproved = True
            elif confirmed is not None and confirmed >= read_finished_at:
                return LateObjectResult(LateObjectDisposition.CLEAR)  # An older read of the same relationship.
        if disproved:
            if history is None:
                history = _audited_objects(db, purchase_id)
            # Positive attestation of an original object supersedes disproof.
            if external_object_id not in history.get(operation_id, AuditedObjects()).confirmed:
                return LateObjectResult(LateObjectDisposition.UNRELATED)
        for case in cases:
            if case.case_state == "open":
                previous = LateObjectEvidence.model_validate(case.evidence_document)
                if not evidence.matches_relationship(previous, legacy_open_agreement_ids=expected_ids):
                    continue
                review = LateReviewRef(purchase_intent_id=purchase_id, review_case_id=case.review_case_id)
                if read_finished_at > previous.latest_observation_at:
                    case.evidence_document = evidence.model_copy(
                        update={"read_started_at": min(previous.read_started_at, read_started_at)}
                    ).model_dump(mode="json")
                    db.commit()
                return LateObjectResult(disposition, review)
        review = LateReviewRef(purchase_intent_id=purchase_id, review_case_id=uuid4())
        db.add(
            ManualReviewCase(
                review_case_id=review.review_case_id,
                reason_code=LATE_REASON,
                scope_kind="purchase_intent",
                scope_reference=str(purchase_id),
                evidence_schema_version=LATE_SCHEMA,
                evidence_document=evidence.model_dump(mode="json"),
                case_state="open",
            )
        )
        db.commit()
        return LateObjectResult(disposition, review)
