from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import NoReturn

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.cli import commercial_mappings as cli
from app.composition.mapping_operator import (
    MappingProposal,
    authorize_operator,
    fresh_mapping_evaluation,
    load_operator_input,
)
from app.core.settings import AppEnv
from app.domains.catalog.admission import SelectedCapabilityUnavailable
from app.domains.catalog.commercial_offer import SelectedOfferRefused
from app.domains.catalog.mapping_evidence import (
    ApprovedMapping,
    MappingDocument,
    MappingEvidenceMode,
    MappingMaterial,
    MappingRefused,
    PublicationState,
    TechnicalBinding,
    require_replacement_approval,
)
from app.domains.catalog.publication import query_mapping
from app.infrastructure.preflight import PreflightDeadlineExceeded
from app.integrations.kernel.client import KernelUnavailable
from apps.api.tests.support.commercial_mappings import (
    SIMULATED_OFFER_ID,
    SIMULATED_UID,
    approval_reference,
    fresh_fixture,
    operator_settings,
    reviewed_fixture,
    technical_binding,
)
from apps.api.tests.support.kernel import manifest_fixture, resign
from apps.api.tests.support.lbx_selected_offer import SelectedOfferRecording, simulated_inputs


pytestmark = pytest.mark.usefixtures("mapping_clock")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_operator_authorization_uses_only_effective_numeric_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    config = operator_settings()
    monkeypatch.setenv("USER", str(SIMULATED_UID))
    monkeypatch.setenv("LOGNAME", str(SIMULATED_UID))
    with pytest.raises(MappingRefused, match="mapping_operator_forbidden"):
        authorize_operator(config, resolve_uid=lambda: SIMULATED_UID + 1)
    assert authorize_operator(config, resolve_uid=lambda: SIMULATED_UID) == f"os-euid:{SIMULATED_UID}"
    with pytest.raises(MappingRefused, match="mapping_operator_forbidden"):
        authorize_operator(operator_settings(mapping_operator_uids=()), resolve_uid=lambda: SIMULATED_UID)
    monkeypatch.delattr(os, "geteuid", raising=False)
    with pytest.raises(MappingRefused, match="mapping_operator_identity_unavailable"):
        authorize_operator(config)
    with pytest.raises(MappingRefused, match="mapping_operator_identity_unavailable"):
        authorize_operator(config, resolve_uid=lambda: True)


@pytest.mark.parametrize("uids", [(True,), (-1,), ("29001",), ("*",)])
def test_uid_allowlist_is_strict(uids: tuple[object, ...]) -> None:
    with pytest.raises(ValidationError):
        operator_settings(mapping_operator_uids=uids)


@pytest.mark.parametrize("allowance", [True, 0, -1, "25", 25.0])
def test_allowance_is_an_independently_specified_strict_positive_integer(allowance: object) -> None:
    payload = technical_binding().model_dump()
    payload["allowance"] = allowance
    with pytest.raises(ValidationError):
        TechnicalBinding.model_validate(payload)


def test_cli_has_no_actor_real_or_self_approval_switch() -> None:
    for forbidden in ("--actor=operator", "--real", "--approved"):
        with pytest.raises(SystemExit):
            cli.parser().parse_args(["dry-run", "--proposal=fixture.json", forbidden])


def test_query_database_failure_is_not_a_source_status() -> None:
    from app.domains.catalog.commercial_offer import CommercialScope

    def failing_database() -> NoReturn:
        raise OperationalError("SIMULATED query failure", None, RuntimeError("offline database"))

    with pytest.raises(OperationalError):
        query_mapping(
            failing_database, scope=CommercialScope("anytoolai", "ru", "SIMULATED:account"), offer_id=SIMULATED_OFFER_ID
        )


@pytest.mark.anyio
async def test_fresh_dry_run_and_publish_evaluations_use_real_clients_and_same_material() -> None:
    reviewed = await reviewed_fixture()
    recording = SelectedOfferRecording()
    first = await fresh_fixture(reviewed, recording=recording)
    second = await fresh_fixture(reviewed, recording=recording)
    assert recording.counts == {"tariff": 4, "periods": 4, "services": 4, "prices": 4}
    assert all(request.method == "GET" for request in recording.requests)
    assert first.document.material_fingerprint == second.document.material_fingerprint
    assert first.document.evaluated_at != second.document.evaluated_at
    assert first.document.evidence_mode == MappingEvidenceMode.SIMULATED
    assert first.document.publication_state == PublicationState.SIMULATED
    assert first.document.material.technical.allowance == 25
    assert first.document.material.terms.money.recurring_amount == Decimal("200.02")
    # Decimal remains exact in the serialized operator/storage boundary.
    assert json.loads(first.document.model_dump_json())["material"]["terms"]["money"]["recurring_amount"] == "200.02"


@pytest.mark.anyio
@pytest.mark.parametrize("reread_only", [False, True])
async def test_fresh_operator_evaluation_refuses_an_additional_default_service(reread_only: bool) -> None:
    reviewed = await reviewed_fixture()
    recording = SelectedOfferRecording()
    recording.append_row(
        "services", '{"tariff_id":701,"tariff_service_id":1002,"enabled_by_default":1}', reread_only=reread_only
    )
    with pytest.raises(SelectedOfferRefused, match="selected_offer_additional_default_components_unsupported"):
        await fresh_fixture(reviewed, recording=recording)
    assert all(request.method == "GET" for request in recording.requests)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "change", ["price", "connection_price", "billing_period", "payment_obligations", "renewal", "cancellation"]
)
async def test_changed_legal_terms_require_a_new_legal_version_after_commercial_approval(change: str) -> None:
    original = await reviewed_fixture()
    previous = (await fresh_fixture(original)).document
    recording = SelectedOfferRecording()
    inputs = simulated_inputs()
    assert inputs.policy is not None
    if change in {"price", "connection_price"}:
        old, new = (
            ('"price":100.01', '"price":120.01')
            if change == "price"
            else ('"connection_price":7.03', '"connection_price":8.03')
        )
        for name in ("services", "prices"):
            recording.replace(name, old, new)
    elif change == "billing_period":
        for name in ("periods", "prices"):
            recording.replace(name, '"period_length":1', '"period_length":2')
    elif change == "payment_obligations":
        recording.replace("tariff", '"block_to_close_days":30', '"block_to_close_days":20')
    else:
        field = "renewal_terms" if change == "renewal" else "cancellation_terms"
        inputs = inputs.model_copy(
            update={"policy": inputs.policy.model_copy(update={field: "SIMULATED revised terms"})}
        )
    replacement = await reviewed_fixture(recording=recording, source_inputs=inputs, revision="fixture-v2")
    old_legal = replacement.approval.model_copy(
        update={
            "revisions": replacement.approval.revisions.model_copy(update={"legal": original.approval.revisions.legal})
        }
    )
    candidate = await fresh_fixture(replace(replacement, approval=old_legal), recording=recording, source_inputs=inputs)
    assert candidate.document.approvals.commercial != previous.approvals.commercial
    with pytest.raises(MappingRefused, match="mapping_legal_reapproval_required"):
        require_replacement_approval(previous, candidate.document)
    approved = await fresh_fixture(replacement, recording=recording, source_inputs=inputs)
    require_replacement_approval(previous, approved.document)


@pytest.mark.anyio
async def test_technical_only_change_keeps_legal_approval_and_technical_guard() -> None:
    original = await reviewed_fixture()
    previous = (await fresh_fixture(original)).document
    replacement = await reviewed_fixture(allowance=26)
    candidate = (await fresh_fixture(replacement)).document
    with pytest.raises(MappingRefused, match="mapping_technical_reapproval_required"):
        require_replacement_approval(previous, candidate)
    revisions = replacement.approval.revisions.model_copy(
        update={"technical": approval_reference("technical", "fixture-v2")}
    )
    replacement = replace(replacement, approval=replacement.approval.model_copy(update={"revisions": revisions}))
    candidate = (await fresh_fixture(replacement)).document
    assert candidate.approvals.legal == previous.approvals.legal
    require_replacement_approval(previous, candidate)


@pytest.mark.anyio
async def test_evidence_only_change_requires_commercial_but_keeps_legal_version() -> None:
    original = await reviewed_fixture()
    previous = (await fresh_fixture(original)).document
    inputs = simulated_inputs()
    assert inputs.policy is not None and inputs.policy.list_completeness is not None
    proof = inputs.policy.list_completeness.model_copy(update={"revision": "test-2"})
    inputs = inputs.model_copy(update={"policy": inputs.policy.model_copy(update={"list_completeness": proof})})
    replacement = await reviewed_fixture(source_inputs=inputs)
    candidate = (await fresh_fixture(replacement, source_inputs=inputs)).document
    assert candidate.material.terms == previous.material.terms
    assert candidate.material.selected_evidence_digest != previous.material.selected_evidence_digest
    with pytest.raises(MappingRefused, match="mapping_commercial_reapproval_required"):
        require_replacement_approval(previous, candidate)
    revisions = replacement.approval.revisions.model_copy(
        update={"commercial": approval_reference("commercial", "fixture-v2")}
    )
    replacement = replace(replacement, approval=replacement.approval.model_copy(update={"revisions": revisions}))
    candidate = (await fresh_fixture(replacement, source_inputs=inputs)).document
    assert candidate.approvals.legal == previous.approvals.legal
    require_replacement_approval(previous, candidate)


@pytest.mark.anyio
async def test_offer_identity_includes_service_and_period_without_rewriting_source_references() -> None:
    material = (await reviewed_fixture()).approval.material
    assert material.billing_offer_id == SIMULATED_OFFER_ID
    assert (material.references.offer, material.references.component, material.references.period) == (
        "701",
        "1001",
        "901",
    )
    assert "billing_offer_id" not in material.model_dump()
    other_service = material.model_copy(update={"references": replace(material.references, component="1002")})
    other_period = material.model_copy(update={"references": replace(material.references, period="902")})
    assert len({material.billing_offer_id, other_service.billing_offer_id, other_period.billing_offer_id}) == 3
    first = material.model_copy(update={"references": replace(material.references, offer="a:b", component="c")})
    second = material.model_copy(update={"references": replace(material.references, offer="a", component="b:c")})
    assert first.billing_offer_id != second.billing_offer_id


@pytest.mark.anyio
async def test_unrelated_manifest_changes_and_observations_are_not_material() -> None:
    reviewed = await reviewed_fixture()
    first = await fresh_fixture(reviewed)
    payload = manifest_fixture()
    unrelated = next(item for item in payload["products"] if item["product_id"] != "proposal_ai")
    unrelated["enabled"] = not unrelated["enabled"]
    payload["generated_at"] = "2026-10-19T01:00:00Z"
    resign(payload)
    second = await fresh_fixture(reviewed, manifest=payload)
    assert first.document.manifest_version != second.document.manifest_version
    assert first.document.material_fingerprint == second.document.material_fingerprint


@pytest.mark.anyio
async def test_large_exponent_source_money_serializes_and_revalidates_exactly() -> None:
    recording = SelectedOfferRecording()
    for name in ("services", "prices"):
        recording.replace(name, '"price":100.01', '"price":1e30')
    reviewed = await reviewed_fixture(recording=recording)
    fresh = await fresh_fixture(reviewed, recording=recording)
    payload = json.loads(fresh.document.model_dump_json())
    assert payload["material"]["terms"]["money"]["recurring_amount"] == "2" + "0" * 30
    assert MappingDocument.model_validate_json(json.dumps(payload)) == fresh.document


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("money", "recurring_unit_amount", 100.01),
        ("money", "connection_amount", 14.06),
        ("quantity", "selected", 2),
        ("quantity", "selected", True),
        ("period", "length", "1"),
        ("period", "price_effective_from", "2026-02-30"),
        ("period", "price_effective_until", "invalid-date"),
        ("period", "unrecognized_field", "unsupported"),
    ],
)
async def test_terms_json_decoding_preserves_strict_types_and_field_validation(
    section: str,
    field: str,
    value: object,
) -> None:
    reviewed = await reviewed_fixture()
    payload = json.loads(reviewed.approval.material.model_dump_json())
    payload["terms"][section][field] = value
    with pytest.raises(ValidationError):
        MappingMaterial.model_validate_json(json.dumps(payload))


@pytest.mark.anyio
async def test_changed_source_or_technical_meaning_cannot_reuse_old_approval() -> None:
    reviewed = await reviewed_fixture()
    changed = SelectedOfferRecording()
    for name in ("services", "prices"):
        changed.replace(name, '"price":100.01', '"price":101.01')
    with pytest.raises(MappingRefused, match="mapping_approved_material_mismatch"):
        await fresh_fixture(reviewed, recording=changed)
    proposal = reviewed.proposal.model_copy(update={"technical": technical_binding(26)})
    with pytest.raises(MappingRefused, match="mapping_approved_material_mismatch"):
        await fresh_mapping_evaluation(
            operator_settings(),
            proposal=proposal,
            approval=reviewed.approval,
            source_inputs=simulated_inputs(),
            principal=f"os-euid:{SIMULATED_UID}",
            kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=manifest_fixture())),
            lbx_transport=httpx.MockTransport(SelectedOfferRecording().respond),
        )


@pytest.mark.anyio
async def test_disabled_selected_metric_is_refused() -> None:
    reviewed = await reviewed_fixture()
    payload = manifest_fixture()
    next(item for item in payload["usage_metrics"] if item["metric_key"] == "proposal_ai.test_generations")[
        "enabled"
    ] = False
    with pytest.raises(SelectedCapabilityUnavailable, match="selected_metric_disabled"):
        await fresh_fixture(reviewed, manifest=resign(payload))


@pytest.mark.anyio
async def test_approval_schema_money_and_stored_mode_are_strict(tmp_path: Path) -> None:
    reviewed = await reviewed_fixture()
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(reviewed.approval.model_dump_json(), encoding="utf-8")
    assert load_operator_input(approval_path, ApprovedMapping) == reviewed.approval
    payload = json.loads(reviewed.approval.model_dump_json())
    payload["material"]["terms"]["money"]["recurring_amount"] = 200.02
    approval_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MappingRefused, match="mapping_input_invalid"):
        load_operator_input(approval_path, ApprovedMapping)
    with pytest.raises(MappingRefused, match="mapping_input_not_configured"):
        load_operator_input(None, ApprovedMapping)
    evaluation = (await fresh_fixture(reviewed)).document
    for mode in ("GENUINE", "unknown"):
        payload = json.loads(evaluation.model_dump_json())
        payload["evidence_mode"] = mode
        with pytest.raises(ValidationError):
            MappingDocument.model_validate_json(json.dumps(payload))
    # Proposal is a separate boundary; no approval boolean is accepted there.
    payload = json.loads(reviewed.proposal.model_dump_json())
    payload["approved"] = True
    with pytest.raises(ValidationError):
        MappingProposal.model_validate_json(json.dumps(payload))


@pytest.mark.anyio
async def test_source_failure_and_production_gate_never_fall_back() -> None:
    reviewed = await reviewed_fixture()
    with pytest.raises(KernelUnavailable):
        await fresh_mapping_evaluation(
            operator_settings(),
            proposal=reviewed.proposal,
            approval=reviewed.approval,
            source_inputs=simulated_inputs(),
            principal=f"os-euid:{SIMULATED_UID}",
            kernel_transport=httpx.MockTransport(lambda request: httpx.Response(503)),
            lbx_transport=httpx.MockTransport(SelectedOfferRecording().respond),
        )
    switched = operator_settings().model_copy(update={"app_env": AppEnv.PRODUCTION})
    with pytest.raises(MappingRefused, match="mapping_real_enablement_unverified"):
        await fresh_fixture(reviewed, configuration=switched)


@pytest.mark.anyio
async def test_kernel_and_selected_lbx_reads_share_one_nonrenewable_budget() -> None:
    reviewed = await reviewed_fixture()
    recording = SelectedOfferRecording()

    async def kernel_response(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.03)
        return httpx.Response(200, json=manifest_fixture())

    async def lbx_response(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.03)
        return recording.respond(request)

    with pytest.raises(PreflightDeadlineExceeded):
        await fresh_mapping_evaluation(
            operator_settings(preflight_total_timeout_seconds=0.1, preflight_cleanup_timeout_seconds=0.01),
            proposal=reviewed.proposal,
            approval=reviewed.approval,
            source_inputs=simulated_inputs(),
            principal=f"os-euid:{SIMULATED_UID}",
            kernel_transport=httpx.MockTransport(kernel_response),
            lbx_transport=httpx.MockTransport(lbx_response),
        )
    assert sum(recording.counts.values()) < 8
