"""Exact financial point evidence retained with the original recovery operation."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.customer_reviews import customer_admission_reviews
from app.domains.billing.customers import lock_customer
from app.domains.billing.work import verify_operation_claim
from app.domains.billing.work_contracts import WorkClaim
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import service
from app.domains.purchases.contracts import Purchase, PurchaseRefused
from app.infrastructure.persistence.billing_work import ensure_recovery
from app.infrastructure.queries import purchases
from app.infrastructure.queries.billing_customers import customer_operation, recovery_work
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


def retain_original_point(
    factory: SessionFactory,
    purchase: Purchase,
    customer: CustomerOpen,
    point: OriginalPointFact,
    *,
    recovering_id: UUID,
    work_claim: WorkClaim | None = None,
) -> bool:
    """Keep a bounded conflict witness even if the caller cannot bind the candidate."""
    from app.domains.billing.late_purchase_reviews import require_bindable
    from app.domains.purchases.inventory import same_purchase

    with factory() as db:
        row = service._locked(db, purchase)
        operations = purchases.operations(db, purchase.id, lock=True)
        if not same_purchase(service._snapshot(db, row), purchase):
            return True  # A changed attempt is handled by the existing writer.
        require_current_customer(db, row, purchase, customer)
        op = next(item for item in operations if item.create_operation_id == point.operation_id)
        if work_claim is not None:
            verify_operation_claim(db, work_claim, recovering_id)
        if op.bound_external_object_id is None:
            require_bindable(db, op, point.external_object_id)
        elif op.bound_external_object_id != point.external_object_id:
            return False
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
        elif saved.conflict.external_object_id == point.external_object_id and (
            point.point_read_finished_at > saved.conflict.point_read_finished_at
        ):
            current = RetainedOriginalPointFacts(primary=saved.primary, conflict=point)
        else:
            current = saved
        if current != saved:
            work.payload_document = {**work.payload_document, _POINT_FACTS: current.model_dump(mode="json")}
            db.commit()
        return current.conflict is None


def settle_point_conflict(work: BillingWorkItem, op: ExternalCreateOperation, external_id: str) -> None:
    saved = _read_points(work, op)
    if saved is None or saved.conflict is None:
        return
    payload = {**work.payload_document}
    point = next((item for item in (saved.primary, saved.conflict) if item.external_object_id == external_id), None)
    if point is None:
        payload.pop(_POINT_FACTS)
    else:
        payload[_POINT_FACTS] = RetainedOriginalPointFacts(primary=point).model_dump(mode="json")
    work.payload_document = payload
