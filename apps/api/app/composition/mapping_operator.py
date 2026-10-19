"""Restricted operator composition; fixtures/transports are injected only here."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.composition.sources import source_resources
from app.core.settings import AppEnv, Settings
from app.domains.catalog.commercial_offer import CommercialScope
from app.domains.catalog.mapping_evidence import (
    ApprovedMapping,
    ImmutableInput,
    MappingDocument,
    MappingRefused,
    Nonempty,
    TechnicalBinding,
    evaluate_mapping,
)
from app.infrastructure.preflight import PreflightCleanupPending
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.offer_inputs import SelectedOfferInputs, SelectedOfferRequest
from app.integrations.lbx.selected_offer import read_selected_offer


MAX_OPERATOR_INPUT_BYTES = 1048576
ModelT = TypeVar("ModelT", bound=BaseModel)


class MappingProposal(ImmutableInput):
    schema_version: Literal[1]
    selection: SelectedOfferRequest
    technical: TechnicalBinding
    reason: Nonempty


@dataclass(frozen=True)
class FreshMappingEvaluation:
    document: MappingDocument
    deadline: float


def authorize_operator(configuration: Settings, *, resolve_uid: Callable[[], int] | None = None) -> str:
    """Composition-only injection for tests; no actor/username/approval flag."""
    resolver = resolve_uid if resolve_uid is not None else getattr(os, "geteuid", None)
    if resolver is None:
        raise MappingRefused("mapping_operator_identity_unavailable")
    try:
        uid = resolver()
    except OSError:
        raise MappingRefused("mapping_operator_identity_unavailable") from None
    if type(uid) is not int or uid < 0:
        raise MappingRefused("mapping_operator_identity_unavailable")
    if uid not in configuration.mapping_operator_uids:
        raise MappingRefused("mapping_operator_forbidden")
    return f"os-euid:{uid}"


def configured_mapping_scope(configuration: Settings) -> CommercialScope:
    if not configuration.mapping_account_id:
        raise MappingRefused("mapping_account_not_configured")
    return CommercialScope(
        configuration.instance_tenant_id, configuration.instance_region, configuration.mapping_account_id
    )


def load_operator_input(path: Path | None, model: type[ModelT]) -> ModelT:
    if path is None:
        raise MappingRefused("mapping_input_not_configured")
    try:
        with path.open("rb") as stream:
            body = stream.read(MAX_OPERATOR_INPUT_BYTES + 1)
        if len(body) > MAX_OPERATOR_INPUT_BYTES:
            raise MappingRefused("mapping_input_too_large")
        return model.model_validate_json(body)
    except (OSError, ValidationError, ValueError):
        raise MappingRefused("mapping_input_invalid") from None


async def fresh_mapping_evaluation(
    configuration: Settings,
    *,
    proposal: MappingProposal,
    approval: ApprovedMapping,
    source_inputs: SelectedOfferInputs,
    principal: str,
    kernel_transport: httpx.AsyncBaseTransport | None = None,
    lbx_transport: httpx.AsyncBaseTransport | None = None,
) -> FreshMappingEvaluation:
    """Outer I/O only; one fresh deadline precedes admission and both sources.

    Returns a neutral evaluation to synchronous Application. No Session exists
    here. The command owns a single event loop, then runs DB work synchronously.
    Configured LBX reads can be real; provisional Kernel always taints the result.
    """
    scope = configured_mapping_scope(configuration)
    selection = proposal.selection
    if (selection.tenant_id, selection.region, selection.external_billing_account_id) != (
        scope.tenant_id,
        scope.region,
        scope.external_billing_account_id,
    ) or configuration.lbx_external_billing_account_id != scope.external_billing_account_id:
        raise MappingRefused("mapping_scope_mismatch")
    if configuration.app_env == AppEnv.PRODUCTION:
        # No trusted genuine producer/release composition exists yet (G1-G4).
        raise MappingRefused("mapping_real_enablement_unverified")
    async with source_resources(configuration, kernel_transport=kernel_transport) as sources:
        lbx = LbxServerClient(configuration, transport=lbx_transport)
        try:
            async with sources.preflight.operation() as budget:
                manifest = await sources.require_kernel().fetch_manifest(budget=budget)
                offer = await read_selected_offer(lbx, selection=selection, inputs=source_inputs, budget=budget)
                budget.check()
                document = evaluate_mapping(
                    manifest=manifest,
                    offer=offer,
                    technical=proposal.technical,
                    approval=approval,
                    scope=scope,
                    principal=principal,
                    reason=proposal.reason,
                    evaluated_at=datetime.now(UTC),
                    allow_simulated=configuration.app_env in {AppEnv.DEVELOPMENT, AppEnv.TEST},
                )
                budget.check()
                result = FreshMappingEvaluation(document, budget.work_deadline)
            return result
        finally:
            # Drain the same owner before closing either pool. If cleanup remains
            # counted, propagate refusal and retain resources, as in Steps 2/3.
            await sources.preflight.aclose()
            try:
                async with asyncio.timeout(configuration.preflight_cleanup_timeout_seconds):
                    await lbx.aclose()
            except TimeoutError:
                raise PreflightCleanupPending() from None
