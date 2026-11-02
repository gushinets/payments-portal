"""Normal connection/direct selection/current-price boundary. Tests are not live probes."""

from __future__ import annotations

import json
import asyncio
from datetime import UTC, date, datetime
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
from app.domains.catalog.commercial_offer import OfferRefusalKind, SelectedOfferRefused, SelectedOfferSourceFailed
from app.domains.catalog.preview import CatalogProductNotFound
from app.domains.catalog.mapping_evidence import MappingRefused
from app.domains.catalog.product_link import ProductLinkRequest
from app.domains.catalog.router import CatalogMoney
from app.integrations.lbx.current_offer import read_current_offer
from app.infrastructure.preflight import PreflightCleanupPending
from apps.api.tests.support.any709_step1 import link_selection, readiness_recording, recording, step1_settings
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


async def test_any709_step1_retained_e04_e05_decode_through_real_client_and_normalize() -> None:
    source = readiness_recording()
    configuration = step1_settings(lbx_widget_signing_secret="", lbx_seller_organization_id="")
    selection = link_selection(tariff_id=32, tariff_service_id=1, period_id=1)
    async with source_resources(configuration, lbx_transport=httpx.MockTransport(source.respond)) as sources:
        async with sources.preflight.operation() as budget:
            services = await sources.require_lbx().list_tariff_services(tariff_id=32, budget=budget)
            prices = await sources.require_lbx().list_service_prices(tariff_id=32, tariff_service_id=1, budget=budget)
        assert services.value[0].min_multiplicator == Decimal("1.0")
        assert isinstance(services.value[0].max_multiplicator, Decimal)
        assert services.value[0].prices[0].price_start_date == prices.value[0].start_date == date(2026, 10, 1)
        assert prices.value[0].start_date_year == 2026 and prices.value[0].start_date_month == 10
    fresh = await evaluate(source=source, selection=selection, configuration=configuration)
    assert fresh.offer.money.recurring_amount == Decimal("100.0")
    assert fresh.offer.money.connection_amount == Decimal("0.0")
    assert fresh.offer.money.currency == "RUB" and fresh.offer.money.decimal_places == 2
    assert fresh.offer.quantity.minimum == fresh.offer.quantity.maximum == Decimal("1.0")
    assert type(fresh.offer.period.price_effective_from) is date
    assert fresh.offer.period.price_effective_until is None
    assert fresh.offer.period_id == 1 and fresh.offer.period_membership_id == 82


@pytest.mark.parametrize("wire_number", ["true", "false", '"1.0"', "NaN", "Infinity", "-Infinity"])
async def test_any709_step1_quantity_rejects_non_json_numbers_without_coercion(wire_number: str) -> None:
    source = readiness_recording()
    source.replace("services", '"min_multiplicator": 1.0', '"min_multiplicator": ' + wire_number)
    with pytest.raises(SelectedOfferSourceFailed, match="lbx_response_invalid"):
        await evaluate(source=source, selection=link_selection(tariff_id=32, tariff_service_id=1, period_id=1))


async def test_any709_step1_fractional_source_bounds_are_parsed_but_unsupported() -> None:
    source = readiness_recording()
    source.replace("services", '"min_multiplicator": 1.0', '"min_multiplicator": 0.5')
    with pytest.raises(SelectedOfferRefused) as error:
        await evaluate(source=source, selection=link_selection(tariff_id=32, tariff_service_id=1, period_id=1))
    assert not isinstance(error.value, SelectedOfferSourceFailed)
    assert error.value.kind == OfferRefusalKind.NOT_SELLABLE
    assert error.value.reason == "commercial_quantity_not_integer"


@pytest.mark.parametrize(
    "name,old,new",
    [
        ("services", '"2026-10-01 00:00:00"', '"2026-02-30 00:00:00"'),
        ("services", '"2026-10-01 00:00:00"', '"2026-10-01 01:00:00"'),
        ("services", '"2026-10-01 00:00:00"', '"2026-10-01T00:00:00Z"'),
        ("services", '"2026-10-01 00:00:00"', "true"),
        ("prices", '"start_date_month": 10', '"start_date_month": 13'),
        ("prices", '"start_date_year": 2026', '"start_date_year": 0'),
        ("prices", '"start_date_year": 2026', '"start_date_year": true'),
        ("prices", '"start_date_year": 2026', '"start_date_year": 2026.0'),
        ("prices", '"start_date_year": 2026', '"start_date_year": 2026, "start_date": "2026-11-01"'),
    ],
)
async def test_any709_step1_calendar_wire_values_are_validated_strictly(name: str, old: str, new: str) -> None:
    source = readiness_recording()
    source.replace(name, old, new)
    with pytest.raises(SelectedOfferSourceFailed, match="lbx_response_invalid"):
        await evaluate(source=source, selection=link_selection(tariff_id=32, tariff_service_id=1, period_id=1))


@pytest.mark.parametrize(
    "name,old,new,reason",
    [
        ("services", '"min_multiplicator": 1.0,', "", "min_multiplicator_unknown"),
        ("prices", '"start_date_month": 10,', "", "price_start_unknown"),
        ("services", "2026-10-01 00:00:00", "2026-10-02 00:00:00", "inline_effective_date_conflict"),
    ],
)
async def test_any709_step1_missing_or_conflicting_calendar_and_quantity_stay_offer_errors(
    name: str, old: str, new: str, reason: str
) -> None:
    source = readiness_recording()
    source.replace(name, old, new)
    with pytest.raises(SelectedOfferRefused) as error:
        await evaluate(source=source, selection=link_selection(tariff_id=32, tariff_service_id=1, period_id=1))
    assert not isinstance(error.value, SelectedOfferSourceFailed)
    assert error.value.kind == OfferRefusalKind.INCOMPLETE and error.value.reason == reason


async def test_any709_step1_rub_mapping_uses_configured_provider_id_and_exact_amounts() -> None:
    source = recording()
    source.replace("tariff", '"currency_id":1', '"currency_id":77')
    for name in ("services", "prices"):
        source.replace(name, '"price":100.01', '"price":9007199254740993.01')
    fresh = await evaluate(source=source, configuration=step1_settings(lbx_currency_id="77"))
    assert fresh.offer.money.currency == "RUB" and fresh.offer.money.decimal_places == 2
    assert fresh.offer.money.recurring_amount == Decimal("9007199254740993.01")
    with pytest.raises(SelectedOfferRefused, match="currency_interpretation_unsupported"):
        await evaluate(source=source, configuration=step1_settings(lbx_currency_id="78"))


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
        ({"lbx_currency": "EUR"}, "currency_interpretation_unsupported"),
        ({"lbx_currency_id": "unknown"}, "currency_interpretation_unsupported"),
    ],
)
async def test_any709_step1_currency_errors_are_offer_errors(overrides: dict[str, str], reason: str) -> None:
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
        == step1_settings(lbx_server_username="rotated", lbx_server_password="rotated").lbx_external_billing_account_id
        == step1_settings(lbx_base_url="https://LBX-CLIENT.TEST:443/").lbx_external_billing_account_id
        == step1_settings(lbx_server_username="", lbx_server_password="").lbx_external_billing_account_id
    )
    assert (
        original.lbx_external_billing_account_id
        != step1_settings(lbx_base_url="https://other.test").lbx_external_billing_account_id
    )
    assert (
        original.lbx_external_billing_account_id
        != step1_settings(lbx_base_url="https://lbx-client.test:8443").lbx_external_billing_account_id
    )
    assert "isolated-test-widget-secret" not in repr(original)
    assert not {
        "mapping_account_id",
        "lbx_external_billing_account_id",
        "mapping_approval_file",
        "mapping_source_inputs_file",
        "mapping_operator_uids",
    }.intersection(type(original).model_fields)


@pytest.mark.parametrize("legacy_value", ["[]", "[42]", "not-json"])
def test_any709_step1_legacy_operator_env_is_ignored(monkeypatch: pytest.MonkeyPatch, legacy_value: str) -> None:
    monkeypatch.setenv("MAPPING_OPERATOR_UIDS", legacy_value)
    configuration = step1_settings()
    assert "mapping_operator_uids" not in configuration.model_dump()
    assert configuration.mapping_lock_timeout_seconds == 2.0


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
            parser().parse_args(
                [
                    "dry-run",
                    "--product-id",
                    "proposal_ai",
                    "--tariff-id",
                    "32",
                    "--tariff-service-id",
                    "1",
                    "--period-id",
                    "1",
                    forbidden,
                    "1",
                ]
            )
    with pytest.raises(ValidationError):
        ProductLinkRequest(product_id="proposal_ai", tariff_id=True, tariff_service_id=1, period_id=1)
    with pytest.raises(ValidationError):
        CatalogMoney(recurring_amount="1.001", connection_amount="0.00", currency="RUB", decimal_places=2)


@pytest.mark.parametrize("uid", [0, 42, 29001])
def test_any709_step1_operator_principal_uses_actual_numeric_identity(
    monkeypatch: pytest.MonkeyPatch, uid: int
) -> None:
    monkeypatch.setattr(mapping_operator.os, "geteuid", lambda: uid, raising=False)
    monkeypatch.setenv("USER", "forged-user")
    monkeypatch.setenv("LOGNAME", "forged-user")
    assert mapping_operator.resolve_operator_principal() == f"os-euid:{uid}"


@pytest.mark.parametrize("uid", [True, False, -1, "42", 42.0, None])
def test_any709_step1_operator_principal_rejects_invalid_identity(monkeypatch: pytest.MonkeyPatch, uid: object) -> None:
    monkeypatch.setattr(mapping_operator.os, "geteuid", lambda: uid, raising=False)
    with pytest.raises(MappingRefused, match="mapping_operator_identity_unavailable"):
        mapping_operator.resolve_operator_principal()


def test_any709_step1_operator_principal_requires_available_os_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable() -> int:
        raise OSError("SIMULATED unavailable OS identity")

    monkeypatch.setattr(mapping_operator.os, "geteuid", unavailable, raising=False)
    with pytest.raises(MappingRefused, match="mapping_operator_identity_unavailable"):
        mapping_operator.resolve_operator_principal()
    monkeypatch.delattr(mapping_operator.os, "geteuid")
    with pytest.raises(MappingRefused, match="mapping_operator_identity_unavailable"):
        mapping_operator.resolve_operator_principal()


@pytest.mark.parametrize("lock_file", [None, "/run/private/operator.lock"])
def test_any709_step1_harness_connection_pass_through_is_private_and_mock_independent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    lock_file: str | None,
) -> None:
    harness = tmp_path / ".harness"
    monkeypatch.setattr(repo, "HARNESS_DIR", harness)
    monkeypatch.setattr(repo, "RUNTIME_ENV", harness / "runtime.env")
    monkeypatch.setattr(repo, "RUNTIME_JSON", harness / "runtime.json")
    monkeypatch.setattr(repo, "kernel_mock_enabled", lambda: False)
    secret = "private-$value #with'quote"
    local_env = {
        "LBX_SERVER_PASSWORD": secret,
        "LBX_BASE_URL": "https://billing.test",
        "MAPPING_OPERATOR_UIDS": "not-json",
        "LBX_BILLING_TIMEZONE": "Unknown/Invalid",
    }
    if lock_file is not None:
        local_env["MAPPING_OPERATOR_LOCK_FILE"] = lock_file
    monkeypatch.setattr(repo, "read_dotenv", lambda: local_env)
    monkeypatch.delenv("LBX_SERVER_PASSWORD", raising=False)
    monkeypatch.delenv("LBX_BASE_URL", raising=False)
    monkeypatch.delenv("MAPPING_OPERATOR_LOCK_FILE", raising=False)
    monkeypatch.setenv("MAPPING_OPERATOR_UIDS", "[42]")
    repo.write_runtime(repo.runtime_config(root=tmp_path))
    written = repo.read_runtime_env()
    assert written["LBX_SERVER_PASSWORD"] == secret
    assert written["LBX_BASE_URL"] == "https://billing.test"
    assert "MAPPING_OPERATOR_UIDS" not in written
    assert "LBX_BILLING_TIMEZONE" not in written
    assert written["MAPPING_OPERATOR_LOCK_FILE"] == (lock_file or "/run/payments-portal/operator.lock")
    assert "LBX_SERVER_PASSWORD" not in json.loads(repo.RUNTIME_JSON.read_text())
    assert repo.RUNTIME_ENV.stat().st_mode & 0o077 == 0
    assert (harness / "operator").is_dir()
    assert (harness / "operator").stat().st_mode & 0o077 == 0
    assert secret not in capsys.readouterr().out
    for filename in ("docker-compose.yml", "docker-compose.agent.yml", "docker-compose.prod.yml"):
        text = (repo.ROOT / filename).read_text()
        assert "MAPPING_OPERATOR_UIDS" not in text
        assert "LBX_BILLING_TIMEZONE" not in text
        for setting in (
            "LBX_BASE_URL",
            "LBX_SERVER_USERNAME",
            "LBX_SERVER_PASSWORD",
            "LBX_WIDGET_SIGNING_SECRET",
            "LBX_SELLER_ORGANIZATION_ID",
            "MAPPING_OPERATOR_LOCK_FILE",
        ):
            assert setting + ":" in text
    for filename in (".env.example", ".env.production.example"):
        text = (repo.ROOT / filename).read_text()
        assert "MAPPING_OPERATOR_UIDS" not in text
        assert "LBX_BILLING_TIMEZONE" not in text
        assert "MAPPING_OPERATOR_LOCK_FILE=" in text
    mock = (repo.ROOT / "docker-compose.kernel-mock.dev.yml").read_text()
    assert "MAPPING_" not in mock and "LBX_" not in mock and "kernel-walkthrough" not in mock
