"""Exact financial point evidence retained with the original recovery operation."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from app.domains.billing.contracts import BillingRefused, CustomerOpen
from app.domains.billing.operator_contracts import RESOLUTION_SCHEMA, OriginalOperationProof
from app.domains.billing.customer_reviews import customer_admission_reviews
from app.domains.billing.customers import lock_customer
from app.domains.billing.work import verify_claim, verify_operation_claim
from app.domains.billing.work_contracts import WorkClaim
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import service
from app.domains.purchases.financial_reviews import review_identity_conflict
from app.domains.purchases.contracts import (
    FINANCIAL_HINT_SCHEMA,
    FINANCIAL_REVIEW_SCHEMA,
    FinancialOperation,
    FinancialRequestDocument,
    FinancialReviewEvidence,
    Purchase,
    PurchaseRefused,
)
from app.infrastructure.persistence.billing_work import ensure_recovery
from app.infrastructure.queries import purchases
from app.infrastructure.queries.billing_customers import customer_operation, open_customer_reviews, recovery_work
from app.infrastructure.queries.billing_operator import has_audited_original_binding
from app.models import (
    BillingWorkItem,
    BillingWorkState,
    ExternalBillingCustomerBindingState as Binding,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    PurchaseIntent,
)

ProviderId = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$")]
_POINT_FACTS = "original_point_facts"


class OriginalPointFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: UUID
    operation_kind: Literal[Kind.AGREEMENT, Kind.SUBSCRIPTION]
    external_object_id: ProviderId
    fact: Literal["open", "live"]
    point_read_finished_at: AwareDatetime

    @model_validator(mode="after")
    def matching_fact(self) -> "OriginalPointFact":
        if self.fact != ("open" if self.operation_kind == Kind.AGREEMENT else "live"):
            raise ValueError("point fact does not match operation kind")
        return self


class RetainedOriginalPointFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["original-operation-point-facts:v1"] = "original-operation-point-facts:v1"
    primary: OriginalPointFact
    conflict: OriginalPointFact | None = None

    @model_validator(mode="after")
    def same_operation(self) -> "RetainedOriginalPointFacts":
        if self.conflict is not None and (
            (self.conflict.operation_id, self.conflict.operation_kind)
            != (self.primary.operation_id, self.primary.operation_kind)
            or self.conflict.external_object_id == self.primary.external_object_id
        ):
            raise ValueError("invalid original point conflict")
        return self


def retained_points(db: Session, operation: ExternalCreateOperation) -> RetainedOriginalPointFacts | None:
    return _read_points(recovery_work(db, operation.create_operation_id), operation)


def _read_points(work: BillingWorkItem | None, operation: ExternalCreateOperation) -> RetainedOriginalPointFacts | None:
    if work is None or _POINT_FACTS not in work.payload_document:
        return None
    try:
        points = RetainedOriginalPointFacts.model_validate(work.payload_document[_POINT_FACTS])
    except ValidationError:
        raise PurchaseRefused("purchase_history_unproven", 409) from None
    if (points.primary.operation_id, points.primary.operation_kind) != (
        operation.create_operation_id,
        operation.operation_kind,
    ):
        raise PurchaseRefused("purchase_history_unproven", 409)
    return points


def require_current_customer(db: Session, row: PurchaseIntent, purchase: Purchase, expected: CustomerOpen) -> str:
    customer = lock_customer(db, row.customer_id)
    customer_create = customer_operation(db, customer.customer_id)
    if (
        customer.customer_id != expected.customer_id
        or customer.binding_state != Binding.BOUND
        or customer.provider_customer_id != expected.provider_id
        or customer.billing_customer_key != expected.outer_key
        or customer.provider_origin != purchase.accepted.provider_origin
        or customer_create is None
        or customer_create.create_operation_id != expected.operation_id
        or customer_create.request_correlation_key != expected.outer_key
        or customer_create.send_fence != expected.fence
        or customer_create.operation_state != State.BOUND
        or customer_create.bound_external_object_id != expected.provider_id
    ):
        raise PurchaseRefused("billing_identity_unproven", 409)
    customer_admission_reviews(db, customer, customer_create)
    return customer.external_billing_account_id


def saved_request(operation: ExternalCreateOperation, purchase: Purchase) -> FinancialRequestDocument:
    hint = operation.recovery_hint_document
    if (
        operation.unknown_since is None
        or operation.unknown_recovery_deadline_at is None
        or operation.send_fence is None
        or operation.recovery_hint_schema_version != FINANCIAL_HINT_SCHEMA
        or not isinstance(hint, dict)
        or hint.get("purchase_intent_id") != str(purchase.id)
        or hint.get("accepted_fingerprint") != purchase.accepted.offer.fingerprint
        or not isinstance(hint.get("request"), dict)
    ):
        raise PurchaseRefused("purchase_history_unproven", 409)
    return hint["request"]


def same_send(
    db: Session, op: ExternalCreateOperation, expected: FinancialOperation, current: FinancialOperation
) -> bool:
    # A definitive no-send permits reusing the operation UUID and request. A new
    # financial claim starts a new active window; a recovery lease does not.
    if current.key != expected.key or current.deadline != expected.deadline:
        return False
    if current.state in {State.PROVEN_NOT_SENT, State.PENDING}:
        return False
    if current.fence == expected.fence:
        return True
    if current.state == State.BOUND and expected.bound_id is None:
        return not has_audited_original_binding(db, expected.id, schema=RESOLUTION_SCHEMA)
    if current.state == State.MANUAL_REVIEW and expected.fence is not None:
        for case in open_customer_reviews(db, expected.id):
            if case.evidence_schema_version == FINANCIAL_REVIEW_SCHEMA:
                try:
                    prior = FinancialReviewEvidence.model_validate(case.evidence_document)
                except ValidationError:
                    raise PurchaseRefused("purchase_history_unproven", 409) from None
                if (prior.create_operation_id, prior.purchase_intent_id, prior.send_fence_at_conflict) == (
                    expected.id,
                    op.purchase_intent_id,
                    expected.fence,
                ):
                    return True
    return False


def retain_original_point(
    factory: SessionFactory,
    purchase: Purchase,
    customer: CustomerOpen,
    point: OriginalPointFact,
    *,
    request_document: FinancialRequestDocument | None,
    recovering_id: UUID,
    work_claim: WorkClaim | None = None,
) -> bool:
    """Keep a bounded conflict witness even if the caller cannot bind the candidate."""
    from app.domains.billing.background_recovery import INVENTORY
    from app.domains.billing.late_purchase_reviews import require_bindable

    with factory() as db:
        row = service._locked(db, purchase)
        operations = purchases.operations(db, purchase.id, lock=True)
        account = require_current_customer(db, row, purchase, customer)
        op = next(item for item in operations if item.create_operation_id == point.operation_id)
        if work_claim is not None:
            if work_claim.kind == INVENTORY:
                if (
                    work_claim.reference != str(customer.customer_id)
                    or verify_claim(db, work_claim).coalescing_key != f"{account}:{customer.customer_id}"
                ):
                    raise BillingRefused("billing_work_stale", 409)
            else:
                verify_operation_claim(db, work_claim, recovering_id)
        expected = next(item for item in purchase.operations if item.id == point.operation_id)
        locked = service._operation(db, op)
        if (
            row.customer_id != purchase.customer_id
            or row.external_billing_account_id != account
            or purchase.account_id != account
            or op.external_billing_account_id != account
            or service.accepted(row) != purchase.accepted
            or expected.kind != point.operation_kind
            or locked.kind != expected.kind
            or not same_send(db, op, expected, locked)
        ):
            raise PurchaseRefused("purchase_pending", 409)
        if request_document is not None:
            if saved_request(op, purchase) != request_document:
                raise PurchaseRefused("purchase_history_unproven", 409)
        elif not (locked.bound_id == expected.bound_id == point.external_object_id and locked.fence == expected.fence):
            raise PurchaseRefused("purchase_history_unproven", 409)
        if locked.bound_id != point.external_object_id:
            require_bindable(db, op, point.external_object_id)
        work = recovery_work(db, op.create_operation_id)
        if work is None:
            if op.unknown_recovery_deadline_at is None:
                raise PurchaseRefused("purchase_history_unproven", 409)
            ensure_recovery(db, str(op.create_operation_id), as_utc(op.unknown_recovery_deadline_at))
            work = recovery_work(db, op.create_operation_id)
            assert work is not None
            if op.bound_external_object_id is not None:
                work.work_state = BillingWorkState.DONE

        saved = _read_points(work, op)
        if saved is None:
            current = RetainedOriginalPointFacts(primary=point)
        elif saved.primary.external_object_id == point.external_object_id:
            current = (
                RetainedOriginalPointFacts(primary=point, conflict=saved.conflict)
                if (point.point_read_finished_at > saved.primary.point_read_finished_at)
                else saved
            )
        elif saved.conflict is None:
            current = RetainedOriginalPointFacts(primary=saved.primary, conflict=point)
        elif point.point_read_finished_at > saved.conflict.point_read_finished_at:
            current = RetainedOriginalPointFacts(primary=saved.primary, conflict=point)
        else:
            current = saved
        if locked.bound_id not in {None, point.external_object_id}:
            # A competing automatic bind committed first. Keep its binding, but withdraw trust.
            review_identity_conflict(db, row, op)
        if current != saved:
            work.payload_document = {**work.payload_document, _POINT_FACTS: current.model_dump(mode="json")}
        db.commit()
        return (
            current.conflict is None
            and op.bound_external_object_id in {None, point.external_object_id}
            and locked.candidate_id in {None, point.external_object_id}
        )


def binding_identity_matches(
    db: Session,
    op: ExternalCreateOperation,
    expected: FinancialOperation,
    external_id: str,
    proof: OriginalOperationProof,
    *,
    operator: bool,
) -> bool:
    # Retention and first binding are separate transactions around source I/O.
    # Re-read both positive and conflicting identity evidence inside this writer.
    snapshot = service._operation(db, op)
    if snapshot.bound_id not in {None, external_id} or snapshot.candidate_id not in {None, external_id}:
        return False
    points = retained_points(db, op)
    if points is not None:
        others = [
            item
            for item in (points.primary, points.conflict)
            if item is not None and item.external_object_id != external_id
        ]
        if others and not operator:
            return False
        if others:
            clock = proof.point_read_at
            if clock is None or any(item.point_read_finished_at >= clock for item in others):
                raise PurchaseRefused("billing_review_stale", 409)
            # The bounded second slot can replace a third ID. A later update to
            # that slot may have displaced a dissenting point after this GET.
            witness = points.conflict
            if witness and witness.external_object_id == external_id and witness.point_read_finished_at > clock:
                raise PurchaseRefused("billing_review_stale", 409)
    if snapshot.state != expected.state or snapshot.deadline != expected.deadline:
        raise PurchaseRefused("billing_review_stale" if operator else "purchase_pending", 409)
    return True


def settle_point_conflict(work: BillingWorkItem, op: ExternalCreateOperation, external_id: str) -> None:
    saved = _read_points(work, op)
    if saved is None or (saved.conflict is None and saved.primary.external_object_id == external_id):
        return
    payload = {**work.payload_document}
    point = next(
        (
            item
            for item in (saved.primary, saved.conflict)
            if item is not None and item.external_object_id == external_id
        ),
        None,
    )
    if point is None:
        payload.pop(_POINT_FACTS)
    else:
        payload[_POINT_FACTS] = RetainedOriginalPointFacts(primary=point).model_dump(mode="json")
    work.payload_document = payload
