"""Local-only purchase sources. The publisher is never invoked on this path."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.composition.mapping_operator import account_billing_date, utc_now
from app.composition.sources import SourceResources
from app.core.settings import AppEnv, Settings
from app.domains.catalog.commercial_offer import CommercialEvidenceMode, CommercialScope
from app.domains.catalog.mapping_evidence import ApprovedMapping, MappingEvidenceMode, evaluate_mapping
from app.domains.purchases.contracts import (
    PurchaseAdmissionProof,
    PurchaseInput,
    PurchaseRefused,
    PurchaseReview,
    SellerEvidence,
)
from app.domains.purchases.service import PurchaseApplication
from app.infrastructure.preflight import PreflightCleanupPending
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.offer_inputs import SelectedOfferInputs, SelectedOfferRequest
from app.integrations.lbx.recorded_offer import recorded_offer_transport
from app.integrations.lbx.selected_offer import read_selected_offer


class SimulatedPurchaseProfile(PurchaseInput):
    schema_version: Literal["SIMULATED-purchase-profile-v1"]
    selection: SelectedOfferRequest
    inputs: SelectedOfferInputs
    seller: SellerEvidence
    recurring_required: bool = Field(strict=True)


def load_profile(configuration: Settings) -> tuple[SimulatedPurchaseProfile, Path]:
    path = configuration.purchase_simulated_profile_file
    if configuration.app_env == AppEnv.PRODUCTION or path is None:
        raise PurchaseRefused("purchase_not_enabled", 503)
    try:
        with path.open("rb") as stream:
            body = stream.read(1048577)
        if len(body) > 1048576:
            raise ValueError("profile too large")
        profile = SimulatedPurchaseProfile.model_validate_json(body)
    except (OSError, ValidationError, ValueError):
        raise PurchaseRefused("purchase_profile_unavailable", 503) from None
    selected = profile.selection
    if (
        (selected.tenant_id, selected.region, selected.external_billing_account_id)
        != (configuration.instance_tenant_id, configuration.instance_region, configuration.mapping_account_id)
        or profile.inputs.source_mode != CommercialEvidenceMode.SIMULATED
        or profile.seller.evidence_mode != "SIMULATED"
    ):
        raise PurchaseRefused("purchase_profile_scope_mismatch", 503)
    return profile, path.parent / "recordings"


async def compare_original_terms(
    configuration: Settings,
    sources: SourceResources,
    review: PurchaseReview,
    profile: SimulatedPurchaseProfile,
    recordings: Path,
    *,
    clock: Callable[[], datetime] = utc_now,
) -> PurchaseAdmissionProof:
    """Fresh complete reads against a separately approved immutable mapping.

    Calendar, currency, quantity and policy originate in a controlled profile,
    never by reconstructing SelectedOfferInputs from a stored selected digest.
    The same comparer can check an original persisted review before unsent work.
    """
    if configuration.app_env == AppEnv.PRODUCTION or review.mapping.evidence_mode != MappingEvidenceMode.SIMULATED:
        raise PurchaseRefused("purchase_real_enablement_unverified", 503)
    document = review.mapping
    scope = document.material.scope
    selection = profile.selection
    if (
        review.seller != profile.seller
        or review.recurring_required != profile.recurring_required
        or (str(selection.tariff_id), str(selection.tariff_service_id), str(selection.period_id))
        != (
            document.material.references.offer,
            document.material.references.component,
            document.material.references.period,
        )
        or scope
        != CommercialScope(
            configuration.instance_tenant_id, configuration.instance_region, configuration.mapping_account_id
        )
    ):
        raise PurchaseRefused("commercial_terms_conflict", 409)
    effective_on = account_billing_date(profile.inputs, account_id=scope.external_billing_account_id, now=clock())
    selection = selection.model_copy(update={"effective_on": effective_on})
    # All credentials and responses are explicit fixtures; even a configured
    # real LBX URL cannot receive a request from this development composition.
    local = configuration.model_copy(
        update={
            "lbx_base_url": "https://purchase-recording.invalid",
            "lbx_external_billing_account_id": scope.external_billing_account_id,
            "lbx_server_username": SecretStr("SIMULATED-purchase-recording"),
            "lbx_server_password": SecretStr("SIMULATED-purchase-recording"),
        }
    )
    client = LbxServerClient(local, transport=recorded_offer_transport(recordings, selection))
    try:
        async with sources.preflight.operation() as budget:
            if effective_on != account_billing_date(
                profile.inputs, account_id=scope.external_billing_account_id, now=clock()
            ):
                raise PurchaseRefused("purchase_effective_date_changed", 409)
            manifest = await sources.require_kernel().fetch_manifest(budget=budget)
            offer = await read_selected_offer(client, selection=selection, inputs=profile.inputs, budget=budget)
            now = clock()
            if effective_on != account_billing_date(
                profile.inputs, account_id=scope.external_billing_account_id, now=now
            ):
                raise PurchaseRefused("purchase_effective_date_changed", 409)
            evaluation = evaluate_mapping(
                manifest=manifest,
                offer=offer,
                technical=document.material.technical,
                approval=ApprovedMapping(
                    schema_version=1,
                    material=document.material,
                    approved_material_hash=document.approved_material_hash,
                    revisions=document.approvals,
                ),
                scope=scope,
                principal=document.publisher_principal,
                reason="SIMULATED: purchase original terms check",
                evaluated_at=now,
                allow_simulated=True,
            )
            budget.check()
            if evaluation.material_fingerprint != document.material_fingerprint:
                raise PurchaseRefused("commercial_terms_conflict", 409)
            assert profile.inputs.calendar is not None  # account_billing_date has proved it
            return PurchaseAdmissionProof(
                mapping=evaluation,
                effective_on=effective_on,
                timezone=profile.inputs.calendar.timezone,
                deadline=budget.work_deadline,
            )
    finally:
        # read_selected_offer drains its counted budget task before returning;
        # never close a shared process admission owner from a single request.
        try:
            async with asyncio.timeout(configuration.preflight_cleanup_timeout_seconds):
                await client.aclose()
        except TimeoutError:
            raise PreflightCleanupPending() from None


def purchase_application(
    configuration: Settings,
    factory: sessionmaker[Session],
    sources: SourceResources | None,
    *,
    clock: Callable[[], datetime] = utc_now,
) -> PurchaseApplication:
    # Loading is lazy: status/replay do not depend on source/profile readiness.
    loaded: tuple[SimulatedPurchaseProfile, Path] | None = None

    def profile() -> tuple[SimulatedPurchaseProfile, Path]:
        nonlocal loaded
        if loaded is None:
            loaded = load_profile(configuration)
        return loaded

    def terms() -> tuple[SellerEvidence, bool]:
        value, _ = profile()
        return value.seller, value.recurring_required

    async def compare(review: PurchaseReview) -> PurchaseAdmissionProof:
        if sources is None:
            raise PurchaseRefused("purchase_sources_unavailable", 503)
        value, directory = profile()
        return await compare_original_terms(configuration, sources, review, value, directory, clock=clock)

    return PurchaseApplication(
        factory,
        scope=CommercialScope(
            configuration.instance_tenant_id, configuration.instance_region, configuration.mapping_account_id
        ),
        allow_simulated=configuration.app_env != AppEnv.PRODUCTION,
        profile_terms=terms,
        fresh_compare=compare,
        clock=clock,
        lock_timeout_seconds=configuration.mapping_lock_timeout_seconds,
    )
