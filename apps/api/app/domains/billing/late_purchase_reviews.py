"""Keep the restriction and its audit on the existing exact-object review case."""

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.customer_scope import connection_account
from app.domains.billing.customers import lock_customer, lock_user
from app.domains.billing.operator_review import case_digest
from app.domains.billing.terminal_resolution import (
    SafeText,
    SCHEMA,
    TERMINAL_REASON,
    TerminalAudit,
    TerminalResult,
    lock_financial_object,
)
from app.domains.catalog.mapping_evidence import Digest
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import service
from app.domains.purchases.contracts import Purchase, PurchaseInventoryIncomplete, PurchaseRefused
from app.domains.purchases.recovery_evidence import ProviderId
from app.infrastructure.queries import (
    billing_operator,
    billing_reconciliation,
    late_purchase_reviews as queries,
    purchases,
)
from app.infrastructure.queries.billing_customers import customer_operation
from app.models import ExternalCreateOperation, ExternalCreateOperationKind as Kind, ManualReviewCase, PurchaseIntent

REASON = "purchase_late_external_object"
CASE_SCHEMA = "purchase-late-object:v1"
CLOSURE_SCHEMA = "purchase-late-object-closure:v1"


class LateObjectEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Kind
    external_object_id: ProviderId
    competing_tariff_id: int | None = Field(default=None, gt=0)
    read_finished_at: AwareDatetime
    agreement_id: ProviderId | None = None


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


def _original(db: Session, row: PurchaseIntent) -> ReleasedOriginal:
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
        op.kind: frozenset(value for value in (op.bound_id, proofs.get(op.id)) if value is not None)
        for op in purchase.operations
    }
    return ReleasedOriginal(purchase, identities[Kind.AGREEMENT], identities[Kind.SUBSCRIPTION])


def released_original(factory: SessionFactory, purchase: Purchase) -> ReleasedOriginal | None:
    with factory() as db:
        row = purchases.owned(db, purchase.user_id, purchase.id)
        if row is None or not row.state.resolved:
            return None
        return (
            _original(db, row)
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
        )
        if len(rows) > 100:
            raise PurchaseInventoryIncomplete()
        return tuple(_original(db, row) for row in rows)


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
        active = next((case for case in cases if case.scope_reference == str(purchase.id)), None)
        if active is not None:
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
    if queries.other_audited_owner(db, operation, external_id, reason=TERMINAL_REASON, schema=SCHEMA):
        raise PurchaseRefused("purchase_review_required", 409)


def close_case(
    factory: SessionFactory, configuration: Settings, request: ClosureRequest, principal: str
) -> TerminalResult:
    if not re.fullmatch(r"os-euid:[0-9]+", principal):
        raise PurchaseRefused("mapping_operator_identity_unavailable", 403)
    original = service.inspect_purchase(factory, configuration, request.user_id, request.purchase_id)
    with factory() as db:
        lock_user(db, original.user_id)
        customer = lock_customer(db, original.customer_id)
        row = purchases.owned(db, original.user_id, original.id, lock=True)
        case = billing_operator.review(db, request.case_id, lock=True)
        if (
            row is None
            or not row.state.resolved
            or case is None
            or (case.scope_kind, case.scope_reference, case.reason_code, case.evidence_schema_version)
            != ("purchase_intent", str(original.id), REASON, CASE_SCHEMA)
        ):
            raise PurchaseRefused("billing_review_stale", 409)
        evidence = LateObjectEvidence.model_validate(case.evidence_document)
        lock_financial_object(db, original.account_id, evidence.kind, evidence.external_object_id)
        if case.case_state != "open":
            if (
                case.resolution_schema_version == CLOSURE_SCHEMA
                and case.resolved_by_principal == principal
                and ClosureAudit.model_validate(case.resolution_document).request == request
            ):
                return TerminalResult(
                    review_case_id=case.review_case_id,
                    purchase_intent_id=original.id,
                    state=row.state,
                    already_resolved=True,
                )
            raise PurchaseRefused("billing_review_stale", 409)
        if (
            request.expected_digest != case_digest(case)
            or request.evidence.external_object_id != evidence.external_object_id
            or customer.external_billing_account_id != connection_account(db, configuration)
            or customer.provider_origin != configuration.lbx_provider_origin
        ):
            raise PurchaseRefused("billing_review_stale", 409)
        now = as_utc(billing_reconciliation.database_now(db))
        if not evidence.read_finished_at <= request.evidence.confirmed_at <= now:
            raise PurchaseRefused("purchase_resolution_confirmation_required", 409)
        case.case_state = "resolved"
        case.resolved_at = now
        case.resolved_by_principal = principal
        case.resolution_schema_version = CLOSURE_SCHEMA
        case.resolution_document = ClosureAudit(request=request).model_dump(mode="json")
        result = TerminalResult(
            review_case_id=case.review_case_id,
            purchase_intent_id=original.id,
            state=row.state,
            already_resolved=False,
        )
        db.commit()
        return result
