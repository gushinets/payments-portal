"""Local-only purchase sources. The publisher is never invoked on this path."""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.composition.mapping_operator import account_billing_date, utc_now
from app.composition.sources import SourceResources
from app.core.settings import AppEnv, Settings
from app.domains.catalog.commercial_offer import (
    CommercialEvidenceMode,
    CommercialScope,
    SelectedCommercialOffer,
    canonical_document,
    commercial_digest,
)
from app.domains.catalog.mapping_evidence import ApprovedMapping, MappingEvidenceMode, evaluate_mapping
from app.domains.purchases.contracts import (
    PurchaseAdmissionProof,
    PurchaseInput,
    PurchaseRefused,
    PurchaseReview,
    SellerEvidence,
    AcceptedPurchase,
)
from app.domains.purchases.preparation import PreparationContext, PurchasePreparation
from app.domains.purchases.preparation_contracts import PreparationEvidence, PreparationGateway
from app.domains.purchases.service import PurchaseApplication
from app.domains.purchases.widget import WidgetApplication, WidgetBootstrap, WidgetProofInput
from app.infrastructure.preflight import PreflightBudget, PreflightCleanupPending
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.offer_inputs import SelectedOfferInputs, SelectedOfferRequest
from app.integrations.lbx.recorded_offer import recorded_offer_transport
from app.integrations.lbx.selected_offer import read_selected_offer
from app.integrations.lbx.preparation_profile import PreparationProfile
from app.integrations.lbx.preparation_dto import NewServiceInfo, PostAgreement, PostSubscription, PostUser
from app.integrations.lbx.purchase_preparation import LbxPurchasePreparation, PreparationRecord
from app.integrations.lbx.recorded_preparation import RecordedPreparationTransport
from app.models import ExternalCreateOperationKind


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


def preparation_fingerprint(profile: PreparationProfile) -> str:
    # The account-local start date is determined at admission. Every stable
    # preparation parameter, including activation and service selection, is pinned.
    return commercial_digest(
        canonical_document(
            {
                "schema": "purchase-preparation-terms-v1",
                "profile": profile.model_dump(
                    mode="json", exclude={"server_username": True, "selection": {"effective_on"}}
                ),
            }
        )
    )


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

    def preparation_profile() -> PreparationProfile:
        value, directory = profile()
        try:
            with (directory.parent / "preparation.json").open("rb") as stream:
                body = stream.read(1048577)
            if len(body) > 1048576:
                raise ValueError("profile too large")
            preparation = PreparationProfile.model_validate_json(body)
        except (OSError, ValueError):
            raise PurchaseRefused("purchase_preparation_profile_unavailable", 503) from None
        if (
            preparation.selection != value.selection
            or preparation.inputs != value.inputs
            or preparation.organization_id != value.seller.organization_id
            or preparation.server_origin != "https://purchase-recording.invalid"
            or preparation.server_username != SecretStr("SIMULATED-purchase-recording")
        ):
            raise PurchaseRefused("purchase_preparation_profile_conflict", 409)
        return preparation

    def terms() -> tuple[SellerEvidence, bool, str]:
        value, _ = profile()
        return value.seller, value.recurring_required, preparation_fingerprint(preparation_profile())

    async def compare(review: PurchaseReview) -> PurchaseAdmissionProof:
        if preparation_fingerprint(preparation_profile()) != review.preparation_fingerprint:
            raise PurchaseRefused("commercial_terms_conflict", 409)
        if sources is None:
            raise PurchaseRefused("purchase_sources_unavailable", 503)
        value, directory = profile()
        return await compare_original_terms(configuration, sources, review, value, directory, clock=clock)

    def make_record(
        context: PreparationContext, kind: ExternalCreateOperationKind, correlation: str
    ) -> PreparationRecord:
        preparation = preparation_profile()
        if preparation_fingerprint(preparation) != context.accepted.review.preparation_fingerprint:
            raise PurchaseRefused("commercial_terms_conflict", 409)
        preparation = preparation.model_copy(
            update={
                "selection": preparation.selection.model_copy(
                    update={"effective_on": context.accepted.admission.effective_on}
                )
            }
        )
        customer = PostUser(type=preparation.customer_type, outer_id=context.customer_key, email=context.email)
        preparation.require_customer(customer)
        agreement = None
        subscription = None
        if kind != ExternalCreateOperationKind.CUSTOMER:
            if context.provider_customer_id is None:
                raise PurchaseRefused("purchase_customer_identity_unproven", 409)
            if kind == ExternalCreateOperationKind.AGREEMENT:
                offer_doc = next((doc for doc in context.accepted.review.documents if doc.doc_type == "offer"), None)
                if offer_doc is None:
                    raise PurchaseRefused("purchase_legal_unavailable", 503)
                agreement = PostAgreement(
                    user_id=int(context.provider_customer_id),
                    organization_id=preparation.organization_id,
                    agreement_number=correlation,
                    agreement_link=offer_doc.url_path,
                    create_date=context.accepted.admission.effective_on,
                    is_offer=preparation.is_offer,
                    debt_threshold=Decimal(0),
                )
            else:
                if context.agreement_record is None or context.agreement_id is None:
                    raise PurchaseRefused("purchase_agreement_unproven", 409)
                agreement = PreparationRecord.model_validate_json(
                    json.dumps(context.agreement_record.storage_document())
                ).agreement
                subscription = PostSubscription(
                    agreement_id=int(context.agreement_id),
                    tariff_id=preparation.selection.tariff_id,
                    period_id=preparation.selection.period_id,
                    subscription_start_date=f"{context.accepted.admission.effective_on} {preparation.start_time}",
                    activate_by_balance=preparation.activate_by_balance,
                    activate_manually=preparation.activate_manually,
                    demo_period_length=preparation.demo_period_length,
                    outer_id=correlation,
                    services=[
                        NewServiceInfo(
                            tariff_service_id=preparation.selection.tariff_service_id,
                            multiplicator=int(preparation.selection.commercial_quantity),
                        )
                    ]
                    if preparation.service_composition == "explicit_single"
                    else None,
                )
        return PreparationRecord(profile=preparation, customer=customer, agreement=agreement, subscription=subscription)

    @asynccontextmanager
    async def gateway(
        evidence: PreparationEvidence, accepted: AcceptedPurchase
    ) -> AsyncIterator[tuple[PreparationGateway, PreflightBudget]]:
        record = PreparationRecord.model_validate_json(json.dumps(evidence.storage_document()))
        if sources is None or configuration.app_env == AppEnv.PRODUCTION:
            raise PurchaseRefused("purchase_not_enabled", 503)
        # Recovery uses persisted original commands/profile. It neither reads
        # Kernel nor reloads the current admission profile or policy file.
        path = configuration.purchase_simulated_profile_file
        if path is None:
            raise PurchaseRefused("purchase_not_enabled", 503)
        substitutions = {
            "SIMULATED-persisted-customer-key": record.customer.outer_id,
            "2026-10-16": record.profile.selection.effective_on.isoformat(),
        }
        if record.agreement is not None:
            substitutions["SIMULATED-held-purchase-reference"] = record.agreement.agreement_number
            substitutions["https://portal.example.invalid/terms/simulated"] = record.agreement.agreement_link
        if record.subscription is not None:
            substitutions["SIMULATED-subscription-hint"] = record.subscription.outer_id
        local = configuration.model_copy(
            update={
                "lbx_base_url": record.profile.server_origin,
                "lbx_external_billing_account_id": accepted.external_billing_account_id,
                "lbx_server_username": SecretStr("SIMULATED-purchase-recording"),
                "lbx_server_password": SecretStr("SIMULATED-purchase-recording"),
            }
        )
        document = accepted.review.mapping
        material = document.material
        offer = SelectedCommercialOffer(
            material.scope,
            material.references,
            material.terms,
            document.lbx_evidence_mode,
            material.digest_scope,
            material.selected_evidence_digest,
            document.selected_evidence_json,
            document.field_sources,
            document.observations,
        )
        client = LbxServerClient(
            local,
            transport=RecordedPreparationTransport(
                path.parent / "recordings", record.profile, substitutions=substitutions
            ),
        )
        try:
            async with sources.purchase_io.operation() as budget:
                yield LbxPurchasePreparation(client, record, offer), budget
        finally:
            async with asyncio.timeout(configuration.preflight_cleanup_timeout_seconds):
                await client.aclose()

    scope = CommercialScope(
        configuration.instance_tenant_id, configuration.instance_region, configuration.mapping_account_id
    )
    preparation = PurchasePreparation(
        factory,
        scope=scope,
        fresh_compare=compare,
        make_record=make_record,
        decode_record=PreparationRecord.model_validate_json,
        gateway=gateway,
        clock=clock,
    )

    def issue_widget(proof: WidgetProofInput) -> WidgetBootstrap:
        if (
            configuration.app_env == AppEnv.PRODUCTION
            or configuration.purchase_simulated_profile_file is None
            or proof.accepted.review.mapping.evidence_mode != MappingEvidenceMode.SIMULATED
        ):
            raise PurchaseRefused("billing_not_ready", 503)
        # Deliberately not a JWT. A real signing key in runtime settings has no
        # effect on this isolated stub path. Real account/SDK enablement remains blocked.
        return WidgetBootstrap("SIMULATED:" + secrets.token_urlsafe(32))

    return PurchaseApplication(
        factory,
        scope=scope,
        allow_simulated=configuration.app_env != AppEnv.PRODUCTION,
        profile_terms=terms,
        fresh_compare=compare,
        clock=clock,
        lock_timeout_seconds=configuration.mapping_lock_timeout_seconds,
        preparation=preparation,
        widget=WidgetApplication(
            factory,
            scope=scope,
            decode_record=PreparationRecord.model_validate_json,
            gateway=gateway,
            clock=clock,
            issue=issue_widget,
        ),
    )
