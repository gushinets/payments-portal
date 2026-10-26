"""Named SIMULATED external approval setup, never imported by Portal runtime.

This test-only fixture review is separate from every attempted fresh operation.
The publisher cannot create approval from its reads. Changed-source tests keep
this original approved fixture unless explicitly simulating a second review.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from apps.api.tests.support.v1_mapping_operator import FreshMappingEvaluation, MappingProposal, fresh_mapping_evaluation
from app.core.settings import Settings
from app.domains.catalog.commercial_offer import commercial_digest
from app.domains.catalog.mapping_evidence import (
    ApprovalBasis,
    ApprovalReference,
    ApprovalRevisions,
    ApprovedMapping,
    MappingMaterial,
    TechnicalBinding,
)
from app.integrations.lbx.offer_inputs import SelectedOfferInputs, SelectedOfferRequest
from app.integrations.lbx.selected_offer import read_selected_offer
from apps.api.tests.support.kernel import TOKEN, manifest_fixture
from apps.api.tests.support.lbx import ACCOUNT, lbx_settings, lbx_source
from apps.api.tests.support.lbx_selected_offer import SelectedOfferRecording, simulated_inputs, simulated_selection


SIMULATED_UID = 29001
SIMULATED_OFFER_ID = "selected-offer:v1:701:1001:901"


class HistoricalOperatorSettings(Settings):
    """v1 fixture-file harness only. These inputs are absent from runtime Settings."""

    mapping_account_id: str = ACCOUNT
    mapping_approval_file: Path | None = None
    mapping_source_inputs_file: Path | None = None

    @property
    def lbx_external_billing_account_id(self) -> str:
        # Explicit historical SIMULATED fixture identity. Not runtime config.
        return self.mapping_account_id


def operator_settings(**overrides: Any) -> Settings:
    values = {
        "kernel_base_url": "http://kernel-client.test",
        "kernel_service_token": TOKEN,
        "kernel_max_retries": 0,
        "kernel_mock_enabled": overrides.get("app_env") != "production",
        "mapping_operator_uids": (SIMULATED_UID,),
        "mapping_account_id": ACCOUNT,
        **overrides,
    }
    configuration = lbx_settings(**values)
    return HistoricalOperatorSettings(_env_file=None, **{**configuration.model_dump(), **values})


def technical_binding(allowance: int = 25) -> TechnicalBinding:
    return TechnicalBinding(
        product_id="proposal_ai",
        metric_key="proposal_ai.test_generations",
        unit="generation",
        allowance=allowance,
        metric_basis=ApprovalBasis.SIMULATED,
    )


def approval_reference(name: str, revision: str = "fixture-v1") -> ApprovalReference:
    return ApprovalReference(
        reference="SIMULATED:" + name,
        revision=revision,
        content_hash=commercial_digest("SIMULATED:" + name + ":" + revision),
        basis=ApprovalBasis.SIMULATED,
    )


@dataclass(frozen=True)
class ApprovedFixture:
    proposal: MappingProposal
    approval: ApprovedMapping


async def reviewed_fixture(
    *,
    allowance: int = 25,
    recording: SelectedOfferRecording | None = None,
    revision: str = "fixture-v1",
    selection: SelectedOfferRequest | None = None,
    source_inputs: SelectedOfferInputs | None = None,
) -> ApprovedFixture:
    recorded = recording if recording is not None else SelectedOfferRecording()
    selected = selection if selection is not None else simulated_selection()
    inputs = source_inputs if source_inputs is not None else simulated_inputs()
    async with lbx_source(httpx.MockTransport(recorded.respond)) as (client, owner):
        async with owner.operation() as budget:
            offer = await read_selected_offer(client, selection=selected, inputs=inputs, budget=budget)
    technical = technical_binding(allowance)
    material = MappingMaterial(
        scope=offer.scope,
        references=offer.references,
        terms=offer.terms,
        technical=technical,
        digest_scope="selected_offer",
        selected_evidence_digest=offer.selected_evidence_digest,
        component_classification="CAPABILITY_BEARING",
        external_usage_reporting="none",
    )
    return ApprovedFixture(
        MappingProposal(
            schema_version=1,
            selection=selected,
            technical=technical,
            reason="SIMULATED: reviewed fixture publication",
        ),
        ApprovedMapping(
            schema_version=1,
            material=material,
            approved_material_hash=commercial_digest(material.canonical_json()),
            revisions=ApprovalRevisions(
                technical=approval_reference("technical", revision),
                commercial=approval_reference("commercial", revision),
                legal=approval_reference("legal", revision),
            ),
        ),
    )


async def fresh_fixture(
    reviewed: ApprovedFixture,
    *,
    recording: SelectedOfferRecording | None = None,
    manifest: dict[str, Any] | None = None,
    configuration: Settings | None = None,
    source_inputs: SelectedOfferInputs | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FreshMappingEvaluation:
    recorded = recording if recording is not None else SelectedOfferRecording()
    payload = manifest if manifest is not None else manifest_fixture()
    return await fresh_mapping_evaluation(
        configuration if configuration is not None else operator_settings(),
        proposal=reviewed.proposal,
        approval=reviewed.approval,
        source_inputs=source_inputs if source_inputs is not None else simulated_inputs(),
        principal=f"os-euid:{SIMULATED_UID}",
        clock=clock,
        kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
        lbx_transport=httpx.MockTransport(recorded.respond),
    )
