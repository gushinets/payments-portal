"""Immutable allowance issuance in the caller's user-serialized transaction."""

from dataclasses import asdict
from datetime import date, datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from app.domains.billing.paid_contracts import EffectiveAllowance
from app.domains.billing.paid_cycles import CalendarEvidence, CycleKind, classify_cycle
from app.domains.purchases.contracts import AcceptedPurchase
from app.domains.identity.services.auth import as_utc
from app.infrastructure.queries import paid_access as queries
from app.models import ExternalSubscription, ManualReviewCase, PurchasedAllowance


def diagnose_cycle(db: Session, subscription: ExternalSubscription, metric: str) -> None:
    reference = f"{subscription.subscription_id}:{metric}"
    # Reuse the existing manual-review store; a metric review never blocks the
    # product grant or acquires subscription-level authority.
    from app.infrastructure.queries.paid_access import metric_review

    if metric_review(db, reference) is None:
        db.add(
            ManualReviewCase(
                reason_code="allowance_cycle_conflict",
                scope_kind="subscription_metric",
                scope_reference=reference,
                evidence_schema_version="allowance-cycle-review:v1",
                evidence_document={"metric_key": metric},
                case_state="open",
            )
        )


def materialize_allowance(
    db: Session,
    subscription: ExternalSubscription,
    accepted: AcceptedPurchase,
    cycle: CalendarEvidence | None,
    *,
    skew_seconds: int,
) -> EffectiveAllowance | None:
    technical = accepted.technical_terms
    if technical is None:
        return None
    offer = technical.offer
    component = str(accepted.selection.tariff_service_id)
    rows = queries.allowances(db, subscription.subscription_id, component, offer.metric_key)
    # Legacy UTC evidence has no proven calendar anchor. Preserve it, never infer.
    if any(row.calendar_document is None for row in rows):
        diagnose_cycle(db, subscription, offer.metric_key)
        return None
    first = CalendarEvidence.model_validate(rows[0].calendar_document) if rows else None
    latest = CalendarEvidence.model_validate(rows[-1].calendar_document) if rows else None
    result = classify_cycle(cycle, accepted.offer.period, first=first, latest=latest)
    if result.kind == CycleKind.AMBIGUOUS:
        diagnose_cycle(db, subscription, offer.metric_key)
        return None
    period = asdict(accepted.offer.period)
    period["price_effective_from"] = accepted.offer.period.price_effective_from.isoformat()
    period["price_effective_until"] = (
        accepted.offer.period.price_effective_until.isoformat() if accepted.offer.period.price_effective_until else None
    )
    terms = {"technical_terms": technical.model_dump(mode="json"), "period": period}
    if rows and (rows[0].terms_document != terms or rows[0].unit != offer.unit or rows[0].quantity != offer.quantity):
        diagnose_cycle(db, subscription, offer.metric_key)
        return None
    same = next((row for row in rows if row.provider_cycle_key == result.key), None)
    if same is None:
        start, end, source_start, source_end = None, None, None, None
        if cycle.precision == "timestamp":
            source_start, source_end = datetime.fromisoformat(cycle.start), datetime.fromisoformat(cycle.end)
            start = source_start + timedelta(seconds=skew_seconds)
            end = source_end - timedelta(seconds=skew_seconds)
            if start >= end:
                diagnose_cycle(db, subscription, offer.metric_key)
                return None
        same = PurchasedAllowance(
            allowance_id=uuid4(),
            subscription_id=subscription.subscription_id,
            source_component_id=component,
            product_id=offer.product_id,
            metric_key=offer.metric_key,
            quantity=offer.quantity,
            unit=offer.unit,
            provider_cycle_key=result.key,
            calendar_document=cycle.model_dump(mode="json"),
            terms_document=terms,
            cycle_schema_version="calendar:v1" if cycle.precision == "date" else "timestamp:v1",
            cycle_date_start=date.fromisoformat(cycle.start) if cycle.precision == "date" else None,
            cycle_date_end=date.fromisoformat(cycle.end) if cycle.precision == "date" else None,
            provider_cycle_start=source_start,
            provider_cycle_end=source_end,
            period_start=start,
            period_end=end,
        )
        db.add(same)
        db.flush()  # Unique logical identity; the caller's whole operation rolls back on failure.
    if len(queries.metric_cycle_allowances(db, subscription.subscription_id, offer.metric_key, result.key)) != 1:
        diagnose_cycle(db, subscription, offer.metric_key)
        return None
    review = queries.metric_review(db, f"{subscription.subscription_id}:{offer.metric_key}")
    if review is not None and review.reason_code == "allowance_cycle_conflict":
        from app.infrastructure.queries.billing_reconciliation import database_now

        review.case_state = "resolved"
        review.resolved_at = as_utc(database_now(db))
        review.resolved_by_principal = "system:original-cycle-proof"
        review.resolution_schema_version = "allowance-cycle-resolution:v1"
        review.resolution_document = {"allowance_id": str(same.allowance_id), "cycle_key": result.key}
    return EffectiveAllowance(
        allowance_id=str(same.allowance_id),
        product_id=same.product_id,
        metric_key=same.metric_key,
        unit=same.unit,
        quantity=same.quantity,
        cycle=CalendarEvidence.model_validate(same.calendar_document),
        period_start=as_utc(same.period_start).isoformat() if same.period_start else None,
        period_end=as_utc(same.period_end).isoformat() if same.period_end else None,
    )
