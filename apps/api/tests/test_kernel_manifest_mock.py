from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from typing import Annotated, Any

import httpx
import pytest
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from tools.kernel_manifest_mock.server import ManifestMockServer, MockConfig, Scenario, semantic_version


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs/contracts/kernel-capability-manifest/v1"
FIXTURE = json.loads((CONTRACT / "fixtures/valid-manifest.json").read_text(encoding="utf-8"))
EXPECTED_DIGEST = (CONTRACT / "fixtures/valid-manifest.digest").read_text(encoding="utf-8").strip()
TOKEN = "test-only-kernel-service-token"
ROUTE = "/internal/v1/capability-manifest"
SCOPE = {"tenant_id": "anytoolai", "region": "ru"}
NonemptyString = Annotated[str, Field(min_length=1)]


class _Product(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    product_id: NonemptyString
    enabled: bool


class _Metric(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    metric_key: NonemptyString
    product_id: NonemptyString
    unit: NonemptyString
    enabled: bool


class _Manifest(BaseModel):
    """Independent test oracle; never imported by the mock or a Portal client."""

    model_config = ConfigDict(strict=True, extra="forbid")
    schema_version: Annotated[int, Field(ge=1, le=1)]
    tenant_id: NonemptyString
    region: NonemptyString
    manifest_version: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    generated_at: AwareDatetime
    products: list[_Product]
    usage_metrics: list[_Metric]


def _independent_digest(payload: dict[str, Any]) -> str:
    semantic = {key: payload[key] for key in ("schema_version", "tenant_id", "region", "products", "usage_metrics")}
    semantic["products"] = sorted(semantic["products"], key=lambda row: row["product_id"])
    semantic["usage_metrics"] = sorted(semantic["usage_metrics"], key=lambda row: row["metric_key"])
    canonical = json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _assert_complete_manifest(payload: dict[str, Any]) -> None:
    manifest = _Manifest.model_validate_json(json.dumps(payload))
    assert (manifest.tenant_id, manifest.region) == ("anytoolai", "ru")
    product_ids = {product.product_id for product in manifest.products}
    metric_keys = {metric.metric_key for metric in manifest.usage_metrics}
    assert len(product_ids) == len(manifest.products)
    assert len(metric_keys) == len(manifest.usage_metrics)
    assert all(metric.product_id in product_ids for metric in manifest.usage_metrics)
    assert manifest.manifest_version == _independent_digest(payload)


@contextmanager
def _running_mock(scenario: Scenario = Scenario.VALID) -> Iterator[httpx.Client]:
    config = MockConfig(app_env="test", token=TOKEN, scenario=scenario, delay_seconds=0.2)
    with ManifestMockServer(("127.0.0.1", 0), config) as server:
        worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{server.server_port}",
                headers={"Authorization": f"Bearer {TOKEN}"},
                timeout=1,
                trust_env=False,
            ) as client:
                yield client
        finally:
            server.shutdown()
            worker.join(timeout=3)
            assert not worker.is_alive()


def test_independent_fixture_has_literal_expected_digest_and_declared_schema_shape() -> None:
    _assert_complete_manifest(FIXTURE)
    assert FIXTURE["manifest_version"] == EXPECTED_DIGEST
    assert _independent_digest(FIXTURE) == EXPECTED_DIGEST
    schema = json.loads((CONTRACT / "manifest.schema.json").read_text(encoding="utf-8"))
    assert set(schema["required"]) == set(schema["properties"]) == set(FIXTURE)
    for definition, collection in (("product", "products"), ("usage_metric", "usage_metrics")):
        fields = schema["$defs"][definition]
        assert set(fields["required"]) == set(fields["properties"]) == set(FIXTURE[collection][0])


def test_complete_manifest_is_served_over_http_with_stable_expected_digest() -> None:
    with _running_mock() as client:
        first = client.get(ROUTE, params=SCOPE)
        second = client.get(ROUTE, params=SCOPE)
    assert first.status_code == second.status_code == 200
    payload = first.json()
    _assert_complete_manifest(payload)
    assert {**payload, "generated_at": FIXTURE["generated_at"]} == FIXTURE
    assert payload["manifest_version"] == second.json()["manifest_version"] == EXPECTED_DIGEST
    assert first.headers["cache-control"] == "no-store"
    assert len(payload["products"]) == 6
    assert [product["product_id"] for product in payload["products"] if product["enabled"]] == ["proposal_ai"]
    assert payload["usage_metrics"][0]["metric_key"] == "proposal_ai.test_generations"


def test_digest_ignores_generation_timestamp_version_and_array_order_but_changes_with_semantics() -> None:
    payload = copy.deepcopy(FIXTURE)
    payload["generated_at"] = "2030-01-01T00:00:00Z"
    payload["manifest_version"] = "ignored-by-hashing"
    payload["products"].reverse()
    assert semantic_version(payload) == _independent_digest(payload) == EXPECTED_DIGEST
    payload["usage_metrics"][0]["enabled"] = False
    assert semantic_version(payload) == _independent_digest(payload) != EXPECTED_DIGEST
    payload["usage_metrics"].append(
        {
            "metric_key": "proposal_ai.another_test_metric",
            "product_id": "proposal_ai",
            "unit": "generation",
            "enabled": False,
        }
    )
    version = semantic_version(payload)
    payload["usage_metrics"].reverse()
    assert semantic_version(payload) == _independent_digest(payload) == version


@pytest.mark.parametrize(
    "scenario",
    [Scenario.DISABLED_PRODUCT, Scenario.MISSING_PRODUCT, Scenario.DISABLED_METRIC, Scenario.MISSING_METRIC],
)
def test_disabled_or_absent_selected_capability_is_a_complete_manifest(scenario: Scenario) -> None:
    with _running_mock(scenario) as client:
        response = client.get(ROUTE, params=SCOPE)
    assert response.status_code == 200
    payload = response.json()
    _assert_complete_manifest(payload)
    products = {product["product_id"]: product for product in payload["products"]}
    metrics = {metric["metric_key"]: metric for metric in payload["usage_metrics"]}
    if scenario == Scenario.DISABLED_PRODUCT:
        assert products["proposal_ai"]["enabled"] is False
    elif scenario == Scenario.MISSING_PRODUCT:
        assert "proposal_ai" not in products
        assert not metrics
    elif scenario == Scenario.DISABLED_METRIC:
        assert metrics["proposal_ai.test_generations"]["enabled"] is False
    else:
        assert products["proposal_ai"]["enabled"] is True
        assert not metrics
    assert payload["manifest_version"] != EXPECTED_DIGEST


@pytest.mark.parametrize(
    "scenario",
    [
        Scenario.WRONG_SCHEMA,
        Scenario.PARTIAL,
        Scenario.WRONG_TYPE,
        Scenario.DUPLICATE_PRODUCT,
        Scenario.DUPLICATE_METRIC,
        Scenario.INVALID_REFERENCE,
        Scenario.WRONG_TENANT,
        Scenario.WRONG_REGION,
        Scenario.DIGEST_MISMATCH,
    ],
)
def test_corrupt_success_scenarios_are_rejected_by_independent_oracle(scenario: Scenario) -> None:
    with _running_mock(scenario) as client:
        response = client.get(ROUTE, params=SCOPE)
    assert response.status_code == 200  # Intentional fault injection, not conforming producer behavior.
    with pytest.raises((ValidationError, AssertionError)):
        _assert_complete_manifest(response.json())


def test_malformed_json_is_deliberate_fault_injection() -> None:
    with _running_mock(Scenario.MALFORMED_JSON) as client:
        response = client.get(ROUTE, params=SCOPE)
    assert response.status_code == 200
    with pytest.raises(json.JSONDecodeError):
        response.json()


@pytest.mark.parametrize("corruption", ["duplicate-product", "duplicate-metric", "invalid-reference", "wrong-type"])
def test_mock_rejects_invalid_entries_before_hashing(corruption: str) -> None:
    payload = copy.deepcopy(FIXTURE)
    if corruption == "duplicate-product":
        payload["products"].append(copy.deepcopy(payload["products"][0]))
    elif corruption == "duplicate-metric":
        payload["usage_metrics"].append(copy.deepcopy(payload["usage_metrics"][0]))
    elif corruption == "invalid-reference":
        payload["usage_metrics"][0]["product_id"] = "missing-test-product"
    else:
        payload["products"][0]["enabled"] = "false"
    with pytest.raises(ValueError):
        semantic_version(payload)


@pytest.mark.parametrize("authorization", [None, "Bearer wrong-token", "Basic user-login", "Bearer"])
def test_missing_or_invalid_service_auth_returns_401_without_sensitive_logs(
    authorization: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    with _running_mock() as client:
        client.headers.pop("Authorization")
        headers = {} if authorization is None else {"Authorization": authorization}
        response = client.get(ROUTE, params=SCOPE, headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "invalid_service_auth"}}
    assert response.headers["www-authenticate"] == "Bearer"
    output = capsys.readouterr()
    assert not output.out and not output.err
    assert TOKEN not in response.text


@pytest.mark.parametrize(
    "scope",
    [
        {},
        {"tenant_id": "other-test-tenant", "region": "ru"},
        {"tenant_id": "anytoolai", "region": "other-test-region"},
        {"tenant_id": "anytoolai", "region": ""},
        {"tenant_id": "anytoolai", "region": ["ru", "ru"]},
        {**SCOPE, "scenario": "unavailable"},
    ],
)
def test_scope_is_explicit_and_query_cannot_control_scenarios(scope: dict[str, Any]) -> None:
    with _running_mock() as client:
        response = client.get(ROUTE, params=scope)
        valid = client.get(ROUTE, params=SCOPE)
    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "scope_forbidden"}}
    assert valid.status_code == 200


@pytest.mark.parametrize(
    ("scenario", "status", "code"),
    [
        (Scenario.UNAUTHORIZED, 401, "invalid_service_auth"),
        (Scenario.FORBIDDEN, 403, "scope_forbidden"),
        (Scenario.UNAVAILABLE, 503, "manifest_unavailable"),
    ],
)
def test_startup_selected_http_failures(scenario: Scenario, status: int, code: str) -> None:
    with _running_mock(scenario) as client:
        response = client.get(ROUTE, params=SCOPE)
        document = client.get("/openapi.json").json()
    assert response.status_code == status
    assert response.json() == {"detail": {"code": code}}
    documented = document["paths"][ROUTE]["get"]["responses"][str(status)]["content"]["application/json"]
    assert documented["examples"][code]["value"] == response.json()


def test_timeout_uses_real_http_read_deadline() -> None:
    with _running_mock(Scenario.TIMEOUT) as client:
        with pytest.raises(httpx.ReadTimeout):
            client.get(ROUTE, params=SCOPE, timeout=0.02)


def test_no_browser_manifest_cors_control_or_unrelated_routes() -> None:
    with _running_mock() as client:
        browser = client.get(ROUTE, params=SCOPE, headers={"Origin": "http://localhost:3000"})
        assert browser.status_code == 403
        assert browser.json() == {"detail": {"code": "browser_access_forbidden"}}
        assert "access-control-allow-origin" not in browser.headers
        for path in ("/", "/health", "/control/scenario"):
            assert client.get(path).status_code == 404
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"):
            assert client.request(method, ROUTE, params=SCOPE).status_code == 405


def test_openapi_documents_real_endpoint_and_reuses_versioned_schema() -> None:
    with _running_mock() as client:
        client.headers.pop("Authorization")
        response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "no-store"
    assert TOKEN not in response.text
    document = response.json()
    assert document["openapi"] == "3.1.0"
    assert "jsonSchemaDialect" not in document
    assert set(document["paths"]) == {ROUTE}
    assert set(document["paths"][ROUTE]) == {"get"}
    operation = document["paths"][ROUTE]["get"]
    assert operation["security"] == [{"KernelServiceBearer": []}]
    security = document["components"]["securitySchemes"]["KernelServiceBearer"]
    assert (security["type"], security["scheme"]) == ("http", "bearer")
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert set(parameters) == set(SCOPE)
    for name, value in SCOPE.items():
        assert parameters[name]["in"] == "query"
        assert parameters[name]["required"] is True
        assert parameters[name]["schema"] == {"type": "string", "enum": [value]}
    assert set(operation["responses"]) == {"200", "401", "403", "503"}
    success = operation["responses"]["200"]["content"]["application/json"]
    assert success["schema"] == {"$ref": "#/components/schemas/CapabilityManifest"}
    assert success["example"] == FIXTURE
    for status in ("401", "403", "503"):
        error = operation["responses"][status]["content"]["application/json"]
        assert error["schema"] == {"$ref": "#/components/schemas/MockError"}

    source = json.loads((CONTRACT / "manifest.schema.json").read_text(encoding="utf-8"))
    embedded = document["components"]["schemas"]["CapabilityManifest"]
    assert "$schema" not in embedded
    restored = json.loads(json.dumps(embedded).replace("#/components/schemas/CapabilityManifest/", "#/"))
    assert restored == {key: value for key, value in source.items() if key != "$schema"}
    for collection, definition in (("products", "product"), ("usage_metrics", "usage_metric")):
        reference = embedded["properties"][collection]["items"]["$ref"]
        assert reference == f"#/components/schemas/CapabilityManifest/$defs/{definition}"
        resolved = document
        for segment in reference.removeprefix("#/").split("/"):
            resolved = resolved[segment]
        assert resolved == source["$defs"][definition]


def test_swagger_is_read_only_metadata_and_does_not_relax_manifest_restrictions() -> None:
    with _running_mock() as client:
        client.headers.pop("Authorization")
        response = client.get("/docs")
        assert client.get(ROUTE, params=SCOPE).status_code == 401
        assert client.get(ROUTE, params=SCOPE, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200
        for path in ("/docs", "/openapi.json"):
            cross_origin = client.get(path, headers={"Origin": "http://localhost:3000"})
            assert cross_origin.status_code == 403
            assert "access-control-allow-origin" not in cross_origin.headers
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    assert TOKEN not in response.text
    assert "SIMULATED" in response.text
    assert 'url: "/openapi.json"' in response.text
    assert "supportedSubmitMethods: []" in response.text
    assert "persistAuthorization: false" in response.text
    assert "queryConfigEnabled: false" in response.text
    assert "validatorUrl: null" in response.text
    assert "swagger-ui-dist@5.32.15/swagger-ui-bundle.js" in response.text
    assert "swagger-ui-dist@5.32.15/swagger-ui.css" in response.text


@pytest.mark.parametrize(
    "scenario", [Scenario.UNAUTHORIZED, Scenario.UNAVAILABLE, Scenario.TIMEOUT, Scenario.MALFORMED_JSON]
)
def test_documentation_stays_available_during_manifest_faults(scenario: Scenario) -> None:
    with _running_mock(scenario) as client:
        client.headers.pop("Authorization")
        assert client.get("/docs").status_code == 200
        document = client.get("/openapi.json")
    assert document.status_code == 200
    example = document.json()["paths"][ROUTE]["get"]["responses"]["200"]["content"]["application/json"]["example"]
    _assert_complete_manifest(example)


def test_documentation_responds_while_manifest_request_is_still_delayed(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_waiting = Event()
    release_manifest = Event()

    def hold_manifest_delay(delay_seconds: float) -> None:
        assert delay_seconds > 0
        manifest_waiting.set()
        if not release_manifest.wait(timeout=10):
            raise TimeoutError("Test did not release the manifest request")

    # Gate the actual HTTP handler at its timeout boundary, without changing
    # the shared time module or relying on a sleep to guess request overlap.
    monkeypatch.setattr("tools.kernel_manifest_mock.server.time", SimpleNamespace(sleep=hold_manifest_delay))
    with _running_mock(Scenario.TIMEOUT) as client:
        with (
            httpx.Client(
                base_url=str(client.base_url),
                headers={"Authorization": f"Bearer {TOKEN}"},
                timeout=5,
                trust_env=False,
            ) as manifest_client,
            ThreadPoolExecutor(max_workers=1) as requests,
        ):
            pending_manifest = requests.submit(manifest_client.get, ROUTE, params=SCOPE)
            try:
                assert manifest_waiting.wait(timeout=2), "Manifest handler did not enter its delay"
                assert not pending_manifest.done()
                for path, content_type in (
                    ("/docs", "text/html; charset=utf-8"),
                    ("/openapi.json", "application/json"),
                ):
                    response = client.get(path, timeout=1)
                    assert response.status_code == 200
                    assert response.headers["content-type"] == content_type
                    assert not pending_manifest.done(), "Documentation waited for the manifest to finish"
                assert not release_manifest.is_set()
            finally:
                release_manifest.set()
            manifest = pending_manifest.result(timeout=2)
    assert manifest.status_code == 200
    _assert_complete_manifest(manifest.json())


@pytest.mark.parametrize("app_env", ["", "production", "staging"])
def test_mock_rejects_non_development_environment(app_env: str) -> None:
    with pytest.raises(ValueError, match="APP_ENV"):
        MockConfig(app_env=app_env, token=TOKEN)


@pytest.mark.parametrize("token", ["", " ", "token with spaces", "token\n", "не-секрет"])
def test_mock_requires_explicit_header_safe_development_token(token: str) -> None:
    with pytest.raises(ValueError, match="KERNEL_MOCK_TOKEN"):
        MockConfig(app_env="test", token=token)


@pytest.mark.parametrize("delay_seconds", [0, -1, 61, float("inf"), float("nan")])
def test_timeout_fault_has_a_bounded_delay(delay_seconds: float) -> None:
    with pytest.raises(ValueError, match="delay_seconds"):
        MockConfig(app_env="test", token=TOKEN, delay_seconds=delay_seconds)


def test_mock_is_excluded_from_docker_inputs() -> None:
    assert "tools/kernel_manifest_mock" in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "token=" not in repr(MockConfig(app_env="test", token=TOKEN))
