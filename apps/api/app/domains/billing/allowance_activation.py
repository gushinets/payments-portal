"""Retain exact committed membership without changing purchased allowance history."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.orm import Session

from app.domains.billing.paid_contracts import EffectiveState
from app.domains.billing.paid_cycles import CalendarEvidence, CycleKind, classify_cycle
from app.domains.billing.reconciliation_contracts import CommercialProof, IdentityProof
from app.domains.catalog.commercial_offer import CommercialPeriod
from app.infrastructure.queries import paid_access, paid_usage
from app.models import BillingStateObservation, BillingStateObservationKind, PurchasedAllowance, User


class ActivationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["allowance-activation:v1"] = "allowance-activation:v1"
    allowance_id: UUID


def retain_activations(
    db: Session, user: User, state: EffectiveState, revision: int, effective_at: datetime, observed_at: datetime
) -> None:
    """Sole writer holds User; effective_at proves membership, not its first-ever occurrence."""
    for item in state.allowances:
        allowance_id = UUID(item.allowance_id)
        if paid_usage.activation(db, allowance_id) is not None:
            continue
        subject = paid_usage.activation_subject(db, user.id, allowance_id)
        if subject is None:
            raise ValueError("committed allowance has no saved subject")
        allowance, subscription, scope = subject
        if (allowance.product_id, allowance.metric_key, allowance.quantity) != (
            item.product_id,
            item.metric_key,
            item.quantity,
        ):
            raise ValueError("committed allowance subject mismatch")
        evidence = ActivationEvidence(allowance_id=allowance_id)
        db.add(
            BillingStateObservation(
                observation_kind=BillingStateObservationKind.ALLOWANCE_ACTIVATION,
                external_billing_account_id=subscription.external_billing_account_id,
                user_id=user.id,
                product_id=allowance.product_id,
                access_scope_id=scope.access_scope_id,
                subscription_id=subscription.subscription_id,
                observed_at=observed_at,
                effective_at=effective_at,
                evidence_schema_version=evidence.schema_version,
                evidence_document=evidence.model_dump(mode="json"),
                completeness_classification="complete",
                result_classification="committed_membership",
                resulting_access_revision=revision,
            )
        )
        # Queries also see facts appended earlier in this same transaction.
        db.flush()


def was_activated(db: Session, row: PurchasedAllowance) -> bool:
    receipt = paid_usage.activation(db, row.allowance_id)
    if receipt is not None:
        evidence = ActivationEvidence.model_validate(receipt.evidence_document)
        return (
            receipt.evidence_schema_version == evidence.schema_version
            and evidence.allowance_id == row.allowance_id
            and receipt.subscription_id == row.subscription_id
            and receipt.product_id == row.product_id
        )
    # Only pre-receipt writers may use the conservative legacy proof. Never
    # infer V2 activation from issuance or from the passage of wall-clock time.
    candidates = paid_usage.legacy_activation_candidates(
        db,
        row,
        schema="subscription-reconciliation:v1",
        selection_schema="primary-selection:v1",
        identity=IdentityProof.MATCH,
        commercial=CommercialProof.MATCH,
    )
    if not candidates:
        return False
    rows = paid_access.allowances(db, row.subscription_id, row.source_component_id, row.metric_key)
    try:
        first = CalendarEvidence.model_validate(rows[0].calendar_document)
        target = CalendarEvidence.model_validate(row.calendar_document)
        saved = row.terms_document["period"]
        period = CommercialPeriod(
            **{
                **saved,
                "price_effective_from": date.fromisoformat(saved["price_effective_from"]),
                "price_effective_until": date.fromisoformat(saved["price_effective_until"])
                if saved["price_effective_until"]
                else None,
            }
        )
    except (ValidationError, ValueError, TypeError, KeyError):
        # Incomplete legacy evidence cannot manufacture activation authority.
        return False
    for candidate in candidates:
        try:
            cycle = CalendarEvidence.model_validate(candidate.evidence_document["cycle"])
        except (ValidationError, KeyError, TypeError):
            # A complete commercial read can still have an unresolved calendar.
            continue
        if classify_cycle(cycle, period, first=first, latest=target).kind == CycleKind.SAME:
            return True
    return False
