"""043-shaped protocol fixtures ONLY. No socket, live proof or vendor probe."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from app.core.settings import AppEnv, Settings
from app.domains.catalog.commercial_offer import CommercialScope, SelectedCommercialOffer, commercial_digest
from app.domains.catalog.mapping_evidence import (
    ApprovedMapping,
    ApprovalRevisions,
    MappingDocument,
    MappingMaterial,
    evaluate_mapping,
)
from app.integrations.lbx.client import API_PATH, LbxServerClient
from app.integrations.lbx.preparation_profile import PreparationProfile
from app.integrations.lbx.selected_offer import read_selected_offer
from app.integrations.lbx.stand import STAND_ORIGIN, Stand043Permission
from app.infrastructure.preflight import PreflightAdmission
from apps.api.tests.support.commercial_mappings import approval_reference, technical_binding
from apps.api.tests.support.kernel import manifest_fixture
from app.integrations.kernel.client import _decode_manifest
from app.domains.catalog.contracts import SourceProvenance
from apps.api.tests.support.lbx import admission, lbx_settings
from apps.api.tests.support.lbx_preparation import DIRECTORY


ACCOUNT = "local-043-fixture-account"
PORTAL_USER_ID = UUID("70900000-0000-4000-8000-000000000006")
NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


def configured_profile() -> PreparationProfile:
    value = json.loads((DIRECTORY / "preparation.json").read_bytes())

    def convert(node: Any) -> Any:
        if isinstance(node, dict):
            return {
                key: (
                    "CONFIGURED_SOURCE"
                    if key == "source_mode"
                    else ACCOUNT
                    if key == "external_billing_account_id"
                    else "ACCOUNT_EVIDENCE"
                    if key == "basis"
                    else 32
                    if key == "tariff_id"
                    else 1
                    if key in {"tariff_service_id", "period_id", "currency_id"}
                    else "1"
                    if key == "commercial_quantity"
                    else convert(item)
                )
                for key, item in node.items()
            }
        if isinstance(node, list):
            return [convert(item) for item in node]
        return node.replace("SIMULATED:", "TEST-ONLY:") if isinstance(node, str) else node

    value = convert(value)
    value.update(
        schema_version="LOCAL-043-lbx-preparation-v1",
        server_origin=STAND_ORIGIN,
        server_username="test-only-server-user",
        is_offer=False,
        lawful_customer_fields=["type", "email", "login", "password", "user_surname", "user_name", "user_patronymic"],
        currency_mapping={
            "external_billing_account_id": ACCOUNT,
            "currency_id": 1,
            "iso_currency": "RUB",
            "source_units": "major",
            "decimal_places": 2,
        },
        financial_policy_evidence={
            "reference": "TEST-ONLY:reviewed-no-credit-activation-risk",
            "revision": "fixture-v1",
            "basis": "ACCOUNT_EVIDENCE",
        },
    )
    return PreparationProfile.model_validate_json(json.dumps(value))


def stand_settings(**overrides: Any) -> Settings:
    return lbx_settings(
        **{
            "app_env": AppEnv.DEVELOPMENT,
            "lbx_base_url": STAND_ORIGIN,
            "lbx_server_username": "test-only-server-user",
            "lbx_external_billing_account_id": ACCOUNT,
            "mapping_account_id": ACCOUNT,
            "lbx_seller_organization_id": 21,
            "lbx043_enabled": True,
            "lbx_widget_signing_secret": "test-only-widget-secret-at-least-32-bytes",
            "lbx043_test_user_ids": (PORTAL_USER_ID,),
            "lbx043_financial_approval_reference": "TEST-ONLY:operator-reviewed-test-risk",
            "purchase_stand_profile_file": Path("/not-read-by-protocol-test/profile.json"),
            **overrides,
        }
    )


class StandRecording:
    """No request bodies/credentials retained; tests inspect them inside callback."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        self.post_fault = False
        self.inspect_post: Callable[[str, dict[str, Any]], None] = lambda _path, _body: None
        self.rows: dict[str, Any] = {}
        ids = {
            "tariff_id": 32,
            "tariff_service_id": 1,
            "period_id": 1,
            "currency_id": 1,
            "tariff_period_id": 82,
            "catalog_id": 5,
            "catalog_service_id": 19,
        }

        def convert(node: Any) -> Any:
            if isinstance(node, dict):
                return {key: ids.get(key, convert(item)) for key, item in node.items()}
            if isinstance(node, list):
                return [convert(item) for item in node]
            return node

        for name in (
            "auth",
            "tariff",
            "periods",
            "services",
            "user",
            "agreement",
            "subscription",
            "created_user",
            "created_agreement",
            "created_subscription",
        ):
            self.rows[name] = convert(json.loads((DIRECTORY / "recordings" / f"{name}.json").read_bytes())["response"])
        service = self.rows["services"][0]
        service.update(min_multiplicator=1, max_multiplicator=1)
        service["prices"][0].update(price=100, connection_price=0)
        self.rows["prices"] = [
            {
                "price_id": 288,
                "period_id": 1,
                "start_date": "2026-10-01",
                "connection_price": 0,
                "bulk_price": 0,
                "price": 100,
                "bulk_include_amount": 0,
                "period_type": 3,
                "period_length": 1,
            }
        ]
        self.rows["user"]["login"] = "test-only-technical-login"
        self.rows["agreement"].update(agreement_link="", is_offer=False)
        self.rows["agreement"].pop("debt_threshold")
        self.rows["subscription"].update(
            total_price=100,
            is_offer_agrm=False,
            subscription_start_date="3000-01-01 00:00:00",
            subscription_end_date="9999-12-31 00:00:00",
            last_tariffication_period_start=None,
            last_tariffication_period_end=None,
            next_change_date=None,
        )
        self.rows["subscription"]["services"][0].update(price=100, tariff_price=999, multiplicator=1)
        self.rows["users"] = []
        self.rows["agreements"] = [
            {**self.rows["agreement"], "agreement_id": 25, "organization_id": 9, "agreement_number": "automatic"}
        ]
        self.rows["subscriptions"] = []

    async def respond(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix(API_PATH)
        self.requests.append((request.method, path))
        if request.method == "POST":
            self.inspect_post(path, json.loads(request.content))
            if self.post_fault:
                raise httpx.ReadTimeout("test-only private transport error", request=request)
            name = {
                "/users": "created_user",
                "/agreements": "created_agreement",
                "/subscriptions": "created_subscription",
            }[path]
            return httpx.Response(201, json={"code": 201, "response": self.rows[name]})
        names = {
            "/auth": "auth",
            "/tariffs/32": "tariff",
            "/tariffs/32/periods": "periods",
            "/tariffs/32/services": "services",
            "/tariffs/32/services/1/prices": "prices",
            "/users/1501": "user",
            "/users": "users",
            "/agreements": "agreements",
            "/agreements/1601": "agreement",
            "/subscriptions/1701": "subscription",
            "/subscriptions": "subscriptions",
        }
        value = self.rows["agreements"][0] if path == "/agreements/25" else self.rows[names[path]]
        return httpx.Response(200, json={"code": 200, "response": value})


@asynccontextmanager
async def stand_source(
    recording: StandRecording, **overrides: Any
) -> AsyncIterator[tuple[LbxServerClient, PreflightAdmission]]:
    configuration = stand_settings(**overrides)
    owner = admission(configuration)
    client = LbxServerClient(
        configuration,
        transport=httpx.MockTransport(recording.respond),
        stand_permission=Stand043Permission.configured(configuration),
    )
    try:
        yield client, owner
    finally:
        await owner.aclose()
        await client.aclose()


async def stand_offer(client: LbxServerClient, owner: PreflightAdmission) -> SelectedCommercialOffer:
    profile = configured_profile()
    async with owner.operation() as budget:
        return await read_selected_offer(client, selection=profile.selection, inputs=profile.inputs, budget=budget)


def mapping_for(
    offer: SelectedCommercialOffer, *, allowance: int = 25, revision: str = "fixture-v1"
) -> MappingDocument:
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
    approval = ApprovedMapping(
        schema_version=1,
        material=material,
        approved_material_hash=commercial_digest(material.canonical_json()),
        revisions=ApprovalRevisions(
            technical=approval_reference("technical", revision),
            commercial=approval_reference("commercial", revision),
            legal=approval_reference("legal", revision),
        ),
    )
    return evaluate_mapping(
        manifest=_decode_manifest(
            json.dumps(manifest_fixture()).encode(),
            tenant_id="anytoolai",
            region="ru",
            provenance=SourceProvenance.SIMULATED,
        ),
        offer=offer,
        technical=technical,
        approval=approval,
        scope=CommercialScope("anytoolai", "ru", ACCOUNT),
        principal="os-euid:29001",
        reason="SIMULATED Kernel, mocked 043 protocol",
        evaluated_at=NOW,
        allow_simulated=True,
    )
