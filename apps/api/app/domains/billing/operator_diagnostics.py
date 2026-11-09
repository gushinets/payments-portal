"""Allowlisted local purchase evidence; no provider calls, row locks or writes."""

from uuid import UUID

from app.core.settings import Settings
from app.domains.billing.operator_review import case_digest
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import service
from app.domains.purchases.contracts import PurchaseRefused
from app.infrastructure.queries import billing_operator as queries, billing_reconciliation, purchases
from app.infrastructure.queries.billing_customers import diagnostic_user
from app.infrastructure.queries.billing_background import operation_subject
from app.domains.billing.customer_scope import connection_account


def inspect_operation(factory: SessionFactory, configuration: Settings, operation_id: UUID) -> dict:
    """Resolve a Sentry correlation locally without sending user data to Sentry."""
    with factory() as db:
        found = operation_subject(db, operation_id)
        if found is None:
            raise PurchaseRefused("purchase_not_found", 404)
        op, customer = found
        if (
            customer.external_billing_account_id != connection_account(db, configuration)
            or customer.provider_origin != configuration.lbx_provider_origin
            or diagnostic_user(
                db,
                user_id=customer.user_id,
                tenant_id=configuration.instance_tenant_id,
                region=configuration.instance_region,
            )
            is None
        ):
            raise PurchaseRefused("purchase_not_found", 404)
        result = {
            "create_operation_id": str(op.create_operation_id),
            "kind": op.operation_kind.value,
            "state": op.operation_state.value,
            "user_id": str(customer.user_id),
            "purchase_intent_id": str(op.purchase_intent_id) if op.purchase_intent_id else None,
        }
        user_id, purchase_id = customer.user_id, op.purchase_intent_id
    if purchase_id is None:
        result["inspect_command"] = f".venv/bin/python scripts/repo.py billing-customer diagnose --user-id {user_id}"
        result["recover_action"] = "Ask the user to explicitly reopen their billing account after source recovery."
    else:
        command = f".venv/bin/python scripts/repo.py billing-purchase {{action}} --user-id {user_id} --purchase-id {purchase_id}"
        result["inspect_command"] = command.format(action="inspect")
        result["recover_command"] = command.format(action="recover")
    return result


def inspect_evidence(factory: SessionFactory, configuration: Settings, user_id: UUID, purchase_id: UUID) -> dict:
    with factory() as db:
        if (
            diagnostic_user(
                db, user_id=user_id, tenant_id=configuration.instance_tenant_id, region=configuration.instance_region
            )
            is None
        ):
            raise PurchaseRefused("purchase_not_found", 404)
        row = purchases.owned(db, user_id, purchase_id)
        if row is None:
            raise PurchaseRefused("purchase_not_found", 404)
        purchase = service._snapshot(db, row)
        sub = queries.subscription(db, purchase.id)
        references = (
            str(purchase.id),
            str(purchase.customer_id),
            *(str(op.id) for op in purchase.operations),
            *((str(sub.subscription_id),) if sub else ()),
        )
        work = queries.work(db, references)
        reviews = queries.reviews(db, purchase.id, purchase.customer_id, sub.subscription_id if sub else None)
        now = as_utc(billing_reconciliation.database_now(db))
        return {
            "purchase_intent_id": str(purchase.id),
            "state": purchase.state,
            "reason": purchase.reason,
            "scope_held": purchase.held,
            "operations": [
                {
                    "create_operation_id": str(op.id),
                    "kind": op.kind,
                    "state": op.state,
                    "send_fence": str(op.fence) if op.fence else None,
                    "bound": op.bound_id is not None,
                    "receipt_saved": op.candidate_id is not None,
                    "deadline": op.deadline.isoformat() if op.deadline else None,
                    "last_failure": {
                        "code": op.last_failure_code,
                        "http_status": op.last_failure[0],
                        "lbx_code": op.last_failure[1],
                        "reason": op.last_failure[2],
                    }
                    if op.last_failure
                    else None,
                }
                for op in purchase.operations
            ],
            "subscription": {
                "subscription_id": str(sub.subscription_id),
                "lifecycle": sub.lifecycle_status,
                "financial": sub.financial_access_status,
                "commercial": sub.commercial_access_status,
                "last_authoritative_read_at": sub.last_authoritative_read_at.isoformat(),
                "projection_valid_until": sub.projection_valid_until.isoformat(),
                "trust_expired": as_utc(sub.projection_valid_until) <= now,
                "supporting_observation_id": str(sub.latest_observation_id) if sub.latest_observation_id else None,
                "reconciliation_fence": sub.reconciliation_fencing_token,
                "lease_expires_at": sub.reconciliation_lease_expires_at.isoformat()
                if sub.reconciliation_lease_expires_at
                else None,
            }
            if sub
            else None,
            "observations": [
                {
                    "observation_id": str(obs.observation_id),
                    "schema": obs.evidence_schema_version,
                    "kind": obs.observation_kind,
                    "observed_at": obs.observed_at.isoformat(),
                    "completeness": obs.completeness_classification,
                    "result": obs.result_classification,
                }
                for obs in queries.observations(db, sub.subscription_id)
            ]
            if sub
            else [],
            "work": [
                {
                    "work_item_id": str(item.work_item_id),
                    "kind": item.work_kind,
                    "state": item.work_state,
                    "next_attempt_at": item.next_attempt_at.isoformat(),
                    "generation": item.enqueue_generation,
                    "attempts": item.attempt_count,
                    "last_error_classification": item.last_error_classification,
                    "lease_expires_at": item.lease_expires_at.isoformat() if item.lease_expires_at else None,
                    "last_attempt_started_at": item.last_attempt_started_at.isoformat()
                    if item.last_attempt_started_at
                    else None,
                }
                for item in work[:100]
            ],
            "reviews": [
                {
                    "review_case_id": str(case.review_case_id),
                    "reason": case.reason_code,
                    "scope_kind": case.scope_kind,
                    "scope_reference": case.scope_reference,
                    "state": case.case_state,
                    "expected_case_digest": case_digest(case),
                    "schema": case.evidence_schema_version,
                    "resolution_schema": case.resolution_schema_version,
                    "resolved_at": case.resolved_at.isoformat() if case.resolved_at else None,
                }
                for case in reviews[:100]
            ],
            "work_truncated": len(work) > 100,
            "reviews_truncated": len(reviews) > 100,
        }


def purchase_subscription(factory: SessionFactory, configuration: Settings, user_id: UUID, purchase_id: UUID) -> UUID:
    evidence = inspect_evidence(factory, configuration, user_id, purchase_id)
    if evidence["subscription"] is None:
        raise PurchaseRefused("subscription_provenance_unproven", 409)
    return UUID(evidence["subscription"]["subscription_id"])
