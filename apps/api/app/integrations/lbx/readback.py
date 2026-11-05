"""Owned restricting facts survive incomplete effective-term admission."""

from dataclasses import replace
from datetime import datetime

from app.core.time import utc_now
from app.domains.billing.readback_contracts import (
    BoundReadbackSubject,
    BoundSourceNegative,
    NegativeBasis,
    OriginalCreateProof,
    OriginalCreateReadbackSubject,
    ReadbackSubject,
    ScopedReadbackFinding,
)
from app.domains.billing.reconciliation_contracts import CommercialProof
from app.infrastructure.preflight import PreflightBudget, PreflightDeadlineExceeded
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.customer import LbxUser
from app.integrations.lbx.errors import LbxError, LbxResponseInvalid, LbxScopeMismatch
from app.integrations.lbx.financial import (
    Agreement,
    NewSubscription,
    Subscription,
    agreement_closed,
    classify_lifecycle,
    inspect_effective_terms,
    prove_agreement,
    prove_subscription,
)
from app.integrations.lbx.reconciliation import _timely_point
from app.models import (
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
)


def inspect_readback(
    subject: ReadbackSubject,
    *,
    user: LbxUser | None,
    agreement: Agreement | None,
    subscription: Subscription | None,
    window: tuple[datetime, datetime],
    reads: tuple[str, ...],
    provider_subscription_id: str | None = None,
) -> ScopedReadbackFinding:
    reasons: list[str] = []
    if (
        user is None
        or user.outer_id != subject.customer.outer_key
        or agreement is None
        or (agreement.user_id, agreement.organization_id, agreement.agreement_number)
        != (int(subject.customer.provider_id), subject.purchase.accepted.seller_id, subject.agreement_key)
        or (subscription is not None and subscription.agreement_id != int(subject.agreement_id))
    ):
        return ScopedReadbackFinding(subject, None, ("ownership_incomplete_or_conflicting",))
    commercial = CommercialProof.INCOMPLETE
    if subscription is not None:
        material = inspect_effective_terms(
            subscription, selection=subject.purchase.accepted.selection, offer=subject.purchase.accepted.offer
        )
        if material.incomplete_fields:
            reasons.append("effective_terms_incomplete")
        if material.differing_fields:
            reasons.append("effective_terms_mismatch")
    else:
        reasons.append("effective_terms_incomplete")
    if agreement.is_offer is None:
        reasons.append("agreement_policy_incomplete")
    elif agreement.is_offer:
        reasons.append("agreement_policy_mismatch")
    # This narrow read set carries no applicable tariff policy proof. It must
    # never assert complete commercial or positive calendar verification.
    reasons.append("tariff_policy_incomplete")
    lifecycle, basis = None, NegativeBasis.SUBSCRIPTION
    if subscription is not None:
        state = classify_lifecycle(subscription)
        reasons.append(state.reason)
        if state.financial == Financial.BLOCKED:
            lifecycle = state.lifecycle
    try:
        closed = agreement_closed(agreement)
    except LbxResponseInvalid:
        reasons.append("agreement_calendar_incomplete")
    else:
        if closed:
            lifecycle, basis = Lifecycle.ENDED, NegativeBasis.AGREEMENT
            reasons.append("agreement_closed")
    if lifecycle is None:
        return ScopedReadbackFinding(subject, None, tuple(reasons), provider_subscription_id)
    provider_id = (
        subject.provider_subscription_id if isinstance(subject, BoundReadbackSubject) else provider_subscription_id
    )
    if provider_id is None:
        return ScopedReadbackFinding(subject, None, tuple(reasons))
    negative = BoundSourceNegative(
        subject.agreement_id, provider_id, basis, lifecycle, window[0], window[1], reads, tuple(reasons), commercial
    )
    return ScopedReadbackFinding(subject, negative, candidate_id=provider_subscription_id)


async def read_bound_finding(
    client: LbxServerClient,
    subject: BoundReadbackSubject,
    *,
    budget: PreflightBudget,
) -> ScopedReadbackFinding:
    started = utc_now()
    user, agreement, subscription = None, None, None
    reads: list[str] = []
    failures: list[str] = []
    try:
        user = await _timely_point(client.get_user(user_id=int(subject.customer.provider_id), budget=budget), budget)
        reads.append("customer")
    except (LbxError, PreflightDeadlineExceeded) as error:
        failures.append("customer:" + error.code)
    try:
        agreement = await _timely_point(
            client.get_agreement(agreement_id=int(subject.agreement_id), budget=budget), budget
        )
        reads.append("agreement")
    except (LbxError, PreflightDeadlineExceeded) as error:
        failures.append("agreement:" + error.code)
    try:
        subscription = await _timely_point(
            client.get_subscription(subscription_id=int(subject.provider_subscription_id), budget=budget), budget
        )
        reads.append("subscription")
    except (LbxError, PreflightDeadlineExceeded) as error:
        failures.append("subscription:" + error.code)
    finding = inspect_readback(
        subject,
        user=user,
        agreement=agreement,
        subscription=subscription,
        window=(started, utc_now()),
        reads=tuple(reads),
    )
    return replace(finding, reasons=finding.reasons + tuple(failures))


async def read_original_create_proof(
    client: LbxServerClient,
    subject: OriginalCreateReadbackSubject,
    *,
    budget: PreflightBudget,
) -> OriginalCreateProof:
    started = utc_now()
    user = await _timely_point(client.get_user(user_id=int(subject.customer.provider_id), budget=budget), budget)
    agreement = await _timely_point(client.get_agreement(agreement_id=int(subject.agreement_id), budget=budget), budget)
    rows = await _timely_point(
        client.discover_subscriptions(
            user_id=int(subject.customer.provider_id), agreement_id=int(subject.agreement_id), budget=budget
        ),
        budget,
    )
    if len(rows) != 1 or subject.operation.candidate_id not in {None, str(rows[0].subscription_id)}:
        raise LbxResponseInvalid()
    provider_id = rows[0].subscription_id
    point = await _timely_point(client.get_subscription(subscription_id=provider_id, budget=budget), budget)
    if user.outer_id != subject.customer.outer_key:
        raise LbxScopeMismatch()
    accepted = subject.purchase.accepted
    prove_agreement(
        agreement,
        user_id=int(subject.customer.provider_id),
        seller_id=accepted.seller_id,
        number=subject.agreement_key,
    )
    prove_subscription(
        point,
        agreement_id=int(subject.agreement_id),
        selection=accepted.selection,
        offer=accepted.offer,
    )
    command = NewSubscription(
        agreement_id=int(subject.agreement_id),
        tariff_id=accepted.selection.tariff_id,
        period_id=accepted.selection.period_id,
        tariff_service_id=accepted.selection.tariff_service_id,
        quantity=accepted.selection.quantity,
        outer_id=subject.operation.key,
    ).request_document()
    if command != subject.saved_command:
        raise LbxScopeMismatch()
    finished = utc_now()
    reads = ("customer", "agreement", "subscription", "unique_candidate", "effective_terms")
    finding = inspect_readback(
        subject,
        user=user,
        agreement=agreement,
        subscription=point,
        window=(started, finished),
        reads=reads,
        provider_subscription_id=str(provider_id),
    )
    return OriginalCreateProof(
        str(provider_id), subject.agreement_id, command, started, finished, reads, finding.negative
    )
