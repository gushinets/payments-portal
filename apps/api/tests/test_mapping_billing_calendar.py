"""Account calendar admission with controlled clocks; no provider or DB calls."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from apps.api.tests.support import v1_cli as cli
from apps.api.tests.support import v1_mapping_operator as mapping_operator
from apps.api.tests.support.v1_mapping_operator import fresh_mapping_evaluation
from app.domains.catalog.mapping_evidence import MappingRefused
from app.domains.catalog.commercial_offer import CommercialEvidenceBasis, SelectedOfferRefused
from apps.api.tests.support.commercial_mappings import SIMULATED_UID, operator_settings, reviewed_fixture
from apps.api.tests.support.kernel import manifest_fixture
from apps.api.tests.support.lbx_selected_offer import SelectedOfferRecording, simulated_inputs, simulated_selection


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("effective_on", "instant", "valid_from", "valid_until", "reason"),
    [
        (date(2026, 10, 15), "2026-10-16T12:00:00+00:00", date(2026, 9, 1), None, "mapping_effective_date_not_current"),
        (date(2026, 10, 17), "2026-10-16T12:00:00+00:00", date(2026, 9, 1), None, "mapping_effective_date_not_current"),
        (
            date(2026, 10, 16),
            "2026-10-16T12:00:00+00:00",
            date(2026, 9, 1),
            date(2026, 10, 16),
            "selected_offer_policy_not_applicable",
        ),
        (
            date(2026, 10, 16),
            "2026-10-16T12:00:00+00:00",
            date(2026, 10, 17),
            None,
            "selected_offer_policy_not_applicable",
        ),
        (date(2026, 10, 16), "2026-10-16T12:00:00+00:00", date(2026, 10, 16), date(2026, 10, 17), None),
        # Explicit simulated Moscow calendar is a day ahead of UTC here.
        (date(2026, 10, 16), "2026-10-15T21:00:00+00:00", date(2026, 9, 1), None, None),
        (date(2026, 10, 15), "2026-10-15T21:00:00+00:00", date(2026, 9, 1), None, "mapping_effective_date_not_current"),
    ],
)
async def test_fresh_evaluation_uses_current_account_date_and_policy_interval(
    effective_on: date, instant: str, valid_from: date, valid_until: date | None, reason: str | None
) -> None:
    reviewed = await reviewed_fixture()
    proposal = reviewed.proposal.model_copy(
        update={"selection": simulated_selection().model_copy(update={"effective_on": effective_on})}
    )
    inputs = simulated_inputs()
    assert inputs.policy is not None
    inputs = inputs.model_copy(
        update={"policy": inputs.policy.model_copy(update={"valid_from": valid_from, "valid_until": valid_until})}
    )
    # For successful reads, independently review this policy without taking
    # approval from the evaluation under test.
    if reason is None:
        reviewed = await reviewed_fixture(selection=proposal.selection, source_inputs=inputs)
    recording = SelectedOfferRecording()

    async def evaluate() -> None:
        result = await fresh_mapping_evaluation(
            operator_settings(),
            proposal=proposal,
            approval=reviewed.approval,
            source_inputs=inputs,
            principal=f"os-euid:{SIMULATED_UID}",
            clock=lambda: datetime.fromisoformat(instant),
            kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=manifest_fixture())),
            lbx_transport=httpx.MockTransport(recording.respond),
        )
        assert result.document.evaluated_at == datetime.fromisoformat(instant)
        assert result.document.material.technical.allowance == 25

    if reason is None:
        await evaluate()
    else:
        with pytest.raises((MappingRefused, SelectedOfferRefused), match=reason):
            await evaluate()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("missing", "mapping_account_calendar_not_configured"),
        ("foreign", "mapping_account_calendar_scope_mismatch"),
        ("invalid", "mapping_account_calendar_invalid"),
        ("documented", "mapping_account_calendar_unproven"),
    ],
)
async def test_calendar_requires_explicit_account_evidence(change: str, reason: str) -> None:
    reviewed = await reviewed_fixture()
    inputs = simulated_inputs()
    assert inputs.calendar is not None
    calendar = inputs.calendar
    if change == "foreign":
        calendar = calendar.model_copy(update={"external_billing_account_id": "other-account"})
    elif change == "invalid":
        calendar = calendar.model_copy(update={"timezone": "Unknown/Calendar"})
    elif change == "documented":
        calendar = calendar.model_copy(
            update={"evidence": calendar.evidence.model_copy(update={"basis": CommercialEvidenceBasis.DOCUMENTED})}
        )
    inputs = inputs.model_copy(update={"calendar": None if change == "missing" else calendar})

    def forbidden(request: httpx.Request) -> httpx.Response:
        raise AssertionError("calendar refusal must precede source HTTP")

    with pytest.raises(MappingRefused, match=reason):
        await fresh_mapping_evaluation(
            operator_settings(),
            proposal=reviewed.proposal,
            approval=reviewed.approval,
            source_inputs=inputs,
            principal=f"os-euid:{SIMULATED_UID}",
            clock=lambda: datetime(2026, 10, 16, 12, tzinfo=UTC),
            kernel_transport=httpx.MockTransport(forbidden),
            lbx_transport=httpx.MockTransport(forbidden),
        )


@pytest.mark.anyio
async def test_account_midnight_during_source_reads_refuses_instead_of_rewriting_date() -> None:
    reviewed = await reviewed_fixture()
    instants = iter((datetime(2026, 10, 16, 20, 59, 59, tzinfo=UTC), datetime(2026, 10, 16, 21, tzinfo=UTC)))
    with pytest.raises(MappingRefused, match="mapping_effective_date_not_current"):
        await fresh_mapping_evaluation(
            operator_settings(),
            proposal=reviewed.proposal,
            approval=reviewed.approval,
            source_inputs=simulated_inputs(),
            principal=f"os-euid:{SIMULATED_UID}",
            clock=lambda: next(instants),
            kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=manifest_fixture())),
            lbx_transport=httpx.MockTransport(SelectedOfferRecording().respond),
        )
    assert reviewed.proposal.selection.effective_on == date(2026, 10, 16)


@pytest.mark.skipif(os.name != "posix", reason="Operator flock requires Unix")
@pytest.mark.parametrize("command", ["dry-run", "publish"])
@pytest.mark.parametrize("expired_policy", [False, True])
def test_operator_commands_refuse_stale_date_or_expired_policy_before_database(
    command: str, expired_policy: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with asyncio.Runner() as runner:
        reviewed = runner.run(reviewed_fixture())
    inputs = simulated_inputs()
    assert inputs.policy is not None
    if expired_policy:
        # Keep today's selection but let the approved policy expire today.
        inputs = inputs.model_copy(
            update={"policy": inputs.policy.model_copy(update={"valid_until": date(2026, 10, 16)})}
        )
        instant = datetime(2026, 10, 16, 12, tzinfo=UTC)
        reason = "selected_offer_policy_not_applicable"
    else:
        instant = datetime(2026, 10, 20, 12, tzinfo=UTC)
        inputs = inputs.model_copy(
            update={"policy": inputs.policy.model_copy(update={"valid_until": date(2026, 10, 17)})}
        )
        reason = "mapping_effective_date_not_current"
    for name, value in (("proposal", reviewed.proposal), ("approval", reviewed.approval), ("inputs", inputs)):
        (tmp_path / f"{name}.json").write_text(value.model_dump_json(), encoding="utf-8")
    configuration = operator_settings(
        mapping_approval_file=tmp_path / "approval.json",
        mapping_source_inputs_file=tmp_path / "inputs.json",
        mapping_operator_lock_file=tmp_path / "operator.lock",
    )
    monkeypatch.setattr(mapping_operator.os, "geteuid", lambda: SIMULATED_UID)
    original = fresh_mapping_evaluation

    async def configured(*args: object, **kwargs: object) -> mapping_operator.FreshMappingEvaluation:
        return await original(
            *args,
            **kwargs,
            clock=lambda: instant,
            kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=manifest_fixture())),
            lbx_transport=httpx.MockTransport(SelectedOfferRecording().respond),
        )

    monkeypatch.setattr(mapping_operator, "fresh_mapping_evaluation", configured)
    argv = [command, "--proposal", str(tmp_path / "proposal.json")]
    if command == "publish":
        argv += ["--expected-previous-revision", "0"]
    with pytest.raises((MappingRefused, SelectedOfferRefused), match=reason):
        cli.execute(cli.parser().parse_args(argv), configuration)


@pytest.mark.anyio
@pytest.mark.parametrize("expiring", ["account_day", "policy", "price"])
async def test_evaluation_carries_exclusive_account_calendar_boundary(expiring: str) -> None:
    recording = SelectedOfferRecording()
    inputs = simulated_inputs()
    assert inputs.policy is not None
    if expiring == "policy":
        inputs = inputs.model_copy(
            update={"policy": inputs.policy.model_copy(update={"valid_until": date(2026, 10, 17)})}
        )
    elif expiring == "price":
        recording.replace("prices", "2027-01-01", "2026-10-17")
    reviewed = await reviewed_fixture(recording=recording, source_inputs=inputs)
    instant = datetime(2026, 10, 16, 20, 59, 59, tzinfo=UTC)  # Moscow 23:59:59
    from apps.api.tests.support.commercial_mappings import fresh_fixture

    fresh = await fresh_fixture(reviewed, recording=recording, source_inputs=inputs, clock=lambda: instant)
    assert fresh.evidence_valid_until == datetime(2026, 10, 16, 21, tzinfo=UTC)
    assert fresh.evidence_valid_until.tzinfo is UTC
    assert fresh.document.evaluated_at == instant
    assert "evidence_valid_until" not in fresh.document.model_dump()
    if expiring == "price":
        assert fresh.document.material.terms.period.price_effective_until == date(2026, 10, 17)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("timezone", "expected_utc"),
    [
        ("Europe/Berlin", "2026-10-25T23:00:00+00:00"),  # DST ends during this day.
        ("Asia/Tokyo", "2026-10-25T15:00:00+00:00"),
        ("America/New_York", "2026-10-26T04:00:00+00:00"),
    ],
)
async def test_boundary_uses_account_iana_zone_including_dst(timezone: str, expected_utc: str) -> None:
    from apps.api.tests.support.commercial_mappings import fresh_fixture

    inputs = simulated_inputs()
    assert inputs.calendar is not None
    inputs = inputs.model_copy(update={"calendar": inputs.calendar.model_copy(update={"timezone": timezone})})
    selection = simulated_selection().model_copy(update={"effective_on": date(2026, 10, 25)})
    reviewed = await reviewed_fixture(selection=selection, source_inputs=inputs)
    fresh = await fresh_fixture(reviewed, source_inputs=inputs, clock=lambda: datetime(2026, 10, 25, 12, tzinfo=UTC))
    assert fresh.evidence_valid_until == datetime.fromisoformat(expected_utc)


@pytest.mark.anyio
@pytest.mark.parametrize("cleanup_source", ["kernel", "lbx"])
async def test_cleanup_crossing_account_midnight_refuses_before_database(cleanup_source: str) -> None:
    from typing import NoReturn

    from app.domains.catalog.publication import publish_mapping

    reviewed = await reviewed_fixture()
    instant = datetime(2026, 10, 16, 20, 59, 59, tzinfo=UTC)
    boundary = datetime(2026, 10, 16, 21, tzinfo=UTC)

    class MidnightCleanup(httpx.MockTransport):
        async def aclose(self) -> None:
            nonlocal instant
            instant = boundary
            await super().aclose()

    def kernel_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=manifest_fixture())

    kernel = MidnightCleanup(kernel_handler) if cleanup_source == "kernel" else httpx.MockTransport(kernel_handler)
    lbx_handler = SelectedOfferRecording().respond
    lbx = MidnightCleanup(lbx_handler) if cleanup_source == "lbx" else httpx.MockTransport(lbx_handler)
    fresh = await fresh_mapping_evaluation(
        operator_settings(),
        proposal=reviewed.proposal,
        approval=reviewed.approval,
        source_inputs=simulated_inputs(),
        principal=f"os-euid:{SIMULATED_UID}",
        clock=lambda: instant,
        kernel_transport=kernel,
        lbx_transport=lbx,
    )
    assert fresh.document.evaluated_at < boundary == instant == fresh.evidence_valid_until

    def forbidden_database() -> NoReturn:
        raise AssertionError("expired cleanup must refuse before a DB session exists")

    with pytest.raises(MappingRefused, match="mapping_publication_evidence_expired"):
        publish_mapping(
            forbidden_database,
            evaluation=fresh.document,
            expected_previous_revision=0,
            deadline=fresh.deadline,
            evidence_valid_until=fresh.evidence_valid_until,
            lock_timeout_seconds=0.2,
            allow_simulated=True,
            clock=lambda: instant,
        )
