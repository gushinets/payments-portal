"""One bounded point-read set; only this boundary interprets LBX lifecycle codes."""

from dataclasses import replace
from datetime import date, datetime
from collections.abc import Awaitable

from app.core.settings import Settings
from app.core.time import utc_now
from app.domains.billing.reconciliation_contracts import (
    CommercialProof,
    IdentityProof,
    ReconciliationSubject,
    SubscriptionCandidateSubject,
    SubscriptionProof,
)
from app.domains.catalog.product_link import CurrentOffer
from app.infrastructure.preflight import PreflightBudget, PreflightDeadlineExceeded
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.customer import LbxUser
from app.integrations.lbx.dto import LbxRead, LbxTariff
from app.integrations.lbx.errors import LbxError, LbxResponseInvalid, LbxScopeMismatch
from app.integrations.lbx.financial import (
    Agreement,
    MaterialInspection,
    Subscription,
    agreement_closed,
    classify_lifecycle,
    inspect_effective_terms,
)
from app.integrations.lbx.selected_offer import PERIOD_ANCHORS
from app.models import (
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
)

CALENDAR_FIELDS = (
    "subscription_start_date",
    "subscription_end_date",
    "subscription_instance_start_date",
    "subscription_instance_end_date",
    "last_tariffication_period_start",
    "last_tariffication_period_end",
)
EMPTY_CALENDAR = {None, "", "0000-00-00", "0000-00-00 00:00:00", "1970-01-01", "1970-01-01 00:00:00"}


def _calendar_ordered(left: date | datetime, right: date | datetime, *, strict: bool = False) -> bool:
    if type(left) is type(right):
        return left < right if strict else left <= right
    left_day = left.date() if isinstance(left, datetime) else left
    right_day = right.date() if isinstance(right, datetime) else right
    # A date carries no time. Different days prove order without inventing a
    # timezone or midnight; a shared day at mixed precision proves neither.
    return left_day < right_day


def _calendar_complete(calendar: dict[str, str | None]) -> bool:
    """Calendar evidence only: no UTC conversion, settlement or cycle identity."""
    parsed: dict[str, date | datetime] = {}
    try:
        for key, value in calendar.items():
            if value not in EMPTY_CALENDAR:
                parsed[key] = date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value)
    except ValueError:
        return False
    for prefix in ("subscription", "subscription_instance", "last_tariffication_period"):
        start, end = parsed.get(prefix + "_start_date"), parsed.get(prefix + "_end_date")
        if prefix == "last_tariffication_period":
            start, end = parsed.get(prefix + "_start"), parsed.get(prefix + "_end")
            if start is None or end is None:
                return False
        if start is not None and end is not None and not _calendar_ordered(start, end, strict=True):
            return False
    cycle_start = parsed["last_tariffication_period_start"]
    cycle_end = parsed["last_tariffication_period_end"]
    for prefix in ("subscription", "subscription_instance"):
        start, end = parsed.get(prefix + "_start_date"), parsed.get(prefix + "_end_date")
        if (start and not _calendar_ordered(start, cycle_start)) or (end and not _calendar_ordered(cycle_end, end)):
            return False
    return True


def _inspect_policy(policy: LbxTariff, configuration: Settings, offer: CurrentOffer) -> MaterialInspection:
    incomplete: list[str] = []
    differences: list[str] = []
    for field, expected, recognized in (
        ("payment_type", 0, {0, 1}),
        ("balance_blocks", 1, {0, 1}),
        ("dynamic_rent", 0, {0, 1, 2}),
        ("dynamic_rent_unblock_type", 0, {0, 1}),
        ("demo_period_length", 0, None),
        ("proportional_rent", 0, {0, 1}),
    ):
        value = getattr(policy, field)
        if value is None or (recognized is not None and value not in recognized):
            incomplete.append(field)
        elif value != expected:
            differences.append(field)
    if policy.float_period not in PERIOD_ANCHORS:
        incomplete.append("float_period")
    elif PERIOD_ANCHORS[policy.float_period] != offer.period.anchor:
        differences.append("float_period")
    mapping = configuration.lbx_currency_mapping
    if mapping is None or policy.currency_id != mapping.provider_currency_id:
        # A changed numeric ID has no ISO meaning without a matching mapping.
        incomplete.append("currency_mapping")
    else:
        if mapping.iso_currency != offer.money.currency:
            differences.append("currency")
        if mapping.scale != offer.money.decimal_places:
            differences.append("decimal_places")
    return MaterialInspection(tuple(incomplete), tuple(differences))


def normalize_subscription(
    subject: ReconciliationSubject | SubscriptionCandidateSubject,
    configuration: Settings,
    *,
    user: LbxUser | None,
    agreement: Agreement | None,
    tariff: LbxRead[LbxTariff] | None,
    subscription: Subscription | None,
) -> SubscriptionProof:
    """Independent identity, commercial, lifecycle and calendar conclusions."""
    now = utc_now()
    reasons: list[str] = []
    identity = IdentityProof.INCOMPLETE
    pairs: list[tuple[object, object]] = []
    if user is not None:
        pairs.extend(((user.user_id, int(subject.customer.provider_id)), (user.outer_id, subject.customer.outer_key)))
    if agreement is not None:
        pairs.extend(
            (
                (agreement.agreement_id, int(subject.agreement_id)),
                (agreement.user_id, int(subject.customer.provider_id)),
                (agreement.agreement_number, subject.agreement_key),
                (agreement.organization_id, subject.purchase.accepted.seller_id),
            )
        )
    if subscription is not None:
        pairs.extend(
            (
                (subscription.subscription_id, int(subject.provider_subscription_id)),
                (subscription.agreement_id, int(subject.agreement_id)),
            )
        )
    if pairs:
        # A known contradiction remains decisive even if a different field is absent.
        if any(value is not None and value != wanted for value, wanted in pairs):
            identity = IdentityProof.CONFLICT
            customer_conflict = user is not None and (
                user.user_id != int(subject.customer.provider_id)
                or (user.outer_id is not None and user.outer_id != subject.customer.outer_key)
            )
            reasons.append("customer_identity_conflict" if customer_conflict else "subscription_identity_conflict")
            if customer_conflict and user.user_id == int(subject.customer.provider_id):
                reasons.append("customer_original_key_mismatch")
            if any(value is not None and value != wanted for value, wanted in pairs[2 if user else 0 :]):
                reasons.append("subscription_identity_conflict")
        elif len(pairs) == 8 and all(value is not None for value, _ in pairs):
            identity = IdentityProof.MATCH
    if identity == IdentityProof.INCOMPLETE:
        reasons.append("ownership_incomplete")

    accepted = subject.purchase.accepted
    terms = (
        inspect_effective_terms(subscription, selection=accepted.selection, offer=accepted.offer)
        if subscription is not None
        else MaterialInspection(("subscription",), ())
    )
    # Applicable policy, not current sale visibility, catalog prices or membership.
    if tariff is None:
        policy = MaterialInspection(("tariff",), ())
    elif (
        # LbxRead carries the configured HTTP origin identity, whereas the
        # purchase may retain a separately proven historical storage scope.
        tariff.external_billing_account_id != configuration.lbx_external_billing_account_id
        or accepted.provider_origin != configuration.lbx_provider_origin
        or tariff.tariff_id != accepted.selection.tariff_id
        or tariff.value.tariff_id != accepted.selection.tariff_id
        or tariff.observed_at.utcoffset() is None
    ):
        policy = MaterialInspection(("provenance",), ())
        # Contradictory source scope cannot establish this canonical subject,
        # including for a negative conclusion. An unavailable policy read is
        # different: the other owned point reads can still prove a block/end.
        if identity != IdentityProof.CONFLICT:
            identity = IdentityProof.INCOMPLETE
        reasons.append("tariff_provenance_conflict")
    else:
        policy = _inspect_policy(tariff.value, configuration, accepted.offer)
    agreement_policy = MaterialInspection(
        ("is_offer",) if agreement is None or agreement.is_offer is None else (),
        ("is_offer",) if agreement is not None and agreement.is_offer else (),
    )
    inspections = (
        (terms, "effective_terms_incomplete", "effective_terms_mismatch"),
        (policy, "tariff_policy_incomplete", "unsupported_prepaid_policy"),
        (agreement_policy, "agreement_policy_incomplete", "agreement_policy_mismatch"),
    )
    for inspection, incomplete_reason, difference_reason in inspections:
        if inspection.incomplete_fields:
            reasons.append(incomplete_reason)
        if inspection.differing_fields:
            reasons.append(difference_reason)
    commercial = (
        CommercialProof.INCOMPLETE
        if any(inspection.incomplete_fields for inspection, _, _ in inspections)
        else CommercialProof.MISMATCH
        if any(inspection.differing_fields for inspection, _, _ in inspections)
        else CommercialProof.MATCH
    )

    lifecycle, financial = None, None
    calendar = {field: getattr(subscription, field) for field in CALENDAR_FIELDS} if subscription else {}
    calendar_complete = bool(calendar) and _calendar_complete(calendar)
    agreement_calendar_complete = True
    lifecycle_complete = False
    if identity == IdentityProof.MATCH:
        state = classify_lifecycle(subscription)
        lifecycle_complete = state.lifecycle is not None
        lifecycle, financial = state.lifecycle, state.financial
        reasons.append(state.reason)
        try:
            closed = agreement_closed(agreement)
        except LbxResponseInvalid:
            reasons.append("agreement_calendar_incomplete")
            agreement_calendar_complete = False
            if financial != Financial.BLOCKED:
                lifecycle, financial = None, None
        else:
            if closed:
                lifecycle, financial = Lifecycle.ENDED, Financial.BLOCKED
                calendar["agreement_close_date"] = agreement.close_date
                reasons.append("agreement_closed")
    positive = financial == Financial.ALLOWED
    if positive and not calendar_complete:
        financial = None
        reasons.append("current_calendar_incomplete")
    if positive and commercial == CommercialProof.INCOMPLETE:
        financial = None
    complete = (
        identity == IdentityProof.MATCH
        and commercial != CommercialProof.INCOMPLETE
        and lifecycle_complete
        and lifecycle is not None
        and financial is not None
        and agreement_calendar_complete
    )
    return SubscriptionProof(
        now, now, identity, commercial, lifecycle, financial, calendar, calendar_complete, complete, tuple(reasons), ()
    )


async def _timely_point[T](read: Awaitable[T], budget: PreflightBudget) -> T:
    """Reject both values and scope errors returned after the read deadline."""
    try:
        value = await read
    except LbxError:
        budget.check()
        raise
    budget.check()
    return value


async def read_subscription_details(
    client: LbxServerClient,
    subject: ReconciliationSubject | SubscriptionCandidateSubject,
    configuration: Settings,
    *,
    budget: PreflightBudget,
) -> tuple[SubscriptionProof, Subscription | None]:
    started = utc_now()
    user, agreement, tariff, subscription = None, None, None, None
    reads: list[str] = []
    failures: list[str] = []
    # Customer pair; canonical agreement/seller/correlation; prepaid policy;
    # effective terms and latest lifecycle. No discovery/current-offer round.
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
        tariff = await _timely_point(
            client.get_tariff(tariff_id=subject.purchase.accepted.selection.tariff_id, budget=budget), budget
        )
        reads.append("tariff_policy")
    except (LbxError, PreflightDeadlineExceeded) as error:
        failures.append("tariff:" + error.code)
    try:
        subscription = await _timely_point(
            client.get_subscription(subscription_id=int(subject.provider_subscription_id), budget=budget), budget
        )
        reads.append("subscription")
    except (LbxError, PreflightDeadlineExceeded) as error:
        failures.append("subscription:" + error.code)
    proof = normalize_subscription(
        subject, configuration, user=user, agreement=agreement, tariff=tariff, subscription=subscription
    )
    if any(
        failure.endswith(":" + LbxScopeMismatch().code)
        for failure in failures
        if failure.split(":", 1)[0] in {"customer", "agreement", "subscription"}
    ):
        conflicts = tuple(
            "customer_identity_conflict" if failure.startswith("customer:") else "subscription_identity_conflict"
            for failure in failures
            if failure.endswith(":" + LbxScopeMismatch().code) and not failure.startswith("tariff:")
        )
        proof = replace(
            proof, identity=IdentityProof.CONFLICT, lifecycle=None, financial=None, reasons=proof.reasons + conflicts
        )
    try:
        budget.check()
    except PreflightDeadlineExceeded:
        failures.append("read_budget_exhausted")
    result = replace(
        proof,
        read_started_at=started,
        read_finished_at=utc_now(),
        reads=tuple(reads),
        complete=proof.complete and not failures,
        reasons=proof.reasons + tuple(failures),
    )
    return result, subscription


async def read_subscription_proof(
    client: LbxServerClient,
    subject: ReconciliationSubject | SubscriptionCandidateSubject,
    configuration: Settings,
    *,
    budget: PreflightBudget,
) -> SubscriptionProof:
    proof, _ = await read_subscription_details(client, subject, configuration, budget=budget)
    return proof
