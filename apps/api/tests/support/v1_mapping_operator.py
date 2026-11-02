"""Historical v1 evidence fixture builder. Never imported by Portal runtime."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Literal, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import BaseModel, ValidationError

from app.composition.sources import source_resources
from app.core.settings import AppEnv, Settings
from app.domains.catalog.commercial_offer import CommercialEvidenceBasis, CommercialScope
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
    evidence_valid_until: datetime


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


def utc_now() -> datetime:
    return datetime.now(UTC)


def account_billing_date(inputs: SelectedOfferInputs, *, account_id: str, now: datetime) -> date:
    calendar = inputs.calendar
    if calendar is None:
        raise MappingRefused("mapping_account_calendar_not_configured")
    if calendar.external_billing_account_id != account_id:
        raise MappingRefused("mapping_account_calendar_scope_mismatch")
    if calendar.evidence.basis not in {CommercialEvidenceBasis.ACCOUNT_EVIDENCE, CommercialEvidenceBasis.SIMULATED}:
        raise MappingRefused("mapping_account_calendar_unproven")
    if now.utcoffset() is None:
        raise MappingRefused("mapping_clock_invalid")
    try:
        return now.astimezone(ZoneInfo(calendar.timezone)).date()
    except (ZoneInfoNotFoundError, ValueError):
        raise MappingRefused("mapping_account_calendar_invalid") from None


async def fresh_mapping_evaluation(
    configuration: Settings,
    *,
    proposal: MappingProposal,
    approval: ApprovedMapping,
    source_inputs: SelectedOfferInputs,
    principal: str,
    kernel_transport: httpx.AsyncBaseTransport | None = None,
    lbx_transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], datetime] | None = None,
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
    now = clock if clock is not None else utc_now

    def require_current_date() -> datetime:
        instant = now()
        if selection.effective_on != account_billing_date(
            source_inputs, account_id=scope.external_billing_account_id, now=instant
        ):
            raise MappingRefused("mapping_effective_date_not_current")
        return instant

    require_current_date()
    async with source_resources(configuration, kernel_transport=kernel_transport) as sources:
        lbx = LbxServerClient(configuration, transport=lbx_transport)
        try:
            async with sources.preflight.operation() as budget:
                manifest = await sources.require_kernel().fetch_manifest(budget=budget)
                offer = await read_selected_offer(lbx, selection=selection, inputs=source_inputs, budget=budget)
                # Reads can cross account midnight: refuse, never rewrite the
                # operator's independently approved date.
                evaluated_at = require_current_date()
                budget.check()
                document = evaluate_mapping(
                    manifest=manifest,
                    offer=offer,
                    technical=proposal.technical,
                    approval=approval,
                    scope=scope,
                    principal=principal,
                    reason=proposal.reason,
                    evaluated_at=evaluated_at,
                    allow_simulated=configuration.app_env in {AppEnv.DEVELOPMENT, AppEnv.TEST},
                )
                budget.check()
                # These exclusive calendar bounds have already been validated
                # by the account-date guard and selected-offer normalizer.
                # Carry a transient UTC lease across cleanup/DB work, without
                # changing the approved immutable document or its fingerprint.
                assert source_inputs.calendar is not None and source_inputs.policy is not None
                dates = [selection.effective_on + timedelta(days=1)]
                if source_inputs.policy.valid_until is not None:
                    dates.append(source_inputs.policy.valid_until)
                if offer.terms.period.price_effective_until is not None:
                    dates.append(offer.terms.period.price_effective_until)
                evidence_valid_until = datetime.combine(
                    min(dates), time.min, tzinfo=ZoneInfo(source_inputs.calendar.timezone)
                ).astimezone(UTC)
                result = FreshMappingEvaluation(document, budget.work_deadline, evidence_valid_until)
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
