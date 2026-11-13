"""One bounded point-read set; only this boundary interprets LBX lifecycle codes."""

from dataclasses import replace
from datetime import date, datetime
from collections.abc import Awaitable, Callable

from app.core.settings import Settings
from app.core.time import utc_now
from app.domains.billing.paid_cycles import CalendarEvidence, CalendarPrecision
from app.domains.billing.reconciliation_contracts import (
    CommercialProof,
    IdentityProof,
    ReconciliationSubject,
    SubscriptionCandidateSubject,
    SubscriptionProof,
    SubscriptionRelationship,
)
from app.infrastructure.preflight import PreflightBudget, PreflightDeadlineExceeded
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.calendar import normalize_access_end, normalize_calendar
from app.integrations.lbx.customer import LbxUser
from app.integrations.lbx.dto import LbxRead, LbxTariff
from app.integrations.lbx.errors import (
    LbxAuthenticationFailed,
    LbxError,
    LbxResponseInvalid,
    LbxScopeForbidden,
    LbxScopeMismatch,
)
from app.integrations.lbx.financial import (
    EMPTY_CALENDAR,
    Agreement,
    Subscription,
    agreement_is_closed,
    prove_effective_terms,
    subscription_lifecycle,
)
from app.integrations.lbx.selected_offer import PERIOD_ANCHORS
from app.models import (
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
)

MAX_RELEVANT_SUBSCRIPTIONS = 20

CALENDAR_FIELDS = (
    "subscription_start_date",
    "subscription_end_date",
    "subscription_instance_start_date",
    "subscription_instance_end_date",
    "last_tariffication_period_start",
    "last_tariffication_period_end",
)


def _calendar_ordered(left: date | datetime, right: date | datetime, *, strict: bool = False) -> bool:
    if type(left) is type(right):
        if isinstance(left, datetime) and isinstance(right, datetime):
            if (left.utcoffset() is None) != (right.utcoffset() is None):
                return False
        return left < right if strict else left <= right
    left_day = left.date() if isinstance(left, datetime) else left
    right_day = right.date() if isinstance(right, datetime) else right
    # A date carries no time. Different days prove order without inventing a
    # timezone or midnight; a shared day at mixed precision proves neither.
    return left_day < right_day


def _calendar_complete(calendar: dict[str, str | None], *, anchor_kind: str, cycle: CalendarEvidence | None) -> bool:
    """Check containment in the normalized frame, without deciding cycle identity."""
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
        if (
            start is not None
            and end is not None
            and not _calendar_ordered(start, end, strict=isinstance(start, datetime) or isinstance(end, datetime))
        ):
            return False
    cycle_start = parsed["last_tariffication_period_start"]
    cycle_end = parsed["last_tariffication_period_end"]
    month_anchor = (
        datetime.fromisoformat(cycle.anchor)
        if anchor_kind == "calendar_month"
        and cycle is not None
        and cycle.precision == CalendarPrecision.TIMESTAMP
        and cycle.anchor is not None
        else None
    )
    for prefix in ("subscription", "subscription_instance"):
        start, end = parsed.get(prefix + "_start_date"), parsed.get(prefix + "_end_date")
        if (
            month_anchor is not None
            and isinstance(start, datetime)
            and start.utcoffset() is not None
            and cycle_start == month_anchor
            and start.astimezone(month_anchor.tzinfo).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            == month_anchor
        ):
            # Only the proven first-day boundary may precede activation. The
            # normalizer supplies the same explicit offset as issued history.
            start = month_anchor
        # Calendar dates may straddle activation/termination. Only explicit
        # timestamps support a more precise containment check.
        if (
            start
            and (isinstance(start, datetime) or isinstance(cycle_start, datetime))
            and not _calendar_ordered(start, cycle_start)
        ) or (
            end
            and (isinstance(end, datetime) or isinstance(cycle_end, datetime))
            and not _calendar_ordered(cycle_end, end)
        ):
            return False
    return True


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
    closed = False
    agreement_calendar_complete = True
    if agreement is not None:
        try:
            closed = agreement_is_closed(agreement)
        except LbxResponseInvalid:
            agreement_calendar_complete = False
            reasons.append("agreement_calendar_incomplete")
    # Authenticated point URLs select canonical resources. Retain original-key,
    # owner, seller and relationship proof; do not compare returned self-IDs.
    customer_pairs = [(user.outer_id, subject.customer.outer_key)] if user is not None else []
    relationship_pairs: list[tuple[object, object]] = []
    if agreement is not None:
        relationship_pairs.extend(
            (
                (agreement.user_id, int(subject.customer.provider_id)),
                (agreement.agreement_number, subject.agreement_key),
                (agreement.organization_id, subject.purchase.accepted.seller_id),
            )
        )
    if subscription is not None:
        relationship_pairs.append((subscription.agreement_id, int(subject.agreement_id)))
    pairs = customer_pairs + relationship_pairs
    if any(value is not None and value != wanted for value, wanted in pairs):
        identity = IdentityProof.CONFLICT
        if any(value is not None and value != wanted for value, wanted in customer_pairs):
            reasons.extend(("customer_identity_conflict", "customer_original_key_mismatch"))
        if any(value is not None and value != wanted for value, wanted in relationship_pairs):
            reasons.append("subscription_identity_conflict")
    elif all(value is not None for value, _ in pairs) and (
        len(pairs) == 5
        or (len(pairs) == 4 and subscription is None and isinstance(subject, ReconciliationSubject) and closed)
    ):
        # A retained canonical binding plus complete customer/agreement owner
        # proof suffices only for an agreement-based negative, never first bind.
        identity = IdentityProof.MATCH
    if identity == IdentityProof.INCOMPLETE:
        reasons.append("ownership_incomplete")

    commercial = CommercialProof.INCOMPLETE
    accepted = subject.purchase.accepted
    if subscription is not None and identity != IdentityProof.CONFLICT:
        try:
            prove_effective_terms(
                subscription, agreement_id=int(subject.agreement_id), selection=accepted.selection, offer=accepted.offer
            )
        except LbxResponseInvalid:
            reasons.append("effective_terms_incomplete")
        except LbxScopeMismatch:
            commercial = CommercialProof.MISMATCH
            reasons.append("effective_terms_mismatch")
        else:
            commercial = CommercialProof.MATCH
    terms_incomplete = commercial == CommercialProof.INCOMPLETE
    # Applicable policy, not current sale visibility, catalog prices or membership.
    policy_incomplete = False
    if tariff is None:
        policy_incomplete = True
        reasons.append("tariff_policy_incomplete")
    elif (
        # LbxRead carries the configured HTTP origin identity, whereas the
        # purchase may retain a separately proven historical storage scope.
        tariff.external_billing_account_id != configuration.lbx_external_billing_account_id
        or accepted.provider_origin != configuration.lbx_provider_origin
        or tariff.tariff_id != accepted.selection.tariff_id
        or tariff.observed_at.utcoffset() is None
    ):
        policy_incomplete = True
        # Contradictory source scope cannot establish this canonical subject,
        # including for a negative conclusion. An unavailable policy read is
        # different: the other owned point reads can still prove a block/end.
        if identity != IdentityProof.CONFLICT:
            identity = IdentityProof.INCOMPLETE
        reasons.append("tariff_provenance_conflict")
    else:
        policy = tariff.value
        flags = {
            "payment_type": 0,
            "balance_blocks": 1,
            "dynamic_rent": 0,
            "dynamic_rent_unblock_type": 0,
            "demo_period_length": 0,
            "proportional_rent": 0,
        }
        mapping = configuration.lbx_currency_mapping
        if (
            any(getattr(policy, field) is None for field in (*flags, "currency_id", "float_period"))
            or any(
                getattr(policy, field) not in {0, 1}
                for field in ("payment_type", "balance_blocks", "dynamic_rent_unblock_type", "proportional_rent")
            )
            or policy.dynamic_rent not in {0, 1, 2}
            or policy.float_period not in PERIOD_ANCHORS
        ):
            policy_incomplete = True
            reasons.append("tariff_policy_incomplete")
        elif mapping is None:
            policy_incomplete = True
            reasons.append("currency_interpretation_incomplete")
        elif (
            any(getattr(policy, field) != value for field, value in flags.items())
            or policy.currency_id != mapping.provider_currency_id
            or mapping.iso_currency != accepted.offer.money.currency
            or mapping.scale != accepted.offer.money.decimal_places
            or PERIOD_ANCHORS.get(policy.float_period) != accepted.offer.period.anchor
        ):
            commercial = CommercialProof.MISMATCH
            reasons.append("unsupported_prepaid_policy")
    if agreement is None or agreement.is_offer is None:
        policy_incomplete = True
        reasons.append("agreement_policy_incomplete")
    elif agreement.is_offer:
        commercial = CommercialProof.MISMATCH
        reasons.append("agreement_policy_mismatch")
    if policy_incomplete or terms_incomplete:
        commercial = CommercialProof.INCOMPLETE

    lifecycle, financial = None, None
    calendar = {field: getattr(subscription, field) for field in CALENDAR_FIELDS} if subscription else {}
    cycle = normalize_calendar(
        calendar,
        accepted.offer.period.anchor,
        established_calendar=subject.established_calendar if isinstance(subject, ReconciliationSubject) else None,
    )
    calendar_complete = bool(calendar) and _calendar_complete(
        calendar, anchor_kind=accepted.offer.period.anchor, cycle=cycle
    )
    if identity == IdentityProof.MATCH:
        if subscription is not None:
            try:
                lifecycle, financial, reason = subscription_lifecycle(subscription)
            except LbxResponseInvalid:
                reasons.append("lifecycle_unknown")
            else:
                reasons.append(reason)
        if closed:
            lifecycle, financial = Lifecycle.ENDED, Financial.BLOCKED
            calendar["agreement_close_date"] = agreement.close_date
            reasons.append("agreement_closed")
        elif not agreement_calendar_complete and financial != Financial.BLOCKED:
            lifecycle, financial = None, None
    positive = financial == Financial.ALLOWED
    if positive and not calendar_complete:
        reasons.append("current_calendar_incomplete")
    if positive and commercial == CommercialProof.INCOMPLETE:
        financial = None
    complete = (
        identity == IdentityProof.MATCH
        and commercial != CommercialProof.INCOMPLETE
        and lifecycle is not None
        and financial is not None
        and agreement_calendar_complete
    )
    return SubscriptionProof(
        now,
        now,
        identity,
        commercial,
        lifecycle,
        financial,
        calendar,
        calendar_complete,
        complete,
        tuple(reasons),
        (),
        cycle=cycle if calendar_complete else None,
        access_end_at=normalize_access_end(calendar.get("subscription_end_date")),
        point_relationship=SubscriptionRelationship(str(subscription.agreement_id), subscription.tariff_id)
        if subscription is not None
        else None,
    )


async def timely_point[T](read: Callable[[], Awaitable[T]], budget: PreflightBudget) -> T:
    """Reject both values and scope errors returned after the read deadline."""
    budget.check()
    try:
        value = await read()
    except LbxError:
        budget.check()
        raise
    budget.check()
    return value


def source_scope_unproven(proof: SubscriptionProof) -> bool:
    """Recognize retained read failures at the owner of their diagnostic encoding."""
    codes = {LbxAuthenticationFailed().code, LbxScopeForbidden().code}
    return any(reason.rsplit(":", 1)[-1] in codes for reason in proof.reasons)


async def _agreement_has_competitor(
    client: LbxServerClient, subject: ReconciliationSubject | SubscriptionCandidateSubject, budget: PreflightBudget
) -> bool:
    """Prove payment isolation using the same lifecycle rules as inventory."""
    agreement_id = int(subject.agreement_id)

    async def discover() -> tuple[Subscription, ...]:
        return await client.discover_subscriptions(
            user_id=int(subject.customer.provider_id), agreement_id=agreement_id, budget=budget
        )

    rows = await timely_point(discover, budget)
    if len(rows) > MAX_RELEVANT_SUBSCRIPTIONS:
        raise LbxResponseInvalid()
    for candidate in rows:
        if str(candidate.subscription_id) == subject.provider_subscription_id:
            continue
        point = await timely_point(
            lambda: client.get_subscription(subscription_id=candidate.subscription_id, budget=budget), budget
        )
        if (point.agreement_id, point.tariff_id) != (agreement_id, candidate.tariff_id):
            raise LbxResponseInvalid()
        if subscription_lifecycle(point)[0] != Lifecycle.ENDED:
            return True
    again = await timely_point(discover, budget)
    if sorted((row.subscription_id, row.tariff_id) for row in rows) != sorted(
        (row.subscription_id, row.tariff_id) for row in again
    ):
        raise LbxResponseInvalid()
    return False


async def read_subscription_proof(
    client: LbxServerClient,
    subject: ReconciliationSubject | SubscriptionCandidateSubject,
    configuration: Settings,
    *,
    budget: PreflightBudget,
    check_agreement_inventory: bool = False,
) -> SubscriptionProof:
    started = utc_now()
    user, agreement, tariff, subscription = None, None, None, None
    reads: list[str] = []
    failures: list[str] = []
    # Read owner and lifecycle before potentially slow policy. Timely negatives
    # survive an unavailable policy, while every late point result is rejected.
    try:
        user = await timely_point(
            lambda: client.get_user(user_id=int(subject.customer.provider_id), budget=budget), budget
        )
        reads.append("customer")
    except (LbxError, PreflightDeadlineExceeded) as error:
        failures.append("customer:" + error.code)
    try:
        agreement = await timely_point(
            lambda: client.get_agreement(agreement_id=int(subject.agreement_id), budget=budget), budget
        )
        reads.append("agreement")
    except (LbxError, PreflightDeadlineExceeded) as error:
        failures.append("agreement:" + error.code)
    try:
        subscription = await timely_point(
            lambda: client.get_subscription(subscription_id=int(subject.provider_subscription_id), budget=budget),
            budget,
        )
        reads.append("subscription")
    except (LbxError, PreflightDeadlineExceeded) as error:
        failures.append("subscription:" + error.code)
    try:
        tariff = await timely_point(
            lambda: client.get_tariff(tariff_id=subject.purchase.accepted.selection.tariff_id, budget=budget), budget
        )
        reads.append("tariff_policy")
    except (LbxError, PreflightDeadlineExceeded) as error:
        failures.append("tariff:" + error.code)
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
    if (
        check_agreement_inventory
        and proof.identity == IdentityProof.MATCH
        and proof.commercial == CommercialProof.MATCH
        and proof.lifecycle in {Lifecycle.ACTIVE, Lifecycle.INACTIVE}
    ):
        try:
            competing = await _agreement_has_competitor(client, subject, budget)
        except (LbxError, PreflightDeadlineExceeded) as error:
            failures.extend(("agreement_inventory_incomplete", "agreement_inventory:" + error.code))
        else:
            reads.append("agreement_inventory")
            if competing:
                proof = replace(
                    proof,
                    identity=IdentityProof.CONFLICT,
                    complete=False,
                    reasons=proof.reasons + ("subscription_identity_conflict", "dedicated_agreement_conflict"),
                )
    try:
        budget.check()
    except PreflightDeadlineExceeded:
        failures.append("read_budget_exhausted")
    return replace(
        proof,
        read_started_at=started,
        read_finished_at=utc_now(),
        reads=tuple(reads),
        complete=proof.complete and not failures,
        reasons=proof.reasons + tuple(failures),
    )
