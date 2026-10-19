from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from scripts import check_kernel_references as watch


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


SOURCES = {
    "manifest-spec": """## Service authentication
TLS, trusted services, no browser access.
## Capability Manifest
### Request ownership
GET /internal/v1/capability-manifest
### Response
schema_version, tenant_id, region, manifest_version, generated_at, products, usage_metrics
### `enabled` semantics
Enabled permits new bindings only.
### HTTP semantics
200 complete, 401 invalid auth, 403 scope, 5xx unavailable.
### Portal import and freshness
Historical source strategy outside the watch.
""",
    "composition": """DEFAULT_PRODUCT_BUNDLES: tuple = (FreelancerSuiteBundle(),)
def build_runtime():
    extra_product_roots = [root for bundle in bundles for root in bundle.config_roots()]
    registry = build_config_registry(config_root, extra_product_roots=extra_product_roots)
    return Result(loaded_bundles=["kernel_demo", "freelancer_suite"])
""",
    "registry": """class ConfigRegistry:
    products: Mapping[str, ProductDefinition]
    def get_product(self, product_id: str):
        return self.products.get(product_id)
""",
    "bundle": """class FreelancerSuiteBundle:
    bundle_id = "freelancer_suite"
    def config_roots(self):
        return [Path("products") / "proposal_ai", Path("products") / "client_update_writer",
                Path("products") / "brief_decoder", Path("products") / "acceptance_builder",
                Path("products") / "task_finder"]
""",
    "selected-product": "product_id: proposal_ai\nproduct_platform: freelancer_suite\nquota_policy_ref: test.guest\n",
}
CURRENT_SHA = "a" * 40


async def reference_report(
    *,
    changes: dict[str, str] | None = None,
    failure_status: int | None = None,
    unavailable_kind: str | None = None,
) -> dict[str, Any]:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "api.github.com"
        assert request.method == "GET"
        if failure_status:
            return httpx.Response(failure_status, text="private source body must not be printed")
        if "/commits/" in request.url.path:
            return httpx.Response(200, json={"sha": CURRENT_SHA})
        if "/contents/" not in request.url.path:
            return httpx.Response(200, json={"default_branch": "main"})
        reference = next(item for item in watch.REFERENCES if request.url.path.endswith("/contents/" + item.path))
        if reference.projection == unavailable_kind:
            return httpx.Response(403, text="private source body must not be printed")
        source = SOURCES[reference.projection]
        if request.url.params["ref"] == CURRENT_SHA:
            source = (changes or {}).get(reference.projection, source)
        else:
            assert request.url.params["ref"] == reference.pin
        assert request.headers["accept"] == "application/vnd.github.raw+json"
        return httpx.Response(200, text=source)

    async with httpx.AsyncClient(
        base_url="https://api.github.com", transport=httpx.MockTransport(respond), follow_redirects=False
    ) as http:
        result = await watch.check_references(http)
    assert len(requests) <= 14  # Two repo/default-head reads plus two reads for five sources; no retries.
    return result


async def test_advanced_repo_heads_off_fixture_products_and_guest_policy_are_not_drift() -> None:
    changed_bundle = SOURCES["bundle"].replace(
        'Path("products") / "task_finder"',
        'Path("products") / "task_finder", Path("products") / "unrelated_new_product"',
    )
    report = await reference_report(
        changes={
            "bundle": changed_bundle,
            "selected-product": SOURCES["selected-product"].replace("test.guest", "changed.guest"),
            "registry": SOURCES["registry"] + "\n# unrelated implementation comment\n",
            "manifest-spec": SOURCES["manifest-spec"] + "\nUnrelated later documentation\n",
        }
    )
    assert report["REFERENCE_SOURCE_CHECK"] == "PASS"
    assert report["source_access_complete"] is True
    assert report["LOCAL_SPEC_CONFORMANCE"] == "NOT_RUN"
    assert report["REAL_KERNEL_CONFORMANCE"] == "DEFERRED_NOT_IMPLEMENTED"
    assert report["REFERENCE_WATCH_OPERATIONAL"] == "NOT_YET_OPERATIONAL"
    assert all(item["observed_commit"] == CURRENT_SHA for item in report["references"])


@pytest.mark.parametrize("kind", list(SOURCES))
async def test_selected_reference_change_reports_fingerprints_and_requires_review(kind: str) -> None:
    substitutions = {
        "manifest-spec": ("200 complete", "200 partial allowed"),
        "composition": ("FreelancerSuiteBundle()", "DifferentBundle()"),
        "registry": ("Mapping[str, ProductDefinition]", "Mapping[str, OtherDefinition]"),
        "bundle": ('"proposal_ai"', '"renamed_product"'),
        "selected-product": ("product_id: proposal_ai", "product_id: renamed_product"),
    }
    before, after = substitutions[kind]
    report = await reference_report(changes={kind: SOURCES[kind].replace(before, after)})
    assert report["REFERENCE_SOURCE_CHECK"] == "CHANGE_REVIEW_REQUIRED"
    changed = [item for item in report["references"] if item["status"] == "CHANGE_REVIEW_REQUIRED"]
    assert len(changed) == 1
    assert changed[0]["pinned_fingerprint"] != changed[0]["observed_fingerprint"]


async def test_accessible_removed_manifest_section_requires_review() -> None:
    report = await reference_report(changes={"manifest-spec": "# Contract replaced\n"})
    assert report["REFERENCE_SOURCE_CHECK"] == "CHANGE_REVIEW_REQUIRED"
    assert report["references"][0]["observed_fingerprint"] == "UNRECOGNIZED_SOURCE_STRUCTURE"


async def test_known_drift_is_reported_when_a_later_source_is_inaccessible() -> None:
    report = await reference_report(
        changes={"manifest-spec": SOURCES["manifest-spec"].replace("200 complete", "200 partial allowed")},
        unavailable_kind="registry",
    )
    assert report["REFERENCE_SOURCE_CHECK"] == "CHANGE_REVIEW_REQUIRED"
    assert report["source_access_complete"] is False
    assert report["unavailable_reference"]["status"] == "UNKNOWN_SOURCE_CHECK"
    assert report["unavailable_reference"]["repository"] == watch.KERNEL
    assert report["unavailable_reference"]["path"].endswith("registry.py")


@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_source_access_failure_is_unknown_with_no_raw_body_or_url_fallback(status: int) -> None:
    report = await reference_report(failure_status=status)
    assert report["REFERENCE_SOURCE_CHECK"] == "UNKNOWN_SOURCE_CHECK"
    assert report["source_access_complete"] is False
    assert "private source body" not in json.dumps(report)
    assert report["LOCAL_SPEC_CONFORMANCE"] == "NOT_RUN"


async def test_whole_watch_deadline_bounds_slow_fragment_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    from collections.abc import AsyncIterator

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            while True:
                await asyncio.sleep(0.005)
                yield b" "

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(watch, "MAX_SECONDS", 0.03)
    async with httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=SlowStream())),
    ) as http:
        async with asyncio.timeout(1):
            report = await watch.check_references(http)
    assert report["REFERENCE_SOURCE_CHECK"] == "UNKNOWN_SOURCE_CHECK"


async def test_response_limit_is_unknown() -> None:
    async with httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"x" * (watch.MAX_RESPONSE_BYTES + 1))
        ),
    ) as http:
        report = await watch.check_references(http)
    assert report["REFERENCE_SOURCE_CHECK"] == "UNKNOWN_SOURCE_CHECK"
