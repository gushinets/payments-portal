"""SIMULATED lifecycle/term proof; these tests never call real LBX."""

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domains.billing.reconciliation_contracts import CommercialProof, IdentityProof, RECONCILIATION_SCHEMA
from app.integrations.lbx.financial import (
    Subscription,
    classify_lifecycle,
    inspect_effective_terms,
    inventory_terminal,
    prove_effective_terms,
    prove_subscription,
)
from app.integrations.lbx.errors import LbxResponseInvalid, LbxScopeMismatch
from app.integrations.lbx.reconciliation import normalize_subscription
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
        (-2, 1, "inactive", "blocked", "waiting"),
        (-2, 3, "inactive", "blocked", "waiting"),
        (-1, 0, "inactive", "blocked", "inactive"),
        (-1, 1, "inactive", "blocked", "inactive"),
        (-1, 3, "inactive", "blocked", "inactive"),
        (0, 0, "inactive", "blocked", "inactive"),
        (0, 1, "inactive", "blocked", "inactive"),
        (0, 3, "inactive", "blocked", "inactive"),
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
    inspected = classify_lifecycle(point)
    assert (inspected.lifecycle, inspected.financial, inspected.reason) == (lifecycle, financial, reason)
    prove_subscription(
        point,
        agreement_id=456,
        selection=subject.purchase.accepted.selection,
        offer=subject.purchase.accepted.offer,
    )
    assert inventory_terminal(point, agreement_factory()) is (lifecycle == "ended")


@pytest.mark.parametrize(
    "change,classification",
    [
        ({"total_price": None}, CommercialProof.INCOMPLETE),
        ({"services": None}, CommercialProof.INCOMPLETE),
        ({"currency_symbol": None}, CommercialProof.INCOMPLETE),
        ({"services": [], "total_price": 0}, CommercialProof.MISMATCH),
        ({"currency_symbol": "USD"}, CommercialProof.INCOMPLETE),
        ({"period_length": 2, "last_tariffication_period_end": "2026-12-01"}, CommercialProof.MISMATCH),
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
    if field == "price":
        raw["total_price"] = value
    if field == "multiplicator":
        raw["total_price"] = 100 * value
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
    assert proof.commercial == (CommercialProof.INCOMPLETE if missing else CommercialProof.MISMATCH)
    assert "effective_terms_mismatch" in proof.reasons
    assert ("effective_terms_incomplete" in proof.reasons) is (missing is not None)


@pytest.mark.parametrize(
    "change", [{"currency_symbol": "USD"}, {"period_length": 2}, {"is_demo": True}, {"services": []}]
)
def test_billing_subscription_reconciliation_missing_total_precedes_known_terms_difference(change: dict) -> None:
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
    assert not proof.complete and proof.financial is None
    assert "effective_terms_incomplete" in proof.reasons
    assert ("effective_terms_mismatch" in proof.reasons) is ("currency_symbol" not in change)
    with pytest.raises(LbxResponseInvalid):
        prove_effective_terms(
            point,
            agreement_id=456,
            selection=subject.purchase.accepted.selection,
            offer=subject.purchase.accepted.offer,
        )


@pytest.mark.parametrize(
    "change",
    [
        {"state": 99},
        {"current_blocking": 99},
        {"last_tariffication_period_start": None},
        {"last_tariffication_period_start": "1970-01-01 00:00:00"},
        {"last_tariffication_period_end": "2026-09-01"},
        {"last_tariffication_period_start": "2026-02-30"},
        {"subscription_instance_start_date": "2026-10-15"},
    ],
)
def test_billing_subscription_reconciliation_unknown_or_incomplete(change: dict) -> None:
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


@pytest.mark.parametrize("kind", ["customer", "customer_id", "agreement", "seller", "subscription"])
def test_billing_subscription_reconciliation_ownership_conflicts(kind: str) -> None:
    subject = subject_factory()
    user, agreement, point = user_factory(), agreement_factory(), subscription_factory()
    if kind == "customer":
        user = user.model_copy(update={"outer_id": "foreign"})
    elif kind == "customer_id":
        user = user.model_copy(update={"user_id": 999, "outer_id": "foreign"})
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
    # Terminal interpretation is returned to the caller's readback/admission
    # decision; original effective terms remain provable without an exception.
    prove_subscription(
        ended,
        agreement_id=456,
        selection=subject.purchase.accepted.selection,
        offer=subject.purchase.accepted.offer,
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
    extra = point.model_copy(update={"services": [*point.services, point.services[0]], "total_price": 200})
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
    assert proof.calendar_complete is complete and proof.complete is complete
    assert (proof.financial == "allowed") is complete
    assert proof.calendar["subscription_instance_start_date"] == start
    assert proof.calendar["last_tariffication_period_end"] == cycle_end


def test_effective_term_inspection_collects_all_missing_fields_and_differences() -> None:
    subject = subject_factory()
    raw = subscription_factory().model_dump()
    raw.update(total_price=None, period_length=2, is_demo=None)
    raw["services"][0].update(price=None, multiplicator=None, tariff_service_id=1002, bulk_price=5)
    inspection = inspect_effective_terms(
        Subscription.model_validate(raw),
        selection=subject.purchase.accepted.selection,
        offer=subject.purchase.accepted.offer,
    )
    assert set(inspection.incomplete_fields) == {
        "total_price",
        "is_demo",
        "services[0].price",
        "services[0].multiplicator",
    }
    assert set(inspection.differing_fields) == {
        "period_length",
        "services[0].tariff_service_id",
        "services[0].bulk_price",
    }


@pytest.mark.parametrize("difference", ["price", "period", "composition", "policy", "agreement_policy"])
@pytest.mark.parametrize("missing", ["terms", "policy", "agreement_policy", "mapping", "remapping", "symbol"])
def test_material_completeness_precedes_differences_across_read_set(difference: str, missing: str) -> None:
    subject, config = subject_factory(), step1_settings()
    raw, tariff, agreement = subscription_factory().model_dump(), tariff_factory(subject), agreement_factory()
    if difference == "price":
        raw["services"][0]["price"] = raw["total_price"] = 150
    elif difference == "period":
        raw["period_length"] = 2
    elif difference == "composition":
        raw["services"] = []
        raw["total_price"] = 0
    elif difference == "policy":
        tariff = replace(tariff, value=tariff.value.model_copy(update={"payment_type": 1}))
    else:
        agreement = agreement.model_copy(update={"is_offer": True})
    if missing == "terms":
        raw["total_price"] = None
    elif missing == "policy":
        tariff = replace(tariff, value=tariff.value.model_copy(update={"dynamic_rent": None}))
    elif missing == "agreement_policy":
        agreement = agreement.model_copy(update={"is_offer": None})
    elif missing in {"mapping", "remapping"}:
        config = config.model_copy(update={"lbx_currency_id": "" if missing == "mapping" else "2"})
    else:
        raw["currency_symbol"] = "USD"
    proof = normalize_subscription(
        subject,
        config,
        user=user_factory(),
        agreement=agreement,
        tariff=tariff,
        subscription=Subscription.model_validate(raw),
    )
    assert proof.commercial == CommercialProof.INCOMPLETE and not proof.complete
    assert proof.financial is None
    expected_reason = {
        "price": "effective_terms_mismatch",
        "period": "effective_terms_mismatch",
        "composition": "effective_terms_mismatch",
        "policy": "unsupported_prepaid_policy",
        "agreement_policy": "agreement_policy_mismatch",
    }[difference]
    # Replacing the differing agreement flag with missing evidence removes that
    # difference; every independently observable difference remains recorded.
    assert (expected_reason in proof.reasons) is not (difference == missing == "agreement_policy")


@pytest.mark.parametrize("currency_id", ["", "invalid", "0", "2"])
def test_missing_invalid_or_remapped_currency_is_incomplete(currency_id: str) -> None:
    subject = subject_factory()
    proof = normalize_subscription(
        subject,
        step1_settings().model_copy(update={"lbx_currency_id": currency_id}),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=subscription_factory(),
    )
    assert proof.commercial == CommercialProof.INCOMPLETE and not proof.complete
    assert "tariff_policy_incomplete" in proof.reasons
    assert "unsupported_prepaid_policy" not in proof.reasons


@pytest.mark.parametrize("money_change", [{"currency": "USD"}, {"decimal_places": 3}])
def test_currency_conflict_requires_validated_money_meaning(money_change: dict[str, object]) -> None:
    subject = subject_factory()
    accepted = subject.purchase.accepted
    # The observed ID is interpreted by a valid account mapping as RUB/2;
    # its proven meaning conflicts with these independently saved terms.
    subject = replace(
        subject,
        purchase=replace(
            subject.purchase,
            accepted=accepted.model_copy(
                update={"offer": replace(accepted.offer, money=replace(accepted.offer.money, **money_change))}
            ),
        ),
    )
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=subscription_factory(),
    )
    assert proof.commercial == CommercialProof.MISMATCH and proof.complete
    assert "unsupported_prepaid_policy" in proof.reasons


@pytest.mark.parametrize(
    "change", [{"state": 99}, {"current_blocking": 99}, {"state": None}, {"current_blocking": None}]
)
def test_unknown_lifecycle_has_no_financial_binding_conflict(change: dict[str, int | None]) -> None:
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
    assert not proof.complete and proof.lifecycle is None and proof.financial is None
    assert "lifecycle_unknown" in proof.reasons
    with pytest.raises(LbxResponseInvalid):
        prove_subscription(
            point,
            agreement_id=456,
            selection=subject.purchase.accepted.selection,
            offer=subject.purchase.accepted.offer,
        )
    with pytest.raises(LbxResponseInvalid):
        inventory_terminal(point, agreement_factory())


@pytest.mark.parametrize(
    "field",
    [
        "period_id",
        "period_type",
        "period_length",
        "is_demo",
        "is_offer_agrm",
        "currency_symbol",
        "total_price",
        "services",
        "services.multiplicator",
        "services.price",
        "services.periodic_service",
        "services.bulk_service",
    ],
)
def test_each_required_effective_field_prevents_strict_admission_despite_difference(field: str) -> None:
    subject = subject_factory()
    raw = subscription_factory().model_dump()
    raw["tariff_id"] = 702
    if field.startswith("services."):
        raw["services"][0][field.split(".")[1]] = None
    else:
        raw[field] = None
    point = Subscription.model_validate(raw)
    inspected = inspect_effective_terms(
        point, selection=subject.purchase.accepted.selection, offer=subject.purchase.accepted.offer
    )
    assert inspected.incomplete_fields and "tariff_id" in inspected.differing_fields
    with pytest.raises(LbxResponseInvalid):
        prove_effective_terms(
            point,
            agreement_id=456,
            selection=subject.purchase.accepted.selection,
            offer=subject.purchase.accepted.offer,
        )


@pytest.mark.parametrize("change", [{"state": 99}, {"current_blocking": 99}])
def test_closed_agreement_proves_negative_without_completing_unknown_lifecycle(change: dict[str, int]) -> None:
    subject = subject_factory()
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory().model_copy(update={"close_date": "2026-11-05"}),
        tariff=tariff_factory(subject),
        subscription=subscription_factory().model_copy(update=change),
    )
    assert not proof.complete and (proof.lifecycle, proof.financial) == ("ended", "blocked")
    assert "lifecycle_unknown" in proof.reasons and "agreement_closed" in proof.reasons


def test_incomplete_material_and_policy_provenance_preserve_actual_ownership_conflict() -> None:
    subject = subject_factory()
    point = subscription_factory().model_copy(update={"agreement_id": 999, "total_price": None})
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=replace(tariff_factory(subject), external_billing_account_id="foreign"),
        subscription=point,
    )
    assert proof.identity == IdentityProof.CONFLICT and proof.commercial == CommercialProof.INCOMPLETE
    assert proof.financial is None
    with pytest.raises(LbxScopeMismatch):
        prove_subscription(
            point,
            agreement_id=456,
            selection=subject.purchase.accepted.selection,
            offer=subject.purchase.accepted.offer,
        )
