"""SIMULATED lifecycle/term proof; these tests never call real LBX."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.domains.billing.reconciliation_contracts import (
    CommercialProof,
    IdentityProof,
    RECONCILIATION_SCHEMA,
    SubscriptionCandidateSubject,
)
from app.integrations.lbx.financial import (
    Subscription,
    prove_agreement,
    prove_subscription,
    require_preparable_agreement,
    require_payable_subscription,
)
from app.integrations.lbx.errors import LbxScopeMismatch, LbxResponseInvalid
from app.infrastructure.preflight import PreflightAdmission, PreflightPolicy
from app.integrations.lbx.reconciliation import normalize_subscription, read_subscription_proof
from apps.api.tests.factories.reconciliation import (
    subject_factory,
    user_factory,
    agreement_factory,
    tariff_factory,
    subscription_factory,
)
from apps.api.tests.support.any709_step1 import step1_settings


@pytest.mark.parametrize(
    "state,block,lifecycle,financial,reason",
    [
        (-2, 0, "inactive", "blocked", "waiting"),
        (-1, 0, "inactive", "blocked", "inactive"),
        (0, 0, "inactive", "blocked", "inactive"),
        (2, 0, "active", "allowed", "active"),
        (2, 1, "active", "blocked", "financial_block"),
        (2, 3, "active", "blocked", "administrative_block"),
        (3, 0, "ended", "blocked", "ended"),
        (3, 1, "ended", "blocked", "ended"),
        (3, 3, "ended", "blocked", "ended"),
    ],
)
def test_billing_subscription_reconciliation_lifecycle(
    state: int, block: int, lifecycle: str, financial: str, reason: str
) -> None:
    subject = subject_factory()
    point = subscription_factory().model_copy(update={"state": state, "current_blocking": block})
    if state == -2:
        point = point.model_copy(
            update={"last_tariffication_period_start": None, "last_tariffication_period_end": None}
        )
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=point,
    )
    assert proof.complete and proof.commercial == CommercialProof.MATCH
    assert (proof.lifecycle, proof.financial) == (lifecycle, financial)
    assert reason in proof.reasons


@pytest.mark.parametrize(
    "change,classification",
    [
        ({"total_price": None}, CommercialProof.INCOMPLETE),
        ({"services": None}, CommercialProof.INCOMPLETE),
        ({"currency_symbol": None}, CommercialProof.INCOMPLETE),
        ({"services": []}, CommercialProof.MISMATCH),
        ({"currency_symbol": "USD"}, CommercialProof.MISMATCH),
        ({"period_length": 2}, CommercialProof.MISMATCH),
        ({"tariff_id": 702}, CommercialProof.MISMATCH),
    ],
)
def test_billing_subscription_reconciliation_commercial(change: dict, classification: CommercialProof) -> None:
    subject = subject_factory()
    point = subscription_factory().model_copy(update=change)
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=point,
    )
    assert proof.commercial == classification
    assert proof.identity == IdentityProof.MATCH


@pytest.mark.parametrize("same_origin", [False, True])
def test_billing_subscription_reconciliation_retained_storage_scope_requires_current_origin(same_origin: bool) -> None:
    subject = subject_factory()
    tariff = tariff_factory(subject)
    purchase = replace(
        subject.purchase,
        account_id="retained-historical-account",
        accepted=subject.purchase.accepted
        if same_origin
        else subject.purchase.accepted.model_copy(update={"provider_origin": "https://foreign.test"}),
    )
    proof = normalize_subscription(
        replace(subject, purchase=purchase),
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff,
        subscription=subscription_factory(),
    )
    assert proof.complete is same_origin
    assert (proof.identity == IdentityProof.MATCH) is same_origin


@pytest.mark.parametrize("field,value", [("price", 15), ("multiplicator", 2), ("tariff_service_id", 1002)])
@pytest.mark.parametrize("missing", [None, "total_price", "period_length"])
def test_billing_subscription_reconciliation_effective_drift(field: str, value: int, missing: str | None) -> None:
    subject = subject_factory()
    raw = subscription_factory().model_dump()
    raw["services"][0][field] = value
    # A catalog price or unchanged provider instance cannot mask effective drift.
    raw["services"][0]["tariff_price"] = 999
    raw["subscription_instance_id"] = 123
    if missing is not None:
        raw[missing] = None
    point = Subscription.model_validate(raw)
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=point,
    )
    assert proof.commercial == (CommercialProof.MISMATCH if missing is None else CommercialProof.INCOMPLETE)


@pytest.mark.parametrize(
    "change", [{"currency_symbol": "USD"}, {"period_length": 2}, {"is_demo": True}, {"services": []}]
)
def test_billing_subscription_reconciliation_known_difference_without_total_is_incomplete(change: dict) -> None:
    subject = subject_factory()
    point = subscription_factory().model_copy(update={"total_price": None, **change})
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=point,
    )
    assert proof.identity == IdentityProof.MATCH and proof.commercial == CommercialProof.INCOMPLETE


@pytest.mark.parametrize("change", [{"state": 99}, {"current_blocking": 99}])
def test_billing_subscription_reconciliation_unknown_lifecycle(change: dict) -> None:
    subject = subject_factory()
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=subscription_factory().model_copy(update=change),
    )
    assert not proof.complete and proof.financial is None


@pytest.mark.parametrize(
    "change",
    [
        {"last_tariffication_period_start": None},
        {"last_tariffication_period_start": "1970-01-01 00:00:00"},
        {"last_tariffication_period_end": "2026-09-01"},
        {"last_tariffication_period_start": "2026-02-30"},
    ],
)
def test_billing_subscription_reconciliation_calendar_does_not_erase_product_proof(change: dict) -> None:
    subject = subject_factory()
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=subscription_factory().model_copy(update=change),
    )
    assert proof.complete and proof.financial == "allowed"
    assert not proof.calendar_complete and proof.cycle is None


@pytest.mark.parametrize("kind", ["customer", "agreement", "seller", "subscription"])
def test_billing_subscription_reconciliation_ownership_conflicts(kind: str) -> None:
    subject = subject_factory()
    user, agreement, point = user_factory(), agreement_factory(), subscription_factory()
    if kind == "customer":
        user = user.model_copy(update={"outer_id": "foreign"})
    elif kind == "agreement":
        agreement = agreement.model_copy(update={"user_id": 999})
    elif kind == "seller":
        agreement = agreement.model_copy(update={"organization_id": 999})
    else:
        point = point.model_copy(update={"agreement_id": 999})
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user,
        agreement=agreement,
        tariff=None,
        subscription=point.model_copy(update={"total_price": None}),
    )
    assert proof.identity == IdentityProof.CONFLICT and proof.financial is None
    assert proof.commercial == CommercialProof.INCOMPLETE
    assert ("customer_original_key_mismatch" in proof.reasons) == (kind == "customer")


def test_billing_subscription_reconciliation_negative_independent_of_terms_and_sale_flags() -> None:
    subject = subject_factory()
    tariff = tariff_factory(subject)
    tariff = replace(tariff, value=tariff.value.model_copy(update={"archive": 1, "assign_unavailable": 1}))
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff,
        subscription=subscription_factory(),
    )
    assert proof.complete and proof.commercial == CommercialProof.MATCH
    for point in (
        subscription_factory().model_copy(update={"state": 3, "total_price": None}),
        subscription_factory().model_copy(update={"current_blocking": 1, "services": None}),
    ):
        proof = normalize_subscription(
            subject,
            step1_settings(),
            user=user_factory(),
            agreement=agreement_factory(),
            tariff=None,
            subscription=point,
        )
        assert proof.financial == "blocked" and not proof.complete
    ended = subscription_factory().model_copy(update={"state": 3})
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory().model_copy(update={"close_date": "2026-10-20"}),
        tariff=tariff,
        subscription=ended,
    )
    assert proof.lifecycle == "ended" and proof.complete
    prove_subscription(
        ended,
        agreement_id=456,
        selection=subject.purchase.accepted.selection,
        offer=subject.purchase.accepted.offer,
    )
    prove_agreement(
        agreement_factory().model_copy(update={"close_date": "2026-10-20"}),
        user_id=345,
        seller_id=21,
        number="portal-agreement",
    )


@pytest.mark.parametrize("field", ["currency_id", "balance_blocks", "payment_type", "float_period"])
def test_billing_subscription_reconciliation_missing_policy(field: str) -> None:
    subject = subject_factory()
    tariff = tariff_factory(subject)
    tariff = replace(tariff, value=tariff.value.model_copy(update={field: None}))
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff,
        subscription=subscription_factory(),
    )
    assert not proof.complete and proof.commercial == CommercialProof.INCOMPLETE


def test_billing_subscription_reconciliation_invalid_decoder_and_runbook_contract() -> None:
    with pytest.raises(ValidationError):
        Subscription.model_validate(
            {
                "subscription_id": 1,
                "agreement_id": 2,
                "tariff_id": 3,
                "subscription_start_date": "secret arbitrary text",
            }
        )
    runbook = Path("docs/engineering/billing-background-operations.md").read_text()
    for phrase in (
        RECONCILIATION_SCHEMA,
        "/users/{id}",
        "/agreements/{id}",
        "/tariffs/{id}",
        "/subscriptions/{id}",
        "COMPLETE_MATCH",
        "COMPLETE_MISMATCH",
        "INCOMPLETE",
        "six hours",
        "primary_subscription_id=NULL",
        "read_started_at",
    ):
        assert phrase in runbook


def test_billing_subscription_reconciliation_extra_service_and_contradictory_tariff_read() -> None:
    subject = subject_factory()
    point = subscription_factory()
    extra = point.model_copy(update={"services": [*point.services, point.services[0]]})
    evidence = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=extra,
    )
    assert evidence.commercial == CommercialProof.MISMATCH
    for changes in ({"external_billing_account_id": "foreign"}, {"tariff_id": 702}):
        tariff = replace(tariff_factory(subject), **changes)
        evidence = normalize_subscription(
            subject,
            step1_settings(),
            user=user_factory(),
            agreement=agreement_factory(),
            tariff=tariff,
            subscription=point,
        )
        assert evidence.commercial == CommercialProof.INCOMPLETE and not evidence.complete
        assert evidence.financial is None
        evidence = normalize_subscription(
            subject,
            step1_settings(),
            user=user_factory(),
            agreement=agreement_factory(),
            tariff=tariff,
            subscription=point.model_copy(update={"current_blocking": 1}),
        )
        assert evidence.identity == IdentityProof.INCOMPLETE and evidence.financial is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("payment_type", 1),
        ("balance_blocks", 0),
        ("dynamic_rent", 1),
        ("dynamic_rent_unblock_type", 1),
        ("demo_period_length", 1),
        ("proportional_rent", 1),
        ("currency_id", 2),
    ],
)
def test_billing_subscription_reconciliation_unsupported_policy(field: str, value: int) -> None:
    subject = subject_factory()
    tariff = tariff_factory(subject)
    tariff = replace(tariff, value=tariff.value.model_copy(update={field: value}))
    evidence = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff,
        subscription=subscription_factory(),
    )
    assert evidence.commercial == CommercialProof.MISMATCH


@pytest.mark.parametrize(
    "start,cycle_start,cycle_end,end,complete",
    [
        ("2026-10-01 12:00:00", "2026-10-01 00:00:00", "2026-11-01 00:00:00", "2026-11-01 00:00:00", False),
        ("2026-10-01 00:00:00", "2026-10-01 00:00:00", "2026-11-01 12:00:00", "2026-11-01 00:00:00", False),
        ("2026-10-01 12:00:00", "2026-10-01 12:00:00", "2026-10-01 14:00:00", "2026-10-01 14:00:00", True),
        ("2026-10-01", "2026-10-01 12:00:00", "2026-11-01 00:00:00", "2026-11-02", False),
        ("2026-09-30", "2026-10-01 12:00:00", "2026-11-01 00:00:00", "2026-11-02", True),
        ("2026-10-01", "2026-10-01", "2026-11-01", "2026-11-01", True),
    ],
)
def test_billing_subscription_reconciliation_preserves_calendar_precision(
    start: str, cycle_start: str, cycle_end: str, end: str, complete: bool
) -> None:
    subject = subject_factory()
    raw = subscription_factory().model_dump()
    raw.update(
        subscription_instance_start_date=start,
        subscription_instance_end_date=end,
        last_tariffication_period_start=cycle_start,
        last_tariffication_period_end=cycle_end,
    )
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=Subscription.model_validate(raw),
    )
    assert proof.calendar_complete is complete
    assert proof.complete and proof.financial == "allowed"
    assert (proof.cycle is not None) is complete
    assert proof.calendar["subscription_instance_start_date"] == start
    assert proof.calendar["last_tariffication_period_end"] == cycle_end


@pytest.mark.parametrize("missing", ["total", "policy", "currency", "agreement_policy"])
def test_billing_subscription_reconciliation_partial_policy_never_makes_commercial_conflict(missing: str) -> None:
    subject = subject_factory()
    configuration = step1_settings()
    point = subscription_factory().model_copy(update={"period_length": 2})
    tariff = tariff_factory(subject)
    agreement = agreement_factory()
    if missing == "total":
        point = point.model_copy(update={"total_price": None})
    elif missing == "policy":
        tariff = replace(tariff, value=tariff.value.model_copy(update={"payment_type": None}))
    elif missing == "currency":
        configuration = configuration.model_copy(update={"lbx_currency_id": ""})
    else:
        agreement = agreement.model_copy(update={"is_offer": None})
    proof = normalize_subscription(
        subject,
        configuration,
        user=user_factory(),
        agreement=agreement,
        tariff=tariff,
        subscription=point,
    )
    assert proof.commercial == CommercialProof.INCOMPLETE
    assert not proof.complete and proof.financial is None


@pytest.mark.parametrize("bound", [True, False])
@pytest.mark.parametrize("owner", ["match", "missing", "conflict"])
def test_billing_subscription_reconciliation_closed_agreement_without_subscription(bound: bool, owner: str) -> None:
    original = subject_factory()
    subject = (
        original
        if bound
        else SubscriptionCandidateSubject(
            original.purchase,
            original.customer,
            original.agreement_id,
            original.agreement_key,
            original.provider_subscription_id,
        )
    )
    agreement = agreement_factory().model_copy(update={"close_date": "2026-10-20"})
    if owner == "missing":
        agreement = agreement.model_copy(update={"organization_id": None})
    elif owner == "conflict":
        agreement = agreement.model_copy(update={"user_id": 999})
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement,
        tariff=None,
        subscription=None,
    )
    assert not proof.complete and proof.commercial == CommercialProof.INCOMPLETE
    if owner == "conflict":
        assert proof.identity == IdentityProof.CONFLICT
    if bound and owner == "match":
        assert proof.identity == IdentityProof.MATCH
        assert (proof.lifecycle, proof.financial) == ("ended", "blocked")
        assert proof.calendar["agreement_close_date"] == "2026-10-20"
    else:
        assert proof.lifecycle is None and proof.financial is None


@pytest.mark.parametrize("change", [{"state": 3, "current_blocking": 99}, {"state": None}, {"current_blocking": None}])
def test_billing_subscription_reconciliation_unrecognized_lifecycle_is_incomplete(change: dict) -> None:
    subject = subject_factory()
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=subscription_factory().model_copy(update=change),
    )
    assert not proof.complete and proof.lifecycle is None and proof.financial is None


@pytest.mark.parametrize("late", ["subscription", "tariff"])
@pytest.mark.parametrize("scope_error", [False, True])
@pytest.mark.anyio
async def test_billing_subscription_reconciliation_timely_negative_precedes_policy(
    late: str,
    scope_error: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = subject_factory()
    clock = [100.0]
    monkeypatch.setattr("app.infrastructure.preflight.time.monotonic", lambda: clock[0])
    reads: list[str] = []

    async def point(name: str, value: object, **kwargs: object) -> object:
        reads.append(name)
        if name == late:
            clock[0] += 2
            if scope_error:
                raise LbxScopeMismatch()
        return value

    client = SimpleNamespace(
        get_user=lambda **kwargs: point("customer", user_factory(), **kwargs),
        get_agreement=lambda **kwargs: point("agreement", agreement_factory(), **kwargs),
        get_subscription=lambda **kwargs: point(
            "subscription",
            subscription_factory().model_copy(update={"current_blocking": 1}),
            **kwargs,
        ),
        get_tariff=lambda **kwargs: point("tariff", tariff_factory(subject), **kwargs),
    )
    admission = PreflightAdmission(PreflightPolicy(1, 0.1, 1, 0))
    try:
        async with admission.operation(bound_scope=False) as budget:
            proof = await read_subscription_proof(client, subject, step1_settings(), budget=budget)
    finally:
        await admission.aclose()
    assert reads == ["customer", "agreement", "subscription"] + (["tariff"] if late == "tariff" else [])
    assert not proof.complete and proof.identity != IdentityProof.CONFLICT
    assert proof.financial == ("blocked" if late == "tariff" else None)
    assert "read_budget_exhausted" in proof.reasons


@pytest.mark.parametrize("policy", ["tariff", "agreement"])
def test_billing_subscription_reconciliation_missing_terms_with_changed_policy_remains_incomplete(policy: str) -> None:
    subject = subject_factory()
    tariff, agreement = tariff_factory(subject), agreement_factory()
    if policy == "tariff":
        tariff = replace(tariff, value=tariff.value.model_copy(update={"payment_type": 1}))
    else:
        agreement = agreement.model_copy(update={"is_offer": True})
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement,
        tariff=tariff,
        subscription=subscription_factory().model_copy(update={"total_price": None}),
    )
    assert proof.commercial == CommercialProof.INCOMPLETE and not proof.complete


@pytest.mark.parametrize("connection", [0, 10])
def test_billing_subscription_reconciliation_connection_evidence_only_when_applicable(connection: int) -> None:
    from decimal import Decimal

    subject = subject_factory()
    accepted = subject.purchase.accepted
    offer = replace(
        accepted.offer,
        money=replace(
            accepted.offer.money,
            connection_unit_amount=Decimal(connection),
            connection_amount=Decimal(connection),
        ),
    )
    subject = replace(
        subject, purchase=replace(subject.purchase, accepted=accepted.model_copy(update={"offer": offer}))
    )
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=subscription_factory(),
    )
    assert proof.commercial == (CommercialProof.MATCH if connection == 0 else CommercialProof.INCOMPLETE)
    assert proof.complete is (connection == 0)


@pytest.mark.parametrize("block", [0, 1, 3])
def test_billing_subscription_reconciliation_terminal_proof_does_not_authorize_payment(block: int) -> None:
    subject = subject_factory()
    point = subscription_factory().model_copy(update={"state": 3, "current_blocking": block})
    prove_subscription(
        point, agreement_id=456, selection=subject.purchase.accepted.selection, offer=subject.purchase.accepted.offer
    )
    with pytest.raises(LbxResponseInvalid):
        require_payable_subscription(point)
    agreement = agreement_factory().model_copy(update={"close_date": "2026-11-05"})
    prove_agreement(agreement, user_id=345, seller_id=21, number="portal-agreement")
    with pytest.raises(LbxResponseInvalid):
        require_preparable_agreement(agreement)


@pytest.mark.parametrize("close_date", ["2026-02-30", "2026-11-05T12:00:00Z", "unknown"])
def test_billing_subscription_reconciliation_invalid_agreement_calendar_never_invents_terminal(close_date: str) -> None:
    subject = subject_factory()
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory().model_copy(update={"close_date": close_date}),
        tariff=tariff_factory(subject),
        subscription=subscription_factory(),
    )
    assert not proof.complete and proof.financial is None and proof.lifecycle is None
    assert "agreement_calendar_incomplete" in proof.reasons


def test_billing_subscription_reconciliation_identity_conflict_survives_unrelated_provenance_failure() -> None:
    subject = subject_factory()
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory().model_copy(update={"outer_id": "foreign"}),
        agreement=agreement_factory(),
        tariff=replace(tariff_factory(subject), external_billing_account_id="foreign"),
        subscription=subscription_factory().model_copy(update={"total_price": None}),
    )
    assert proof.identity == IdentityProof.CONFLICT and proof.commercial == CommercialProof.INCOMPLETE
    assert proof.financial is None


@pytest.mark.parametrize(
    "start,end,anchor,calendar_complete",
    [
        ("2026-10-31", "2026-10-31", "2026-10-31", True),
        ("2026-10-01", "2026-10-31", "2026-10-15", True),
        ("2026-10-01T12:34:56Z", "2026-11-01T12:34:56Z", "2026-10-01 12:34:56", False),
    ],
)
def test_billing_subscription_reconciliation_inclusive_dates_and_mixed_zones(
    start: str,
    end: str,
    anchor: str,
    calendar_complete: bool,
) -> None:
    subject = subject_factory()
    point = subscription_factory().model_copy(
        update={
            "last_tariffication_period_start": start,
            "last_tariffication_period_end": end,
            "subscription_instance_start_date": anchor,
        }
    )
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=point,
    )
    assert proof.complete and proof.financial == "allowed"
    assert proof.calendar_complete is calendar_complete
    if calendar_complete:
        assert proof.cycle.start == start and proof.cycle.end == end and proof.cycle.anchor == anchor
    else:
        assert proof.cycle is None
