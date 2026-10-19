from __future__ import annotations

import copy
import json
import sys
from typing import Any

import pytest

from scripts import check_kernel_manifest_contract as checker


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def contract_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    schema = json.loads((checker.CONTRACT / "manifest.schema.json").read_text())
    fixture = json.loads((checker.CONTRACT / "fixtures/valid-manifest.json").read_text())
    return schema, fixture


@pytest.mark.anyio
async def test_local_spec_mock_and_typed_client_conformance_over_real_http() -> None:
    await checker.check_local()


@pytest.mark.anyio
async def test_independent_oracle_detects_incorrect_typed_consumer_interpretation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from app.domains.catalog.contracts import CapabilityManifest
    from app.integrations.kernel import client

    original = client._decode_manifest

    def broken_consumer(body: bytes, **kwargs: Any) -> CapabilityManifest:
        manifest = original(body, **kwargs)
        products = (replace(manifest.products[0], enabled=True), *manifest.products[1:])
        return replace(manifest, products=products)

    monkeypatch.setattr(client, "_decode_manifest", broken_consumer)
    schema, _ = contract_inputs()
    with pytest.raises(checker.ContractFailure, match="client_product_interpretation_mismatch"):
        await checker.check_case("valid", schema)


@pytest.mark.parametrize(
    "field",
    ["schema_version", "tenant_id", "region", "manifest_version", "generated_at", "products", "usage_metrics"],
)
def test_independent_oracle_rejects_every_missing_required_field(field: str) -> None:
    schema, fixture = contract_inputs()
    del fixture[field]
    with pytest.raises(checker.ContractFailure, match="schema_required_field_missing"):
        checker.validate_manifest(fixture, schema)


@pytest.mark.parametrize("value", [True, 1.0, "1", 2])
def test_oracle_does_not_coerce_protocol_version(value: Any) -> None:
    schema, fixture = contract_inputs()
    fixture["schema_version"] = value
    with pytest.raises(checker.ContractFailure):
        checker.validate_manifest(fixture, schema)


@pytest.mark.parametrize(
    "corruption", ["owner", "digest", "product-key", "metric-key", "scope", "extra", "enabled", "timestamp"]
)
def test_independent_semantic_and_schema_failures(corruption: str) -> None:
    schema, fixture = contract_inputs()
    if corruption == "owner":
        fixture["usage_metrics"][0]["product_id"] = "absent-test-product"
        fixture["manifest_version"] = checker.semantic_digest(fixture)
    elif corruption == "digest":
        fixture["manifest_version"] = "sha256:" + "0" * 64
    elif corruption in {"product-key", "metric-key"}:
        collection = "products" if corruption == "product-key" else "usage_metrics"
        fixture[collection].append(copy.deepcopy(fixture[collection][0]))
        fixture["manifest_version"] = checker.semantic_digest(fixture)
    elif corruption == "scope":
        fixture["region"] = "other-test-region"
        fixture["manifest_version"] = checker.semantic_digest(fixture)
    elif corruption == "extra":
        fixture["usage_metrics"][0]["extra"] = "not-a-wire-field"
    elif corruption == "enabled":
        fixture["products"][0]["enabled"] = 0
    else:
        fixture["generated_at"] = "2026-10-19T00:00:00"
    with pytest.raises(checker.ContractFailure):
        checker.validate_manifest(fixture, schema)


def test_oracle_fails_closed_for_a_new_schema_keyword() -> None:
    schema, fixture = contract_inputs()
    schema["properties"]["tenant_id"]["maxLength"] = 1
    with pytest.raises(checker.ContractFailure, match="unsupported_schema_keyword"):
        checker.validate_manifest(fixture, schema)


@pytest.mark.parametrize("scenario", ["partial", "invalid-reference", "digest-mismatch"])
def test_deliberately_broken_http_producer_makes_command_fail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], scenario: str
) -> None:
    monkeypatch.setattr(sys, "argv", ["check_kernel_manifest_contract.py", "--local", "--scenario", scenario])
    assert checker.main() == 1
    output = capsys.readouterr().out
    assert "LOCAL_SPEC_CONFORMANCE=FAIL" in output
    assert "REAL_KERNEL_CONFORMANCE=DEFERRED_NOT_IMPLEMENTED" in output
    assert checker.TEST_TOKEN not in output


@pytest.mark.anyio
async def test_openapi_constraint_or_reference_drift_and_writable_swagger_are_rejected() -> None:
    import httpx

    schema, _ = contract_inputs()
    with checker.running_mock() as origin:
        async with httpx.AsyncClient(base_url=origin, trust_env=False) as http:
            document = (await http.get("/openapi.json")).json()
            html = (await http.get("/docs")).text
    checker.validate_documentation(document, html, schema)
    broken_schema = copy.deepcopy(document)
    broken_schema["components"]["schemas"]["CapabilityManifest"]["additionalProperties"] = True
    with pytest.raises(checker.ContractFailure, match="openapi_schema_drift"):
        checker.validate_documentation(broken_schema, html, schema)
    broken_ref = copy.deepcopy(document)
    operation = broken_ref["paths"][checker.ROUTE]["get"]
    success_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    success_schema["$ref"] = "#/components/schemas/Missing"
    with pytest.raises(checker.ContractFailure, match="unresolved_schema_reference"):
        checker.validate_documentation(broken_ref, html, schema)
    with pytest.raises(checker.ContractFailure, match="swagger_read_only_drift"):
        checker.validate_documentation(
            document, html.replace("supportedSubmitMethods: []", 'supportedSubmitMethods: ["get"]'), schema
        )
