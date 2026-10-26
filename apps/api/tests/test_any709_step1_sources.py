"""Normal connection/direct selection/current-price boundary. Tests are not live probes."""

from __future__ import annotations

import json
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.cli.commercial_mappings import parser
from app.composition import mapping_operator
from app.composition.mapping_operator import fresh_link_evaluation
from app.composition.sources import source_resources
from app.domains.catalog.commercial_offer import OfferRefusalKind, SelectedOfferRefused
from app.domains.catalog.preview import CatalogProductNotFound
from app.domains.catalog.mapping_evidence import MappingRefused
from app.domains.catalog.product_link import ProductLinkRequest
from app.domains.catalog.router import CatalogMoney
from app.integrations.lbx.current_offer import read_current_offer
from app.infrastructure.preflight import PreflightCleanupPending
from apps.api.tests.support.any709_step1 import link_selection, recording, step1_settings
from apps.api.tests.support.kernel import manifest_fixture, resign
from scripts import repo


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def fixed_offer_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 26, tzinfo=UTC))


async def evaluate(**overrides: Any) -> mapping_operator.FreshLinkEvaluation:
    source = overrides.pop("source", recording())
    manifest = overrides.pop("manifest", manifest_fixture())
    configuration = overrides.pop("configuration", step1_settings())
    selection = overrides.pop("selection", link_selection())
    return await fresh_link_evaluation(
        configuration,
        selection=selection,
        principal="os-euid:29001",
        kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=manifest)),
        lbx_transport=httpx.MockTransport(source.respond),
        **overrides,
    )


async def test_any709_step1_direct_link_uses_complete_reads_and_separate_provenance() -> None:
    source = recording()
    fresh = await evaluate(source=source)
    assert fresh.document.kernel_provenance == "SIMULATED"
    assert fresh.document.lbx_evidence_mode == "CONFIGURED_SOURCE"
    assert fresh.document.selection.period_id == 901  # membership ID 801 is different
    assert source.counts == {"tariff": 2, "periods": 2, "services": 2, "prices": 2}
    assert all(request.method == "GET" and request.url.path.startswith("/api/rest/v1/") for request in source.requests)
    serialized = fresh.document.model_dump_json()
    for forbidden in ("allowance", "approvals", "effective_price", "recurring_amount", "password"):
        assert forbidden not in serialized


async def test_any709_step1_price_change_is_live_without_changing_link_identity() -> None:
    before = await evaluate()
    changed = recording()
    changed.replace("services", '"price":100.01', '"price":200.02')
    changed.replace("prices", '"price":100.01', '"price":200.02')
    after = await evaluate(source=changed)
    assert before.document.identity_digest == after.document.identity_digest
    async with source_resources(step1_settings(), lbx_transport=httpx.MockTransport(changed.respond)) as sources:
        async with sources.preflight.operation() as budget:
            offer = await read_current_offer(
                sources.require_lbx(), selection=link_selection(), configuration=step1_settings(), budget=budget
            )
    assert offer.money.recurring_amount == Decimal("200.02")
    assert offer.period_id == 901 and offer.period_membership_id != offer.period_id
    assert offer.money.connection_amount == Decimal("7.03")


async def test_any709_step1_current_price_keeps_digits_beyond_binary_float_precision() -> None:
    source = recording()
    for name in ("services", "prices"):
        source.replace(name, '"price":100.01', '"price":9007199254740993.01')
    fresh = await evaluate(source=source)
    assert fresh.offer.money.recurring_amount == Decimal("9007199254740993.01")


async def test_any709_step1_quantity_is_explicit_commercial_bounds_without_invented_connection_policy() -> None:
    with pytest.raises(SelectedOfferRefused, match="connection_quantity_basis_unproven") as error:
        await evaluate(selection=link_selection(quantity=2))
    assert error.value.kind == OfferRefusalKind.INCOMPLETE
    source = recording()
    for name in ("services", "prices"):
        source.replace(name, '"connection_price":7.03', '"connection_price":0')
    offer = (await evaluate(selection=link_selection(quantity=2), source=source)).offer
    assert offer.quantity.selected == Decimal(2) and offer.money.recurring_amount == Decimal("200.02")


@pytest.mark.parametrize(
    "change,kind,reason",
    [
        ("additional", OfferRefusalKind.NOT_SELLABLE, "additional_or_missing_default_components_unsupported"),
        ("missing_default", OfferRefusalKind.INCOMPLETE, "component_enabled_by_default_unknown"),
        ("period_association", OfferRefusalKind.INCOMPLETE, "period_membership_missing_or_ambiguous"),
        ("unknown_currency", OfferRefusalKind.INCOMPLETE, "currency_interpretation_unsupported"),
        ("nonperiodic", OfferRefusalKind.NOT_SELLABLE, "fixed_periodic_profile_required"),
        ("inexact", OfferRefusalKind.INCOMPLETE, "money_scale_mismatch"),
    ],
)
async def test_any709_step1_refuses_incomplete_or_unsupported_offer(
    change: str, kind: OfferRefusalKind, reason: str
) -> None:
    source = recording()
    if change == "additional":
        source.append_row("services", '{"tariff_id":701,"tariff_service_id":1002,"enabled_by_default":1}')
    elif change == "missing_default":
        source.replace("services", '"enabled_by_default":1,', "")
    elif change == "period_association":
        source.replace("periods", '"period_id":901', '"period_id":999')
    elif change == "unknown_currency":
        source.replace("tariff", '"currency_id":1', '"currency_id":99')
    elif change == "nonperiodic":
        source.replace("services", '"periodic_service":1', '"periodic_service":0')
    else:
        for name in ("services", "prices"):
            source.replace(name, '"price":100.01', '"price":100.001')
    with pytest.raises(SelectedOfferRefused) as error:
        await evaluate(source=source)
    assert error.value.kind == kind and error.value.reason == reason


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"lbx_billing_timezone": ""}, "billing_timezone_required"),
        ({"lbx_billing_timezone": "Unknown/Invalid"}, "billing_timezone_invalid"),
        ({"lbx_currency": "EUR"}, "currency_interpretation_unsupported"),
        ({"lbx_currency_id": "unknown"}, "currency_interpretation_unsupported"),
    ],
)
async def test_any709_step1_calendar_and_currency_are_offer_errors(overrides: dict[str, str], reason: str) -> None:
    configuration = step1_settings(**overrides)
    assert configuration.lbx_configuration_error is None
    with pytest.raises(SelectedOfferRefused) as error:
        await evaluate(configuration=configuration)
    assert error.value.reason == reason


async def test_any709_step1_disabled_product_refuses_before_lbx_without_metric_allowance() -> None:
    manifest = manifest_fixture()
    next(product for product in manifest["products"] if product["product_id"] == "proposal_ai")["enabled"] = False
    source = recording()
    with pytest.raises(CatalogProductNotFound):
        await evaluate(source=source, manifest=resign(manifest))
    assert source.requests == []
    manifest = manifest_fixture()
    manifest["usage_metrics"] = []
    assert (await evaluate(manifest=resign(manifest))).document.selection.product_id == "proposal_ai"


async def test_any709_step1_source_failure_never_reuses_price_or_publication() -> None:
    source = recording()
    source.replace("prices", '"code":200', '"code":500')
    with pytest.raises(SelectedOfferRefused):
        await evaluate(source=source)


async def test_any709_step1_startup_sends_no_http_and_closes_both_pools_on_cleanup_failure() -> None:
    class Transport(httpx.AsyncBaseTransport):
        closed = False

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise AssertionError("startup made a provider request")

        async def aclose(self) -> None:
            self.closed = True

    class SlowTransport(Transport):
        async def aclose(self) -> None:
            await asyncio.Event().wait()

    lbx = Transport()
    with pytest.raises(PreflightCleanupPending):
        async with source_resources(
            step1_settings(preflight_cleanup_timeout_seconds=0.01), kernel_transport=SlowTransport(), lbx_transport=lbx
        ):
            pass
    assert lbx.closed


def test_any709_step1_removed_manual_configuration_cannot_override_connection_scope() -> None:
    original = step1_settings()
    changed = step1_settings(
        mapping_account_id="forged",
        lbx_external_billing_account_id="forged",
        mapping_approval_file="/missing",
        mapping_source_inputs_file="/missing",
    )
    assert original.lbx_external_billing_account_id == changed.lbx_external_billing_account_id
    assert (
        original.lbx_external_billing_account_id
        == step1_settings(lbx_server_password="rotated").lbx_external_billing_account_id
    )
    assert (
        original.lbx_external_billing_account_id
        != step1_settings(lbx_base_url="https://other.test").lbx_external_billing_account_id
    )
    assert "isolated-test-widget-secret" not in repr(original)
    assert not {
        "mapping_account_id",
        "lbx_external_billing_account_id",
        "mapping_approval_file",
        "mapping_source_inputs_file",
    }.intersection(type(original).model_fields)


def test_any709_step1_production_connection_and_partial_configuration_do_not_gate_identity() -> None:
    config = step1_settings(
        app_env="production",
        app_public_base_url="https://portal.example.com",
        cors_allow_origins=("https://portal.example.com",),
        kernel_base_url="",
        kernel_service_token="",
        kernel_mock_enabled=False,
    )
    assert config.lbx_configuration_error is None
    assert step1_settings(lbx_server_password="").lbx_configuration_error == "lbx_connection_fields_required"
    assert (
        step1_settings(lbx_base_url="https://billing.test/api/rest/v1").lbx_configuration_error
        == "lbx_base_url_invalid"
    )


async def test_any709_step1_configured_production_http_is_not_blanket_rejected_or_called_approved() -> None:
    config = step1_settings(
        app_env="production",
        app_public_base_url="https://portal.example.com",
        cors_allow_origins=("https://portal.example.com",),
        kernel_base_url="https://kernel.example.com",
        kernel_mock_enabled=False,
    )
    fresh = await evaluate(configuration=config)
    assert fresh.document.kernel_provenance == "CONFIGURED_SOURCE"
    assert fresh.document.lbx_evidence_mode == "CONFIGURED_SOURCE"
    assert "GENUINE" not in fresh.document.model_dump_json()
    with pytest.raises(ValidationError):
        step1_settings(
            app_env="production",
            app_public_base_url="https://portal.example.com",
            cors_allow_origins=("https://portal.example.com",),
            kernel_base_url="https://kernel.example.com",
            kernel_mock_enabled=True,
        )


def test_any709_step1_cli_accepts_only_ids_and_quantity() -> None:
    args = parser().parse_args(
        [
            "publish",
            "--product-id",
            "proposal_ai",
            "--tariff-id",
            "32",
            "--tariff-service-id",
            "1",
            "--period-id",
            "1",
            "--expected-previous-revision",
            "0",
        ]
    )
    assert args.period_id == 1 and args.quantity == 1
    for forbidden in ("--price", "--allowance", "--proposal", "--approved", "--actor"):
        with pytest.raises(SystemExit):
            parser().parse_args(["dry-run", forbidden, "1"])
    with pytest.raises(ValidationError):
        ProductLinkRequest(product_id="proposal_ai", tariff_id=True, tariff_service_id=1, period_id=1)
    with pytest.raises(ValidationError):
        CatalogMoney(recurring_amount="1.001", connection_amount="0.00", currency="RUB", decimal_places=2)


def test_any709_step1_operator_authorization_keeps_numeric_execution_identity() -> None:
    assert mapping_operator.authorize_operator(step1_settings(), resolve_uid=lambda: 29001) == "os-euid:29001"
    with pytest.raises(MappingRefused, match="mapping_operator_forbidden"):
        mapping_operator.authorize_operator(step1_settings(), resolve_uid=lambda: 42)
    with pytest.raises(MappingRefused, match="mapping_operator_identity_unavailable"):
        mapping_operator.authorize_operator(step1_settings(), resolve_uid=lambda: True)


def test_any709_step1_harness_connection_pass_through_is_private_and_mock_independent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = tmp_path / ".harness"
    monkeypatch.setattr(repo, "HARNESS_DIR", harness)
    monkeypatch.setattr(repo, "RUNTIME_ENV", harness / "runtime.env")
    monkeypatch.setattr(repo, "RUNTIME_JSON", harness / "runtime.json")
    monkeypatch.setattr(repo, "kernel_mock_enabled", lambda: False)
    secret = "private-$value #with'quote"
    monkeypatch.setattr(
        repo, "read_dotenv", lambda: {"LBX_SERVER_PASSWORD": secret, "LBX_BASE_URL": "https://billing.test"}
    )
    monkeypatch.delenv("LBX_SERVER_PASSWORD", raising=False)
    repo.write_runtime(repo.runtime_config(root=tmp_path))
    assert repo.read_runtime_env()["LBX_SERVER_PASSWORD"] == secret
    assert "LBX_SERVER_PASSWORD" not in json.loads(repo.RUNTIME_JSON.read_text())
    assert repo.RUNTIME_ENV.stat().st_mode & 0o077 == 0
    assert secret not in capsys.readouterr().out
    for filename in ("docker-compose.yml", "docker-compose.agent.yml", "docker-compose.prod.yml"):
        text = (repo.ROOT / filename).read_text()
        for setting in (
            "LBX_BASE_URL",
            "LBX_SERVER_USERNAME",
            "LBX_SERVER_PASSWORD",
            "LBX_WIDGET_SIGNING_SECRET",
            "LBX_SELLER_ORGANIZATION_ID",
            "MAPPING_OPERATOR_LOCK_FILE",
        ):
            assert setting + ":" in text
    mock = (repo.ROOT / "docker-compose.kernel-mock.dev.yml").read_text()
    assert "MAPPING_" not in mock and "LBX_" not in mock and "kernel-walkthrough" not in mock
