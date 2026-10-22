#!/usr/bin/env python3
"""Portal-only conformance oracle. Never imported by the mock or application."""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Thread
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/contracts/kernel-capability-manifest/v1"
EXPECTED_DIGEST = "sha256:535a1cdf925b0afaa07b6d6045fd92f98dcb620dbd5fac7bf359dd3416a741fe"
ROUTE = "/internal/v1/capability-manifest"
SCOPE = {"tenant_id": "anytoolai", "region": "ru"}
TEST_TOKEN = "simulated-step8-local-only"
SELECTION = {"proposal_ai.test_generations": "generation"}


class ContractFailure(ValueError):
    """Only fixed diagnostics, never remote payloads or credentials."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractFailure(code)


def resolve_pointer(document: dict[str, Any], reference: str) -> Any:
    require(reference.startswith("#/"), "nonlocal_schema_reference")
    value = document
    try:
        for part in reference[2:].split("/"):
            value = value[part.replace("~1", "/").replace("~0", "~")]
    except (KeyError, TypeError):
        raise ContractFailure("unresolved_schema_reference") from None
    return value


def validate_schema(value: Any, schema: dict[str, Any], root: dict[str, Any]) -> None:
    """Interpret only the retained schema's vocabulary; fail on new keywords.

    This deliberately small test oracle is not a general JSON Schema library
    or a shared runtime validator. Protocol integers are strictly integers.
    """
    supported = {
        "$schema", "$defs", "$ref", "title", "description", "type", "const",
        "required", "properties", "additionalProperties", "items", "minLength", "pattern", "format",
    }
    require(not (set(schema) - supported), "unsupported_schema_keyword")
    if "$ref" in schema:
        validate_schema(value, resolve_pointer(root, schema["$ref"]), root)
    if "type" in schema:
        types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
        require(schema["type"] in types, "unsupported_schema_type")
        require(type(value) is types[schema["type"]], "schema_type_mismatch")
    if "const" in schema:
        require(type(value) is type(schema["const"]) and value == schema["const"], "schema_const_mismatch")
    if isinstance(value, dict):
        require(set(schema.get("required", ())) <= set(value), "schema_required_field_missing")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            require(set(value) <= set(properties), "schema_unknown_field")
        for name, item in value.items():
            if name in properties:
                validate_schema(item, properties[name], root)
    if isinstance(value, list) and "items" in schema:
        for item in value:
            validate_schema(item, schema["items"], root)
    if isinstance(value, str):
        require(len(value) >= schema.get("minLength", 0), "schema_empty_string")
        if "pattern" in schema:
            require(re.search(schema["pattern"], value) is not None, "schema_pattern_mismatch")
        if "format" in schema:
            require(schema["format"] == "date-time", "unsupported_schema_format")
            require(
                re.fullmatch(r"\d{4}-\d\d-\d\d[Tt]\d\d:\d\d:\d\d(?:\.\d+)?(?:[Zz]|[+-]\d\d:\d\d)", value)
                is not None,
                "schema_invalid_datetime",
            )
            try:
                parsed = datetime.fromisoformat(value.upper().replace("Z", "+00:00"))
            except ValueError:
                raise ContractFailure("schema_invalid_datetime") from None
            require(parsed.utcoffset() is not None, "schema_naive_datetime")


def semantic_digest(payload: dict[str, Any]) -> str:
    """Independent implementation, anchored to the unchanged literal digest."""
    semantic = {key: payload[key] for key in ("schema_version", "tenant_id", "region", "products", "usage_metrics")}
    semantic["products"] = sorted(semantic["products"], key=lambda row: row["product_id"])
    semantic["usage_metrics"] = sorted(semantic["usage_metrics"], key=lambda row: row["metric_key"])
    encoded = json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def validate_manifest(payload: Any, schema: dict[str, Any]) -> None:
    validate_schema(payload, schema, schema)
    require(all(payload[key] == value for key, value in SCOPE.items()), "manifest_scope_mismatch")
    products = [row["product_id"] for row in payload["products"]]
    metrics = [row["metric_key"] for row in payload["usage_metrics"]]
    require(len(products) == len(set(products)), "duplicate_product")
    require(len(metrics) == len(set(metrics)), "duplicate_metric")
    require(all(row["product_id"] in products for row in payload["usage_metrics"]), "invalid_metric_owner")
    require(payload["manifest_version"] == semantic_digest(payload), "semantic_digest_mismatch")


def validate_documentation(document: dict[str, Any], html: str, schema: dict[str, Any]) -> None:
    require(document["openapi"].startswith("3.1."), "openapi_version_mismatch")
    component = copy.deepcopy(document["components"]["schemas"]["CapabilityManifest"])
    prefix = "#/components/schemas/CapabilityManifest"

    def restore(value: Any) -> None:
        if isinstance(value, dict):
            if "$ref" in value:
                require(value["$ref"].startswith(prefix + "/"), "manifest_schema_reference_mismatch")
                value["$ref"] = "#" + value["$ref"][len(prefix):]
            for item in value.values():
                restore(item)
        elif isinstance(value, list):
            for item in value:
                restore(item)

    def resolve_all(value: Any) -> None:
        if isinstance(value, dict):
            if "$ref" in value:
                resolve_pointer(document, value["$ref"])
            for item in value.values():
                resolve_all(item)
        elif isinstance(value, list):
            for item in value:
                resolve_all(item)

    resolve_all(document)
    restore(component)
    require(component == {key: value for key, value in schema.items() if key != "$schema"}, "openapi_schema_drift")
    require("jsonSchemaDialect" not in document, "openapi_dialect_drift")
    require(set(document["paths"]) == {ROUTE}, "openapi_path_drift")
    require(set(document["paths"][ROUTE]) == {"get"}, "openapi_method_drift")
    operation = document["paths"][ROUTE]["get"]
    require(operation["security"] == [{"KernelServiceBearer": []}], "openapi_auth_drift")
    require(document["components"]["securitySchemes"]["KernelServiceBearer"]["scheme"] == "bearer", "openapi_auth_drift")
    parameters = {item["name"]: item for item in operation["parameters"]}
    require(set(parameters) == set(SCOPE), "openapi_scope_drift")
    for name, expected in SCOPE.items():
        require(parameters[name]["required"] is True, "openapi_scope_drift")
        require(parameters[name]["in"] == "query", "openapi_scope_drift")
        require(parameters[name]["schema"] == {"type": "string", "enum": [expected]}, "openapi_scope_drift")
    require(set(operation["responses"]) == {"200", "401", "403", "503"}, "openapi_status_drift")
    success = operation["responses"]["200"]["content"]["application/json"]
    require(success["schema"] == {"$ref": prefix}, "openapi_success_schema_drift")
    validate_manifest(success["example"], schema)
    require(success["example"]["manifest_version"] == EXPECTED_DIGEST, "openapi_example_drift")
    for setting in (
        'url: "/openapi.json"', "supportedSubmitMethods: []", "tryItOutEnabled: false",
        "persistAuthorization: false", "queryConfigEnabled: false", "validatorUrl: null", "withCredentials: false",
        "swagger-ui-dist@5.32.15/swagger-ui.css", "swagger-ui-dist@5.32.15/swagger-ui-bundle.js",
    ):
        require(setting in html, "swagger_read_only_drift")
    require(TEST_TOKEN not in html + json.dumps(document), "documentation_credential_leak")


@contextmanager
def running_mock(scenario: str = "valid", *, fixture: dict[str, Any] | None = None) -> Iterator[str]:
    from tools.kernel_manifest_mock.server import ManifestMockServer, MockConfig, Scenario

    with ManifestMockServer(("127.0.0.1", 0), MockConfig(app_env="test", token=TEST_TOKEN, scenario=Scenario(scenario))) as server:
        if fixture is not None:
            server.fixture = copy.deepcopy(fixture)
        worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            worker.join(timeout=3)
            require(not worker.is_alive(), "local_mock_shutdown_failed")


async def check_case(scenario: str, schema: dict[str, Any], *, fixture: dict[str, Any] | None = None) -> None:
    import httpx

    from app.composition.sources import source_resources
    from app.domains.catalog.admission import SelectedCapabilityUnavailable, require_selected_capability
    from app.domains.catalog.contracts import SourceProvenance
    from app.integrations.kernel.client import KernelError
    from apps.api.tests.support.kernel import kernel_settings

    invalid = {
        "wrong-schema", "malformed-json", "partial", "wrong-type", "duplicate-product", "duplicate-metric",
        "invalid-reference", "digest-mismatch", "wrong-tenant", "wrong-region",
    }
    errors = {
        "unauthorized": "kernel_authentication_failed", "forbidden": "kernel_scope_forbidden",
        "unavailable": "kernel_unavailable", "wrong-tenant": "kernel_scope_mismatch", "wrong-region": "kernel_scope_mismatch",
    }
    disabled = {"disabled-product", "missing-product", "disabled-metric", "missing-metric"}
    with running_mock(scenario, fixture=fixture) as origin:
        async with httpx.AsyncClient(base_url=origin, trust_env=False, timeout=2) as http:
            response = await http.get(ROUTE, params=SCOPE, headers={"Authorization": f"Bearer {TEST_TOKEN}"})
            require(response.status_code == {"unauthorized": 401, "forbidden": 403, "unavailable": 503}.get(scenario, 200), "http_status_mismatch")
            if response.status_code == 200:
                try:
                    validate_manifest(response.json(), schema)
                except ValueError:
                    require(scenario in invalid, "unexpected_oracle_rejection")
                else:
                    require(scenario not in invalid, "oracle_accepted_corruption")
            document = await http.get("/openapi.json")
            html = await http.get("/docs")
            require(document.status_code == html.status_code == 200, "documentation_unavailable")
            require(document.headers["content-type"] == "application/json", "documentation_content_type")
            require(html.headers["content-type"].startswith("text/html"), "documentation_content_type")
            openapi = document.json()
            validate_documentation(openapi, html.text, schema)
            if scenario == "valid":
                require("access-control-allow-origin" not in response.headers, "browser_access_enabled")
                for headers, scope, status in (
                    ({}, SCOPE, 401),
                    ({"Authorization": "Bearer wrong-test-token"}, SCOPE, 401),
                    ({"Authorization": "Basic user-login"}, SCOPE, 401),
                    ({"Authorization": f"Bearer {TEST_TOKEN}"}, {**SCOPE, "region": "other"}, 403),
                    ({"Authorization": f"Bearer {TEST_TOKEN}", "Origin": "http://localhost"}, SCOPE, 403),
                ):
                    refused = await http.get(ROUTE, params=scope, headers=headers)
                    require(refused.status_code == status, "http_auth_scope_mismatch")
                    require("access-control-allow-origin" not in refused.headers, "browser_access_enabled")
                    if status == 401:
                        require(refused.headers.get("www-authenticate") == "Bearer", "http_auth_challenge_mismatch")
                    error_schema = openapi["components"]["schemas"]["MockError"]
                    validate_schema(refused.json(), error_schema, openapi)
        async with source_resources(kernel_settings(kernel_base_url=origin, kernel_service_token=TEST_TOKEN)) as sources:
            try:
                async with sources.preflight.operation() as budget:
                    manifest = await sources.require_kernel().fetch_manifest(budget=budget)
            except KernelError as error:
                require(scenario in invalid or scenario in errors, "unexpected_client_rejection")
                require(str(error) == errors.get(scenario, "kernel_manifest_invalid"), "client_error_mismatch")
            else:
                require(scenario not in invalid and scenario not in errors, "client_accepted_corruption")
                require(manifest.provenance is SourceProvenance.SIMULATED, "simulation_provenance_lost")
                selection = dict(SELECTION)
                if fixture is not None:
                    selection = {row["metric_key"]: row["unit"] for row in fixture["usage_metrics"]}
                try:
                    require_selected_capability(manifest, product_id="proposal_ai", metric_units=selection)
                except SelectedCapabilityUnavailable:
                    require(scenario in disabled, "unexpected_selection_rejection")
                else:
                    require(scenario not in disabled, "disabled_selection_accepted")
                require(manifest.manifest_version == response.json()["manifest_version"], "client_digest_mismatch")
                served = response.json()
                require(
                    {item.product_id: item.enabled for item in manifest.products}
                    == {item["product_id"]: item["enabled"] for item in served["products"]},
                    "client_product_interpretation_mismatch",
                )
                require(
                    {item.metric_key: (item.product_id, item.unit, item.enabled) for item in manifest.usage_metrics}
                    == {
                        item["metric_key"]: (item["product_id"], item["unit"], item["enabled"])
                        for item in served["usage_metrics"]
                    },
                    "client_metric_interpretation_mismatch",
                )
                require(
                    (manifest.schema_version, manifest.tenant_id, manifest.region)
                    == (served["schema_version"], served["tenant_id"], served["region"]),
                    "client_scope_interpretation_mismatch",
                )
                require(manifest.generated_at.utcoffset() is not None, "client_timestamp_interpretation_mismatch")
            require(sources.preflight.active_count == sources.preflight.waiting_count == 0, "source_capacity_leak")


async def check_local(scenario: str | None = None) -> None:
    from apps.api.tests.support.settings import configure_api_test_environment

    # Settings has an import-time instance: supply the existing safe test scope
    # before importing the consumer, including in a clean CI environment.
    configure_api_test_environment()
    schema = json.loads((CONTRACT / "manifest.schema.json").read_text(encoding="utf-8"))
    fixture = json.loads((CONTRACT / "fixtures/valid-manifest.json").read_text(encoding="utf-8"))
    validate_manifest(fixture, schema)
    require((CONTRACT / "fixtures/valid-manifest.digest").read_text().strip() == EXPECTED_DIGEST, "literal_digest_drift")
    require(fixture["manifest_version"] == EXPECTED_DIGEST, "fixture_digest_drift")
    if scenario is not None:
        # A deliberately broken producer must make this command exit nonzero.
        import httpx

        with running_mock(scenario) as origin:
            async with httpx.AsyncClient(base_url=origin, trust_env=False, timeout=2) as http:
                response = await http.get(ROUTE, params=SCOPE, headers={"Authorization": f"Bearer {TEST_TOKEN}"})
                validate_manifest(response.json(), schema)
        return
    for case in (
        "valid", "disabled-product", "missing-product", "disabled-metric", "missing-metric", "wrong-schema",
        "malformed-json", "partial", "wrong-type", "duplicate-product", "duplicate-metric", "invalid-reference",
        "digest-mismatch", "wrong-tenant", "wrong-region", "unauthorized", "forbidden", "unavailable",
    ):
        await check_case(case, schema)
    multiple = copy.deepcopy(fixture)
    multiple["usage_metrics"].append({
        "metric_key": "proposal_ai.second_test_metric", "product_id": "proposal_ai", "unit": "generation", "enabled": True,
    })
    multiple["manifest_version"] = semantic_digest(multiple)
    multiple["products"].reverse()
    multiple["usage_metrics"].reverse()
    multiple["generated_at"] = "2026-10-16T10:00:00+08:00"
    validate_manifest(multiple, schema)
    await check_case("valid", schema, fixture=multiple)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true", required=True)
    parser.add_argument("--scenario", choices=("partial", "invalid-reference", "digest-mismatch"))
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "apps/api"))
    try:
        asyncio.run(check_local(args.scenario))
    except ContractFailure as error:
        print("LOCAL_SPEC_CONFORMANCE=FAIL")
        print(f"LOCAL_SPEC_FAILURE={error}")
        result = 1
    except Exception:
        # Diagnostic category only: unexpected errors may contain network/config secrets.
        print("LOCAL_SPEC_CONFORMANCE=FAIL")
        print("LOCAL_SPEC_FAILURE=unexpected_checker_error")
        result = 1
    else:
        print("LOCAL_SPEC_CONFORMANCE=PASS")
        result = 0
    print("REAL_KERNEL_CONFORMANCE=DEFERRED_NOT_IMPLEMENTED")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
