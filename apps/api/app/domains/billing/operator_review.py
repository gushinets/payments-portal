"""Narrow audited review authorization; source proof and business writers are shared."""

import re
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.domains.billing.customers import lock_customer, lock_user
from app.domains.billing.customer_scope import connection_account
from app.domains.billing.operator_contracts import (
    RESOLUTION_SCHEMA,
    OriginalOperationProof,
    ResolutionRequest,
    ReviewResolution,
)
from app.domains.billing.reconciliation_contracts import CommercialProof, IdentityProof
from app.domains.billing.operator_cases import validate_case, original_possible_send, digest, case_digest
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import service
from app.domains.purchases.contracts import FinancialOperation, Purchase, PurchaseRefused
from app.infrastructure.queries import billing_operator as queries, billing_reconciliation, purchases
from app.infrastructure.queries.billing_customers import customer_operation, recovery_work
from app.models import (
    ExternalBillingCustomerBindingState as Binding,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ExternalSubscription,
    ManualReviewCase,
    PurchaseIntent,
    PurchaseIntentState,
)


def command_digest(request: ResolutionRequest, principal: str) -> str:
    return digest({"request": request.model_dump(mode="json"), "principal": principal})


def customer_digest(db: Session, purchase: Purchase) -> str:
    customer = lock_customer(db, purchase.customer_id)
    op = customer_operation(db, purchase.customer_id)
    return digest(
        {
            "customer": str(customer.customer_id),
            "user": str(customer.user_id),
            "account": customer.external_billing_account_id,
            "origin": customer.provider_origin,
            "state": customer.binding_state,
            "provider": customer.provider_customer_id,
            "key": customer.billing_customer_key,
            "operation": str(op.create_operation_id) if op else None,
            "operation_state": op.operation_state if op else None,
            "bound": op.bound_external_object_id if op else None,
            "fence": str(op.send_fence) if op else None,
        }
    )


def operation_digest(db: Session, operations: list[ExternalCreateOperation]) -> str:
    return digest(
        [
            {
                "id": str(op.create_operation_id),
                "kind": op.operation_kind,
                "state": op.operation_state,
                "key": op.request_correlation_key,
                "fence": str(op.send_fence),
                "bound": op.bound_external_object_id,
                "unknown_since": as_utc(op.unknown_since).isoformat() if op.unknown_since else None,
                "deadline": as_utc(op.unknown_recovery_deadline_at).isoformat()
                if op.unknown_recovery_deadline_at
                else None,
                "schema": op.recovery_hint_schema_version,
                "hint": op.recovery_hint_document,
                "candidate": (
                    work.payload_document.get("candidate_id")
                    if (work := recovery_work(db, op.create_operation_id))
                    else None
                ),
            }
            for op in operations
        ]
    )


def identities(operations: list[ExternalCreateOperation], subscription: ExternalSubscription | None) -> dict:
    return {
        "operations": [
            {
                "id": str(op.create_operation_id),
                "kind": op.operation_kind,
                "bound_id": op.bound_external_object_id,
                "send_fence": str(op.send_fence),
            }
            for op in operations
        ],
        "subscription_id": str(subscription.subscription_id) if subscription else None,
        "external_subscription_id": subscription.external_subscription_id if subscription else None,
        "external_agreement_id": subscription.external_agreement_id if subscription else None,
        "observation_id": str(subscription.latest_observation_id)
        if subscription and subscription.latest_observation_id
        else None,
        "reconciliation_fence": subscription.reconciliation_fencing_token if subscription else None,
    }


def prepare_resolution(
    factory: SessionFactory,
    configuration: Settings,
    request: ResolutionRequest,
    principal: str,
    *,
    io_timeout_seconds: float,
) -> ReviewResolution | dict:
    if not re.fullmatch(r"os-euid:[0-9]+", principal):
        raise PurchaseRefused("mapping_operator_identity_unavailable", 403)
    purchase = service.inspect_purchase(factory, configuration, request.user_id, request.purchase_id)
    with factory() as db:
        lock_user(db, purchase.user_id)
        customer = lock_customer(db, purchase.customer_id)
        customer_op = customer_operation(db, purchase.customer_id)
        row = service._locked(db, purchase)
        operations = purchases.operations(db, purchase.id, lock=True)
        subscription = purchases.linked_subscription(db, purchase.id)
        case = queries.review(db, request.case_id, lock=True)
        if case is not None and case.case_state == "resolved":
            if (
                case.resolution_schema_version == RESOLUTION_SCHEMA
                and isinstance(case.resolution_document, dict)
                and case.resolution_document.get("command_digest") == command_digest(request, principal)
            ):
                return {
                    "review_case_id": str(case.review_case_id),
                    "outcome": "already_resolved",
                    "observation_id": case.resolution_document.get("observation_id"),
                }
            raise PurchaseRefused("billing_review_stale", 409)
        case, related = validate_case(db, request, purchase, subscription, operations)
        if (
            customer.binding_state != Binding.BOUND
            or customer_op is None
            or customer_op.operation_state != State.BOUND
            or customer_op.bound_external_object_id != customer.provider_customer_id
            or customer_op.request_correlation_key != customer.billing_customer_key
            or customer.provider_origin != purchase.accepted.provider_origin
            or customer.provider_origin != configuration.lbx_provider_origin
            or purchase.account_id != connection_account(db, configuration)
        ):
            raise PurchaseRefused("billing_identity_unproven", 409)
        service._verify_original_consent(db, row, purchase.accepted)
        now = as_utc(billing_reconciliation.database_now(db))
        saved_request = None
        if request.resolution in {"restore-original", "select-primary"}:
            if (
                subscription is None
                or subscription.latest_observation_id != request.expected_observation_id
                or subscription.reconciliation_fencing_token != request.expected_reconciliation_fence
                or any(
                    not op.bound_external_object_id or op.operation_state not in {State.BOUND, State.MANUAL_REVIEW}
                    for op in operations
                )
            ):
                raise PurchaseRefused("billing_review_stale", 409)
        else:
            target = next((op for op in operations if op.create_operation_id == request.operation_id), None)
            if (
                target is None
                or target.send_fence != request.expected_operation_fence
                or target.operation_state != State.MANUAL_REVIEW
                or target.bound_external_object_id is not None
                or target.unknown_since is None
                or target.recovery_hint_schema_version != "financial-create:v1"
                or subscription is not None
                or not original_possible_send(case, related, purchase)
            ):
                raise PurchaseRefused("purchase_history_unproven", 409)
            if any(op is not target and op.operation_state == State.MANUAL_REVIEW for op in operations):
                raise PurchaseRefused("billing_review_unrelated_cases", 409)
            other = next((op for op in operations if op is not target), None)
            if (
                len(operations) != 2
                or other is None
                or (
                    target.operation_kind == Kind.AGREEMENT
                    and other.operation_state not in {State.PENDING, State.PROVEN_NOT_SENT}
                )
                or (
                    target.operation_kind == Kind.SUBSCRIPTION
                    and (other.operation_state != State.BOUND or not other.bound_external_object_id)
                )
            ):
                raise PurchaseRefused("purchase_history_unproven", 409)
            if (
                not isinstance(target.recovery_hint_document, dict)
                or target.recovery_hint_document.get("purchase_intent_id") != str(purchase.id)
                or target.recovery_hint_document.get("accepted_fingerprint") != purchase.accepted.offer.fingerprint
                or not isinstance(target.recovery_hint_document.get("request"), dict)
            ):
                raise PurchaseRefused("purchase_history_unproven", 409)
            saved_request = target.recovery_hint_document["request"]
        return ReviewResolution(
            request,
            principal,
            service._snapshot(db, row),
            operation_digest(db, operations),
            customer_digest(db, purchase),
            saved_request,
            identities(operations, subscription),
            now,
            now + timedelta(seconds=io_timeout_seconds + 30),
            tuple((item.review_case_id, case_digest(item)) for item in related),
        )


def authorize_original_binding(
    db: Session,
    resolution: ReviewResolution,
    proof: OriginalOperationProof | None,
    row: PurchaseIntent,
    operations: list[ExternalCreateOperation],
    subscription: ExternalSubscription | None,
    expected: FinancialOperation,
) -> ManualReviewCase:
    now = as_utc(billing_reconciliation.database_now(db))
    if (
        proof is None
        or resolution.request.operation_id != expected.id
        or proof.read_started_at < resolution.started_at
        or proof.read_started_at > proof.read_finished_at
        or proof.read_finished_at > now
        or proof.read_finished_at >= resolution.expires_at - timedelta(seconds=30)
        or proof.request_digest != digest(resolution.saved_request)
        or (
            expected.kind == Kind.SUBSCRIPTION
            and (
                proof.subscription is None
                or proof.subscription.identity != IdentityProof.MATCH
                or proof.subscription.commercial != CommercialProof.MATCH
                or proof.subscription.lifecycle is None
            )
        )
    ):
        raise PurchaseRefused("billing_review_proof_incomplete", 409)
    return authorize_resolution(db, resolution, row, operations, subscription, restoring=False)


def authorize_resolution(
    db: Session,
    resolution: ReviewResolution,
    row: PurchaseIntent,
    operations: list[ExternalCreateOperation],
    subscription: ExternalSubscription | None,
    *,
    restoring: bool,
) -> ManualReviewCase:
    """Called only inside the shared writer, after its normal provenance locks."""
    from app.domains.purchases.inventory import validate_inventory, validate_inventory_product

    if resolution.inventory is None:
        raise PurchaseRefused("billing_review_proof_incomplete", 409)
    resolution.inventory.require_clear(
        resolution.purchase, original=True, primary=resolution.request.resolution == "select-primary"
    )
    if resolution.request.resolution == "select-primary":
        validate_inventory_product(db, resolution.inventory, resolution.purchase.accepted.selection.product_id)
    else:
        validate_inventory(db, resolution.inventory)
    request = resolution.request
    now = as_utc(billing_reconciliation.database_now(db))
    if (
        now >= resolution.expires_at
        or row.purchase_intent_id != request.purchase_id
        or row.user_id != request.user_id
        or service.accepted(row) != resolution.purchase.accepted
        or operation_digest(db, operations) != resolution.operation_digest
        or customer_digest(db, resolution.purchase) != resolution.customer_digest
        or restoring != (request.resolution in {"restore-original", "select-primary"})
    ):
        raise PurchaseRefused("billing_review_stale", 409)
    case, related = validate_case(db, request, resolution.purchase, subscription, operations)
    if tuple((item.review_case_id, case_digest(item)) for item in related) != resolution.related_case_digests:
        raise PurchaseRefused("billing_review_stale", 409)
    service._verify_original_consent(db, row, resolution.purchase.accepted)
    if subscription is not None:
        if (
            subscription.latest_observation_id != request.expected_observation_id
            or subscription.reconciliation_fencing_token != request.expected_reconciliation_fence + 1
        ):
            raise PurchaseRefused("billing_review_stale", 409)
    for op in operations:
        if restoring or op.create_operation_id != request.operation_id:
            # Reject financial callbacks/inventory begun before this audited
            # decision. The target bind rotates its own fence after rechecking.
            op.send_fence = uuid4()
        if restoring:
            if op.bound_external_object_id is None:
                raise PurchaseRefused("purchase_history_unproven", 409)
            op.operation_state = State.BOUND
    if restoring:
        row.state = PurchaseIntentState.LINKED
        row.state_updated_at = now
    # The case and resulting facts commit together. Failure anywhere rolls both back.
    document = {
        "command_digest": command_digest(request, resolution.principal),
        "resolution": request.resolution,
        "reason": request.reason,
        "reference": request.reference,
        "before": resolution.before,
        "inventory": {
            "complete": resolution.inventory.complete,
            "customer_id": str(resolution.inventory.customer.customer_id),
            "purchase_ids": [str(item.id) for item in resolution.inventory.purchases],
            "pending_original_ids": [str(identity) for identity in resolution.inventory.pending],
            "conflicts": [str(identity) for identity in resolution.inventory.conflicts],
        },
        "related_deadline_cases": [{"id": str(item.review_case_id), "digest": case_digest(item)} for item in related],
    }
    if request.resolution == "select-primary":
        document["inventory"]["primary_product"] = next(
            item
            for item in resolution.inventory.products
            if item.product_id == resolution.purchase.accepted.selection.product_id
        ).model_dump(mode="json")
    for item in (case, *related):
        item.case_state = "resolved"
        item.resolved_at = now
        item.resolved_by_principal = resolution.principal
        item.resolution_schema_version = RESOLUTION_SCHEMA
        item.resolution_document = document
    db.flush()
    return case


def audit_resolution(
    db: Session,
    case: ManualReviewCase,
    operations: list[ExternalCreateOperation],
    subscription: ExternalSubscription | None,
    *,
    observation_id: UUID | None,
    proof: dict,
) -> None:
    case.resolution_document = {
        **case.resolution_document,
        "after": identities(operations, subscription),
        "observation_id": str(observation_id) if observation_id else None,
        "proof": proof,
    }
    for related in case.resolution_document["related_deadline_cases"]:
        previous = queries.review(db, UUID(related["id"]), lock=True)
        previous.resolution_document = {
            **case.resolution_document,
            "related_to_review_case_id": str(case.review_case_id),
        }
    db.flush()


def audit_original_binding(
    db: Session,
    case: ManualReviewCase,
    operations: list[ExternalCreateOperation],
    subscription: ExternalSubscription | None,
    *,
    proof: OriginalOperationProof | None,
) -> None:
    if proof is None:
        raise PurchaseRefused("billing_review_proof_incomplete", 409)
    sub = proof.subscription
    audit_resolution(
        db,
        case,
        operations,
        subscription,
        observation_id=subscription.latest_observation_id if subscription else None,
        proof={
            "schema": "original-operation-proof:v1",
            "discovery": "unique_complete",
            "request_digest": proof.request_digest,
            "read_started_at": proof.read_started_at.isoformat(),
            "read_finished_at": proof.read_finished_at.isoformat(),
            "subscription": {
                "schema": "subscription-reconciliation:v1",
                "identity": sub.identity,
                "commercial": sub.commercial,
                "lifecycle": sub.lifecycle,
                "financial": sub.financial,
                "calendar_complete": sub.calendar_complete,
                "reads": list(sub.reads),
            }
            if sub
            else None,
        },
    )
