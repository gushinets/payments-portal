"""One bounded point-read set; only this boundary interprets LBX lifecycle codes."""

from dataclasses import replace
from datetime import date, datetime
from collections.abc import Awaitable, Callable

from app.core.settings import Settings
from app.core.time import utc_now
from app.domains.billing.reconciliation_contracts import (
    CommercialProof,
    IdentityProof,
    ReconciliationSubject,
    SubscriptionCandidateSubject,
    SubscriptionProof,
)
from app.infrastructure.preflight import PreflightBudget, PreflightDeadlineExceeded
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.customer import LbxUser
from app.integrations.lbx.dto import LbxRead, LbxTariff
from app.integrations.lbx.errors import LbxError, LbxResponseInvalid, LbxScopeMismatch
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
    calendar_complete = bool(calendar) and _calendar_complete(calendar)
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
        financial = None
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
        now, now, identity, commercial, lifecycle, financial, calendar, calendar_complete, complete, tuple(reasons), ()
    )


async def _timely_point[T](read: Callable[[], Awaitable[T]], budget: PreflightBudget) -> T:
    """Reject both values and scope errors returned after the read deadline."""
    budget.check()
    try:
        value = await read()
    except LbxError:
        budget.check()
        raise
    budget.check()
    return value


async def read_subscription_proof(
    client: LbxServerClient,
    subject: ReconciliationSubject | SubscriptionCandidateSubject,
    configuration: Settings,
    *,
    budget: PreflightBudget,
) -> SubscriptionProof:
    started = utc_now()
    user, agreement, tariff, subscription = None, None, None, None
    reads: list[str] = []
    failures: list[str] = []
    # Read owner and lifecycle before potentially slow policy. Timely negatives
    # survive an unavailable policy, while every late point result is rejected.
    try:
        user = await _timely_point(
            lambda: client.get_user(user_id=int(subject.customer.provider_id), budget=budget), budget
        )
        reads.append("customer")
    except (LbxError, PreflightDeadlineExceeded) as error:
        failures.append("customer:" + error.code)
    try:
        agreement = await _timely_point(
            lambda: client.get_agreement(agreement_id=int(subject.agreement_id), budget=budget), budget
        )
        reads.append("agreement")
    except (LbxError, PreflightDeadlineExceeded) as error:
        failures.append("agreement:" + error.code)
    try:
        subscription = await _timely_point(
            lambda: client.get_subscription(subscription_id=int(subject.provider_subscription_id), budget=budget),
            budget,
        )
        reads.append("subscription")
    except (LbxError, PreflightDeadlineExceeded) as error:
        failures.append("subscription:" + error.code)
    try:
        tariff = await _timely_point(
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
