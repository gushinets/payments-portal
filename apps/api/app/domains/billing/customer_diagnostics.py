"""Read-only scoped customer state and allowlisted durable CREATE evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from app.core.settings import Settings
from app.domains.billing.contracts import CREATE_FAILURE_REASONS, CREATE_RESPONSE_SCHEMA, BillingRefused
from app.domains.billing.customers import _receipt_id
from app.domains.catalog.publication import SessionFactory
from app.infrastructure.queries.billing_customers import (
    diagnostic_create_reviews,
    diagnostic_customer_rows,
    diagnostic_user,
    provider_customer_owner,
)


@dataclass(frozen=True, repr=False)
class CustomerDiagnosticInput:
    report: dict[str, object]
    email: str = field(repr=False)
    email_normalized: str = field(repr=False)
    outer_key: str | None = field(default=None, repr=False)
    account_id: str | None = None
    customer_id: UUID | None = None
    operation_id: UUID | None = None
    provider_ids: tuple[str, ...] = ()
    local_problem: str | None = None


def _failure(value: object, source: str) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    status, code, reason = value.get("http_status"), value.get("lbx_code"), value.get("reason")
    if type(status) is not int or not 100 <= status <= 599:
        return None
    if code is not None and (type(code) is not int or not -(2**31) <= code < 2**31):
        return None
    recorded_at = value.get("recorded_at")
    try:
        stamp = datetime.fromisoformat(recorded_at) if isinstance(recorded_at, str) else None
    except ValueError:
        return None
    if stamp is None or stamp.tzinfo is None:
        return None
    return {
        "source": source,
        "http_status": status,
        "lbx_code": code,
        "reason": reason if isinstance(reason, str) and reason in CREATE_FAILURE_REASONS else "unknown",
        "recorded_at": stamp.astimezone(UTC).isoformat(),
    }


def load_customer_diagnostics(
    factory: SessionFactory, configuration: Settings, user_id: UUID
) -> CustomerDiagnosticInput:
    with factory() as db:
        user = diagnostic_user(
            db, user_id=user_id, tenant_id=configuration.instance_tenant_id, region=configuration.instance_region
        )
        if user is None:
            raise BillingRefused("billing_customer_user_not_found", 404)
        report: dict[str, object] = {
            "user_id": str(user.id),
            "email_verified": user.email_verified_at is not None,
            "create_responses": [],
            "customer_id": None,
            "create_operation_id": None,
        }
        rows = diagnostic_customer_rows(db, user.id)
        if len(rows) != 1:
            return CustomerDiagnosticInput(
                report,
                user.email,
                user.email_normalized,
                local_problem="not_provisioned" if not rows else "connection_conflict",
            )
        customer, operation, work = rows[0]
        report.update(
            customer_id=str(customer.customer_id),
            binding_state=customer.binding_state,
            provider_customer_id=customer.provider_customer_id,
        )
        if customer.provider_origin != configuration.lbx_provider_origin:
            return CustomerDiagnosticInput(
                report, user.email, user.email_normalized, local_problem="connection_conflict"
            )
        receipt = None
        problem = None
        failures = []
        if operation is not None:
            report.update(
                create_operation_id=str(operation.create_operation_id),
                operation_state=operation.operation_state,
                has_send_fence=operation.send_fence is not None,
                unknown_since=operation.unknown_since.isoformat() if operation.unknown_since else None,
                recovery_deadline=operation.unknown_recovery_deadline_at.isoformat()
                if operation.unknown_recovery_deadline_at
                else None,
            )
            if operation.request_correlation_key != customer.billing_customer_key:
                problem = "identity_conflict"
            try:
                receipt = _receipt_id(operation)
            except BillingRefused:
                problem = "receipt_invalid"
            if work is not None:
                raw = work.payload_document.get("last_failed_create")
                if isinstance(raw, dict) and raw.get("schema_version") == CREATE_RESPONSE_SCHEMA:
                    evidence = _failure(raw, "recovery_work_item")
                    if evidence is not None:
                        failures.append(evidence)
            # Historical, explicitly audited curl comparisons contain safe codes,
            # never parse their arbitrary text or private file/log counterparts.
            for review in diagnostic_create_reviews(db, operation.create_operation_id):
                if review.evidence_schema_version != "curl-customer-comparison:v1":
                    continue
                raw = review.evidence_document.get("comparison_outcome")
                if isinstance(raw, dict):
                    evidence = _failure(
                        {
                            "http_status": raw.get("owner_http"),
                            "lbx_code": raw.get("owner_lbx_code"),
                            "recorded_at": review.created_at.isoformat(),
                            "reason": "email_not_unique"
                            if raw.get("safe_provider_reason") == "email_must_be_unique"
                            else "unknown",
                        },
                        "operator_create_comparison",
                    )
                    if evidence is not None:
                        failures.append(evidence)
        failures.sort(key=lambda item: item["recorded_at"], reverse=True)
        report.update(receipt_candidate_id=receipt, create_responses=failures)
        ids = tuple(
            dict.fromkeys(
                value
                for value in (
                    customer.provider_customer_id,
                    receipt,
                    operation.bound_external_object_id if operation else None,
                )
                if value is not None
            )
        )
        if any(
            not value.isascii()
            or not value.isdecimal()
            or len(value) > 20
            or int(value) <= 0
            or str(int(value)) != value
            for value in ids
        ):
            problem = "receipt_invalid"
        if len(ids) > 1:
            problem = "identity_conflict"
        return CustomerDiagnosticInput(
            report,
            user.email,
            user.email_normalized,
            customer.billing_customer_key,
            customer.external_billing_account_id,
            customer.customer_id,
            operation.create_operation_id if operation else None,
            ids,
            problem,
        )


def diagnostic_owner_conflict(
    factory: SessionFactory,
    configuration: Settings,
    user_id: UUID,
    *,
    account_id: str,
    customer_id: UUID,
    provider_ids: tuple[int, ...],
) -> bool:
    with factory() as db:
        if (
            diagnostic_user(
                db, user_id=user_id, tenant_id=configuration.instance_tenant_id, region=configuration.instance_region
            )
            is None
        ):
            return True
        return any(
            provider_customer_owner(db, account_id=account_id, provider_id=str(value)) not in {None, customer_id}
            for value in provider_ids
        )
