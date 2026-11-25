"""Keep the restriction and its audit on the existing exact-object review case."""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.customers import lock_customer, lock_user
from app.domains.billing.operator_review import case_digest
from app.domains.billing.purchase_maintenance import (
    guard_maintenance_write,
    lock_financial_object,
    lock_owned_purchase,
    maintenance_session,
)
from app.domains.billing.reconciliation_contracts import (
    PREPARED_SUBSCRIPTION_SCHEMA,
    RECONCILIATION_READ_SCHEMAS,
    IdentityProof,
)
from app.domains.billing.terminal_resolution import (
    SafeText,
    SCHEMA,
    TERMINAL_REASON,
    TerminalAudit,
    TerminalResult,
)
from app.domains.catalog.mapping_evidence import Digest
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases import service
from app.domains.purchases.contracts import Purchase, PurchaseInventoryIncomplete, PurchaseRefused
from app.domains.purchases.recovery_evidence import ProviderId
from app.infrastructure.queries import (
    billing_operator,
    late_purchase_reviews as queries,
    purchases,
)
from app.infrastructure.queries.billing_customers import customer_operation
from app.models import ExternalCreateOperation, ExternalCreateOperationKind as Kind, ManualReviewCase, PurchaseIntent

REASON = "purchase_late_external_object"
CASE_SCHEMA = "purchase-late-object:v1"
CLOSURE_SCHEMA = "purchase-late-object-closure:v1"


class LateObjectEvidence(BaseModel):
    """A timely live/open read of the exact provider object."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal[Kind.AGREEMENT, Kind.SUBSCRIPTION]
    external_object_id: ProviderId
    fact: Literal["open", "live"] = Field(
        default_factory=lambda data: "open" if data["kind"] == Kind.AGREEMENT else "live"
    )
    competing_tariff_id: int | None = Field(default=None, gt=0)
    read_finished_at: AwareDatetime
    agreement_id: ProviderId | None = None

    @model_validator(mode="after")
    def matching_fact(self) -> "LateObjectEvidence":
        if self.fact != ("open" if self.kind == Kind.AGREEMENT else "live"):
            raise ValueError("point fact does not match object kind")
        return self


class ClosureKind(StrEnum):
    EXTERNAL_TERMINAL = "external_terminal"


class ClosureEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    outcome: ClosureKind
    external_object_id: ProviderId
    confirmed_at: AwareDatetime


class ClosureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    user_id: UUID
    purchase_id: UUID
    case_id: UUID
    expected_digest: Digest
    reason: SafeText
    reference: SafeText
    evidence: ClosureEvidence


class ClosureAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: ClosureRequest


@dataclass(frozen=True)
class ReleasedOriginal:
    purchase: Purchase
    agreement_ids: frozenset[str]
    subscription_ids: frozenset[str]


def _original(
    db: Session, row: PurchaseIntent, *, include_late_cases: bool = False, case_subscription_ids: set[str] | None = None
) -> ReleasedOriginal:
    purchase = service._snapshot(db, row)
    case = billing_operator.purchase_resolution_audit(db, purchase.id, reason=TERMINAL_REASON, schema=SCHEMA)
    proofs = (
        {
            item.operation_id: item.external_object_id
            for item in TerminalAudit.model_validate(case.resolution_document).request.evidence.operations
        }
        if case is not None
        else {}
    )
    identities = {
        op.kind: {value for value in (op.bound_id, proofs.get(op.id)) if value is not None}
        for op in purchase.operations
    }
    if include_late_cases or case_subscription_ids:
        points = queries.purchase_object_ids(
            db, purchase.id, reason=REASON, schema=CASE_SCHEMA, subscription_ids=case_subscription_ids
        )
        if len(points) > 100:
            raise PurchaseInventoryIncomplete()
        for kind, external_id in points:
            identities[Kind(kind)].add(external_id)
    return ReleasedOriginal(purchase, frozenset(identities[Kind.AGREEMENT]), frozenset(identities[Kind.SUBSCRIPTION]))


def released_original(factory: SessionFactory, purchase: Purchase) -> ReleasedOriginal | None:
    with factory() as db:
        row = purchases.owned(db, purchase.user_id, purchase.id)
        if row is None or not row.state.resolved:
            return None
        return (
            _original(db, row, include_late_cases=True)
            if billing_operator.purchase_resolution_audit(db, purchase.id, reason=TERMINAL_REASON, schema=SCHEMA)
            is not None
            else None
        )


def released_owners(
    factory: SessionFactory,
    customer_id: UUID,
    agreement_ids: set[str],
    subscription_ids: set[str],
    *,
    agreement_number: str | None = None,
) -> tuple[ReleasedOriginal, ...]:
    with factory() as db:
        rows = queries.released_owners(
            db,
            customer_id,
            agreement_ids,
            subscription_ids,
            agreement_number,
            audit_reason=TERMINAL_REASON,
            audit_schema=SCHEMA,
            case_reason=REASON,
            case_schema=CASE_SCHEMA,
        )
        if len(rows) > 100:
            raise PurchaseInventoryIncomplete()
        return tuple(_original(db, row, case_subscription_ids=subscription_ids) for row in rows)


def record_late_object(
    factory: SessionFactory, original: ReleasedOriginal, expected: CustomerOpen, evidence: LateObjectEvidence
) -> None:
    purchase = original.purchase
    with factory() as db:
        lock_user(db, purchase.user_id)
        customer = lock_customer(db, purchase.customer_id)
        operation = customer_operation(db, customer.customer_id)
        row = purchases.owned(db, purchase.user_id, purchase.id, lock=True)
        if (
            row is None
            or not row.state.resolved
            or row.customer_id != customer.customer_id
            or service.accepted(row) != purchase.accepted
            or customer.provider_origin != purchase.accepted.provider_origin
            or (customer.customer_id, customer.provider_customer_id, customer.billing_customer_key)
            != (expected.customer_id, expected.provider_id, expected.outer_key)
            or operation is None
            or (operation.create_operation_id, operation.send_fence) != (expected.operation_id, expected.fence)
        ):
            raise PurchaseRefused("purchase_resolution_stale", 409)
        lock_financial_object(db, purchase.account_id, evidence.kind, evidence.external_object_id)
        cases = queries.object_cases(
            db,
            purchase.account_id,
            evidence.kind,
            evidence.external_object_id,
            reason=REASON,
            schema=CASE_SCHEMA,
        )
        if cases:
            if len(cases) != 1 or cases[0].scope_reference != str(purchase.id):
                raise PurchaseInventoryIncomplete()
            [active] = cases
            previous = LateObjectEvidence.model_validate(active.evidence_document)
            if evidence.read_finished_at > previous.read_finished_at:
                active.evidence_document = evidence.model_dump(mode="json")
                db.commit()
            return
        db.add(
            ManualReviewCase(
                reason_code=REASON,
                scope_kind="purchase_intent",
                scope_reference=str(purchase.id),
                evidence_schema_version=CASE_SCHEMA,
                evidence_document=evidence.model_dump(mode="json"),
                case_state="open",
            )
        )
        db.commit()


def blocking_cases(db: Session, purchase: Purchase) -> list[ManualReviewCase]:
    return queries.product_cases(
        db,
        purchase.customer_id,
        purchase.accepted.selection.product_id,
        purchase.accepted.selection.tariff_id,
        reason=REASON,
        schema=CASE_SCHEMA,
    )


def require_clear(db: Session, purchase: Purchase) -> None:
    if blocking_cases(db, purchase):
        raise PurchaseRefused("purchase_existing_subscription_review", 409)


def require_bindable(db: Session, operation: ExternalCreateOperation, external_id: str) -> None:
    account_id, kind = operation.external_billing_account_id, operation.operation_kind
    lock_financial_object(db, account_id, kind, external_id)
    if queries.object_cases(db, account_id, kind, external_id, reason=REASON, schema=CASE_SCHEMA):
        raise PurchaseRefused("purchase_existing_subscription_review", 409)
    if queries.has_terminal_closure(
        db,
        account_id,
        kind,
        external_id,
        reason=REASON,
        schema=CASE_SCHEMA,
        closure_schema=CLOSURE_SCHEMA,
        closure_outcome=ClosureKind.EXTERNAL_TERMINAL.value,
    ) or queries.other_audited_owner(db, operation, external_id, reason=TERMINAL_REASON, schema=SCHEMA):
        raise PurchaseRefused("purchase_review_required", 409)


def close_case(
    factory: SessionFactory, configuration: Settings, request: ClosureRequest, principal: str
) -> TerminalResult:
    if not re.fullmatch(r"os-euid:[0-9]+", principal):
        raise PurchaseRefused("mapping_operator_identity_unavailable", 403)
    with maintenance_session(factory) as db:
        row, customer = lock_owned_purchase(
            db, configuration, request.user_id, request.purchase_id, stale_code="billing_review_stale"
        )
        purchase_id = row.purchase_intent_id
        case = billing_operator.review(db, request.case_id)
        if (
            not row.state.resolved
            or customer.provider_origin != configuration.lbx_provider_origin
            or case is None
            or (case.scope_kind, case.scope_reference, case.reason_code, case.evidence_schema_version)
            != ("purchase_intent", str(purchase_id), REASON, CASE_SCHEMA)
        ):
            raise PurchaseRefused("billing_review_stale", 409)
        if case.case_state != "open":
            if (
                case.resolution_schema_version == CLOSURE_SCHEMA
                and case.resolved_by_principal == principal
                and ClosureAudit.model_validate(case.resolution_document).request == request
            ):
                return TerminalResult(
                    review_case_id=case.review_case_id,
                    purchase_intent_id=purchase_id,
                    state=row.state,
                    already_resolved=True,
                )
            raise PurchaseRefused("billing_review_stale", 409)
        evidence = LateObjectEvidence.model_validate(case.evidence_document)
        if (
            request.expected_digest != case_digest(case)
            or request.evidence.external_object_id != evidence.external_object_id
        ):
            raise PurchaseRefused("billing_review_stale", 409)
        current = guard_maintenance_write(
            db, row, {(evidence.kind, evidence.external_object_id)}, stale_code="billing_review_stale"
        )
        case = billing_operator.review(db, request.case_id, lock=True)
        if case is None or case.case_state != "open" or request.expected_digest != case_digest(case):
            raise PurchaseRefused("billing_review_stale", 409)
        service._verify_original_consent(db, row, service.accepted(row))
        now = current.now
        confirmed = request.evidence.confirmed_at
        if not evidence.read_finished_at <= confirmed <= now or billing_operator.has_newer_live_financial_point(
            db,
            billing_operator.customer_subscription_ids(customer.customer_id, customer.external_billing_account_id),
            evidence.kind,
            evidence.external_object_id,
            confirmed,
            schemas=RECONCILIATION_READ_SCHEMAS,
            preparation_schema=PREPARED_SUBSCRIPTION_SCHEMA,
            matched_identity=IdentityProof.MATCH.value,
        ):
            raise PurchaseRefused("purchase_resolution_confirmation_required", 409)
        case.case_state = "resolved"
        case.resolved_at = now
        case.resolved_by_principal = principal
        case.resolution_schema_version = CLOSURE_SCHEMA
        case.resolution_document = ClosureAudit(request=request).model_dump(mode="json")
        result = TerminalResult(
            review_case_id=case.review_case_id,
            purchase_intent_id=purchase_id,
            state=row.state,
            already_resolved=False,
        )
        db.commit()
        return result
