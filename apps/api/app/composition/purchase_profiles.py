"""Lazy local purchase profiles and immutable preparation fingerprinting."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from app.core.settings import AppEnv, Settings
from app.domains.catalog.commercial_offer import canonical_document, commercial_digest
from app.domains.purchases.contracts import PurchaseInput, PurchaseRefused, SellerEvidence
from app.integrations.lbx.offer_inputs import SelectedOfferInputs, SelectedOfferRequest
from app.integrations.lbx.preparation_profile import PreparationProfile
from app.integrations.lbx.stand import Stand043Permission


class SimulatedPurchaseProfile(PurchaseInput):
    schema_version: Literal["SIMULATED-purchase-profile-v1", "LOCAL-043-purchase-profile-v1"]
    selection: SelectedOfferRequest
    inputs: SelectedOfferInputs
    seller: SellerEvidence
    recurring_required: bool = Field(strict=True)


def test_recordings(configuration: Settings) -> bool:
    return (
        configuration.app_env == AppEnv.TEST
        and configuration.purchase_simulated_profile_file is not None
        and not configuration.lbx043_enabled
        and configuration.purchase_stand_profile_file is None
    )


def load_profile(configuration: Settings) -> tuple[SimulatedPurchaseProfile, Path]:
    recorded = test_recordings(configuration)
    if not recorded:
        Stand043Permission.configured(configuration)
    path = configuration.purchase_simulated_profile_file if recorded else configuration.purchase_stand_profile_file
    if path is None:
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
        or profile.inputs.source_mode != ("SIMULATED" if recorded else "CONFIGURED_SOURCE")
        or profile.seller.evidence_mode != ("SIMULATED" if recorded else "CONFIGURED_SOURCE")
        or profile.schema_version != ("SIMULATED-purchase-profile-v1" if recorded else "LOCAL-043-purchase-profile-v1")
        or (
            not recorded
            and (
                (selected.tariff_id, selected.tariff_service_id, selected.period_id) != (32, 1, 1)
                or selected.commercial_quantity != 1
                or profile.seller.organization_id != 21
            )
        )
    ):
        raise PurchaseRefused("purchase_profile_scope_mismatch", 503)
    return profile, path.parent / "recordings"


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
