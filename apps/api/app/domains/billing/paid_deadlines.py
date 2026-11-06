"""Effective deadlines reuse the existing subscription expiry queue."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.domains.billing.paid_contracts import EffectiveState
from app.domains.identity.services.auth import as_utc
from app.infrastructure.persistence.billing_work import coalesce
from app.models import BillingProductAccessScope, ExternalSubscription


def effective_deadline(scope: BillingProductAccessScope) -> datetime | None:
    if scope.effective_access_document is None or scope.effective_access_until is None:
        return None
    state = EffectiveState.model_validate(scope.effective_access_document)
    return min(
        [
            as_utc(scope.effective_access_until),
            *(datetime.fromisoformat(item.period_end) for item in state.allowances if item.period_end),
            *(datetime.fromisoformat(item.valid_until) for item in state.grants if item.valid_until),
        ]
    )


def schedule_deadline(db: Session, sub: ExternalSubscription, scope: BillingProductAccessScope | None = None) -> None:
    """Caller finishes business/state locks before touching queue rows."""
    deadlines = []
    if (
        sub.latest_observation_id is not None
        and sub.reconciliation_fencing_token
        and as_utc(sub.projection_valid_until) > as_utc(sub.last_authoritative_read_at)
    ):
        deadlines.append(as_utc(sub.projection_valid_until))
    paid = effective_deadline(scope) if scope and scope.primary_subscription_id == sub.subscription_id else None
    if paid is not None:
        deadlines.append(paid)
    if not deadlines:
        return
    deadline = min(deadlines)
    coalesce(
        db,
        kind="subscription_trust_expiry",
        key=f"{sub.external_billing_account_id}:{sub.subscription_id}",
        scope_kind="subscription",
        reference=str(sub.subscription_id),
        due=deadline,
        priority=1,
        payload={
            "supporting_observation_id": str(sub.latest_observation_id),
            "access_basis_observation_id": str(scope.access_basis_observation_id) if paid else None,
            "deadline": deadline.isoformat(),
        },
        replace_deadline=True,
    )
