from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from app.composition.sources import source_resources
from app.domains.catalog.admission import SelectedCapabilityUnavailable, require_selected_capability
from app.domains.catalog.contracts import CapabilityManifest, SourceProvenance
from app.infrastructure.preflight import PreflightBudget, PreflightDeadlineExceeded, PreflightSaturated
from app.integrations.kernel.client import (
    KernelAuthenticationFailed,
    KernelManifestInvalid,
    KernelScopeForbidden,
    KernelScopeMismatch,
    KernelTimeout,
    KernelUnavailable,
)
from apps.api.tests.support.kernel import (
    CONTRACT,
    EXPECTED_DIGEST,
    TOKEN,
    independent_digest,
    kernel_settings,
    manifest_fixture,
    resign,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _fetch(payload: dict[str, Any]) -> CapabilityManifest:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with source_resources(kernel_settings(), kernel_transport=httpx.MockTransport(respond)) as sources:
        async with sources.preflight.operation() as budget:
            return await sources.require_kernel().fetch_manifest(budget=budget)


async def test_independent_literal_contract_and_fresh_get_on_every_operation() -> None:
    payload = manifest_fixture()
    assert payload["manifest_version"] == independent_digest(payload) == EXPECTED_DIGEST
    assert (CONTRACT / "fixtures/valid-manifest.digest").read_text().strip() == EXPECTED_DIGEST
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload)

    async with source_resources(kernel_settings(), kernel_transport=httpx.MockTransport(respond)) as sources:
        assert requests == []
        for _ in range(2):
            async with sources.preflight.operation() as budget:
                manifest = await sources.require_kernel().fetch_manifest(budget=budget)
                require_selected_capability(
                    manifest, product_id="proposal_ai", metric_units={"proposal_ai.test_generations": "generation"}
                )
                require_selected_capability(
                    manifest, product_id="brief_decoder", metric_units={"brief_decoder.test_analyses": "analysis"}
                )
                assert manifest.provenance is SourceProvenance.SIMULATED
                assert manifest.manifest_version == EXPECTED_DIGEST
                assert len(manifest.products) == 6
                assert manifest.generated_at.utcoffset() is not None
        assert sources.preflight.active_count == sources.preflight.waiting_count == 0
    assert len(requests) == 2
    for request in requests:
        assert request.method == "GET"
        assert request.url.path == "/internal/v1/capability-manifest"
        assert dict(request.url.params) == {"tenant_id": "anytoolai", "region": "ru"}
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert "origin" not in request.headers


async def test_two_different_metrics_may_share_a_product_and_order_timestamp_do_not_change_hash() -> None:
    payload = manifest_fixture()
    payload["usage_metrics"].append(
        {
            "metric_key": "proposal_ai.second_test_metric",
            "product_id": "proposal_ai",
            "unit": "generation",
            "enabled": True,
        }
    )
    resign(payload)
    digest = payload["manifest_version"]
    payload["products"].reverse()
    payload["usage_metrics"].reverse()
    payload["generated_at"] = "2026-10-16T10:00:00+08:00"
    manifest = await _fetch(payload)
    assert manifest.manifest_version == digest
    require_selected_capability(
        manifest,
        product_id="proposal_ai",
        metric_units={"proposal_ai.test_generations": "generation", "proposal_ai.second_test_metric": "generation"},
    )


@pytest.mark.parametrize(
    "field", ["schema_version", "tenant_id", "region", "manifest_version", "generated_at", "products", "usage_metrics"]
)
async def test_missing_required_field_is_not_repaired(field: str) -> None:
    payload = manifest_fixture()
    del payload[field]
    with pytest.raises(KernelManifestInvalid):
        await _fetch(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), True),
        (("schema_version",), 1.0),
        (("schema_version",), "1"),
        (("schema_version",), 2),
        (("tenant_id",), ""),
        (("region",), 1),
        (("generated_at",), "2026-10-16T00:00:00"),
        (("generated_at",), "2026-10-16"),
        (("generated_at",), 1792108800),
        (("generated_at",), "invalid"),
        (("products",), None),
        (("usage_metrics",), {}),
        (("unexpected",), "secret-from-remote"),
        (("products", 0, "enabled"), "false"),
        (("products", 0, "enabled"), 0),
        (("products", 0, "product_id"), ""),
        (("products", 0, "unexpected"), True),
        (("usage_metrics", 0, "enabled"), "true"),
        (("usage_metrics", 0, "unit"), ""),
        (("usage_metrics", 0, "metric_key"), ""),
        (("usage_metrics", 0, "product_id"), "unknown-test-product"),
        (("manifest_version",), "sha256:" + "0" * 64),
    ],
)
async def test_strict_schema_and_semantic_rejections(path: tuple[str | int, ...], value: Any) -> None:
    payload = manifest_fixture()
    target = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(KernelManifestInvalid) as error:
        await _fetch(payload)
    assert str(error.value) == "kernel_manifest_invalid"
    assert error.value.__cause__ is None


@pytest.mark.parametrize("collection", ["products", "usage_metrics"])
async def test_duplicate_identities_are_rejected(collection: str) -> None:
    payload = manifest_fixture()
    payload[collection].append(payload[collection][0].copy())
    resign(payload)
    with pytest.raises(KernelManifestInvalid):
        await _fetch(payload)


@pytest.mark.parametrize("field", ["tenant_id", "region"])
async def test_response_scope_must_match_even_with_a_correct_digest(field: str) -> None:
    payload = manifest_fixture()
    payload[field] = "other-test-scope"
    resign(payload)
    with pytest.raises(KernelScopeMismatch):
        await _fetch(payload)


@pytest.mark.parametrize(
    ("status", "failure"),
    [
        (401, KernelAuthenticationFailed),
        (403, KernelScopeForbidden),
        (500, KernelUnavailable),
        (503, KernelUnavailable),
        (302, KernelManifestInvalid),
    ],
)
async def test_status_errors_ignore_raw_bodies_and_do_not_follow_redirects(
    status: int, failure: type[Exception]
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, text=f"sensitive remote {TOKEN}", headers={"location": "http://other.test/"})

    async with source_resources(kernel_settings(), kernel_transport=httpx.MockTransport(respond)) as sources:
        with pytest.raises(failure) as error:
            async with sources.preflight.operation() as budget:
                await sources.require_kernel().fetch_manifest(budget=budget)
        assert sources.preflight.active_count == 0
    assert TOKEN not in str(error.value)
    assert len(requests) == 1


@pytest.mark.parametrize(
    ("body", "headers"),
    [
        (b"{", {"content-type": "application/json"}),
        (b"{}", {"content-type": "text/html"}),
        (b"{}", {"content-type": "application/json", "content-encoding": "gzip"}),
        (b"{}", {"content-type": "application/json", "content-length": "9999999"}),
        (b"{}", {"content-type": "application/json", "content-length": "-1"}),
        (b'{"schema_version":1,"schema_version":1}', {"content-type": "application/json"}),
        (b"\xff", {"content-type": "application/json"}),
    ],
)
async def test_malformed_or_oversized_response_fails_closed(body: bytes, headers: dict[str, str]) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=httpx.ByteStream(body), headers=headers)

    async with source_resources(kernel_settings(), kernel_transport=httpx.MockTransport(respond)) as sources:
        with pytest.raises(KernelManifestInvalid):
            async with sources.preflight.operation() as budget:
                await sources.require_kernel().fetch_manifest(budget=budget)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("disabled_product", "selected_product_disabled"),
        ("missing_product", "selected_product_missing"),
        ("disabled_metric", "selected_metric_disabled"),
        ("missing_metric", "selected_metric_missing"),
        ("other_owner", "selected_metric_owner_mismatch"),
        ("different_unit", "selected_metric_unit_mismatch"),
    ],
)
async def test_valid_manifest_and_selected_eligibility_are_separate(change: str, code: str) -> None:
    payload = manifest_fixture()
    if change == "disabled_product":
        next(item for item in payload["products"] if item["product_id"] == "proposal_ai")["enabled"] = False
    elif change == "missing_product":
        payload["products"] = [item for item in payload["products"] if item["product_id"] != "proposal_ai"]
        payload["usage_metrics"] = [
            metric for metric in payload["usage_metrics"] if metric["product_id"] != "proposal_ai"
        ]
    elif change == "disabled_metric":
        payload["usage_metrics"][0]["enabled"] = False
    elif change == "missing_metric":
        payload["usage_metrics"] = [
            metric for metric in payload["usage_metrics"] if metric["product_id"] != "proposal_ai"
        ]
    elif change == "other_owner":
        payload["usage_metrics"][0]["product_id"] = "kernel_demo"
    elif change == "different_unit":
        payload["usage_metrics"][0]["unit"] = "other-test-unit"
    manifest = await _fetch(resign(payload))
    with pytest.raises(SelectedCapabilityUnavailable) as error:
        require_selected_capability(
            manifest, product_id="proposal_ai", metric_units={"proposal_ai.test_generations": "generation"}
        )
    assert error.value.code == code


async def test_transport_failure_retry_uses_same_budget_and_releases_slots() -> None:
    requests = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            raise httpx.ConnectError(f"sensitive {TOKEN}", request=request)
        return httpx.Response(200, json=manifest_fixture())

    async with source_resources(
        kernel_settings(kernel_max_retries=1, kernel_retry_delay_seconds=0),
        kernel_transport=httpx.MockTransport(respond),
    ) as sources:
        async with sources.preflight.operation() as budget:
            deadline = budget.deadline
            manifest = await sources.require_kernel().fetch_manifest(budget=budget)
            assert budget.deadline == deadline
            assert manifest.manifest_version == EXPECTED_DIGEST
        assert sources.preflight.active_count == sources.preflight.waiting_count == 0
    assert requests == 2


async def test_bounded_subtimeout_retries_then_safe_timeout_failure() -> None:
    requests = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        raise httpx.ReadTimeout(f"sensitive {TOKEN}", request=request)

    async with source_resources(
        kernel_settings(kernel_max_retries=1, kernel_retry_delay_seconds=0),
        kernel_transport=httpx.MockTransport(respond),
    ) as sources:
        with pytest.raises(KernelTimeout) as error:
            async with sources.preflight.operation() as budget:
                await sources.require_kernel().fetch_manifest(budget=budget)
        assert sources.preflight.active_count == 0
    assert requests == 2
    assert TOKEN not in str(error.value)


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_and_authorization_failures_are_not_retried(status: int) -> None:
    requests = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(status)

    async with source_resources(
        kernel_settings(kernel_max_retries=2), kernel_transport=httpx.MockTransport(respond)
    ) as sources:
        with pytest.raises((KernelAuthenticationFailed, KernelScopeForbidden)):
            async with sources.preflight.operation() as budget:
                await sources.require_kernel().fetch_manifest(budget=budget)
        assert sources.preflight.active_count == sources.preflight.waiting_count == 0
    assert requests == 1


async def test_retry_delay_cannot_restart_whole_deadline() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with source_resources(
        kernel_settings(
            preflight_total_timeout_seconds=0.08,
            preflight_cleanup_timeout_seconds=0.01,
            kernel_max_retries=2,
            kernel_retry_delay_seconds=0.1,
        ),
        kernel_transport=httpx.MockTransport(respond),
    ) as sources:
        with pytest.raises(PreflightDeadlineExceeded):
            async with sources.preflight.operation() as budget:
                await sources.require_kernel().fetch_manifest(budget=budget)
        assert sources.preflight.active_count == sources.preflight.waiting_count == 0


async def test_streamed_body_without_content_length_is_size_bounded_and_closed() -> None:
    class OversizedStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b" " * 700
            yield b" " * 700
            pytest.fail("client must stop consuming once the size limit is exceeded")

        async def aclose(self) -> None:
            self.closed = True

    stream = OversizedStream()

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream, headers={"content-type": "application/json"})

    async with source_resources(
        kernel_settings(kernel_max_response_bytes=1024), kernel_transport=httpx.MockTransport(respond)
    ) as sources:
        with pytest.raises(KernelManifestInvalid):
            async with sources.preflight.operation() as budget:
                await sources.require_kernel().fetch_manifest(budget=budget)
        assert stream.closed
        assert sources.preflight.active_count == 0


async def test_real_http_trickling_body_exceeds_absolute_deadline_despite_read_progress() -> None:
    peer_closed = asyncio.Event()
    fragments = 0

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal fragments
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 10000\r\n\r\n")
            # Every fragment arrives well inside the 0.1s individual read wait;
            # the full body would take 100s without a whole-operation bound.
            for _ in range(10000):
                if reader.at_eof():
                    break
                writer.write(b" ")
                await writer.drain()
                fragments += 1
                await asyncio.sleep(0.01)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            peer_closed.set()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with source_resources(
            kernel_settings(
                kernel_base_url=f"http://127.0.0.1:{port}",
                preflight_total_timeout_seconds=0.2,
                preflight_cleanup_timeout_seconds=0.03,
                kernel_read_timeout_seconds=0.1,
            )
        ) as sources:
            loop = asyncio.get_running_loop()
            started = loop.time()
            with pytest.raises(PreflightDeadlineExceeded):
                async with sources.preflight.operation() as budget:
                    await sources.require_kernel().fetch_manifest(budget=budget)
            elapsed = loop.time() - started
            assert elapsed < 0.35  # scheduling tolerance; not a per-read timeout
            assert fragments >= 2
            assert sources.preflight.active_count == sources.preflight.waiting_count == 0
            await asyncio.wait_for(peer_closed.wait(), timeout=1)
    finally:
        server.close()
        await server.wait_closed()


async def test_client_consumes_accepted_step_one_mock_over_actual_http() -> None:
    from threading import Thread

    from tools.kernel_manifest_mock.server import ManifestMockServer, MockConfig

    with ManifestMockServer(("127.0.0.1", 0), MockConfig(app_env="test", token=TOKEN)) as server:
        worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        try:
            async with source_resources(
                kernel_settings(kernel_base_url=f"http://127.0.0.1:{server.server_port}")
            ) as sources:
                async with sources.preflight.operation() as budget:
                    manifest = await sources.require_kernel().fetch_manifest(budget=budget)
                assert manifest.manifest_version == EXPECTED_DIGEST
                assert manifest.provenance is SourceProvenance.SIMULATED
        finally:
            server.shutdown()
            worker.join(timeout=2)
            assert not worker.is_alive()


async def test_two_http_consumers_cannot_each_take_a_full_new_budget() -> None:
    requests = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        await asyncio.sleep(0.07)
        return httpx.Response(200, json=manifest_fixture())

    async with source_resources(
        kernel_settings(preflight_total_timeout_seconds=0.13, preflight_cleanup_timeout_seconds=0.02),
        kernel_transport=httpx.MockTransport(respond),
    ) as sources:
        with pytest.raises(PreflightDeadlineExceeded):
            async with sources.preflight.operation() as budget:
                deadline = budget.deadline
                await sources.require_kernel().fetch_manifest(budget=budget)
                assert budget.deadline == deadline
                await sources.require_kernel().fetch_manifest(budget=budget)
        assert requests == 2
        assert sources.preflight.active_count == sources.preflight.waiting_count == 0


async def test_cancelled_http_read_keeps_capacity_occupied_until_stream_close_finishes() -> None:
    class DelayedCloseStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.entered = asyncio.Event()
            self.closing = asyncio.Event()
            self.allow_close = asyncio.Event()
            self.closed = asyncio.Event()

        async def __aiter__(self) -> AsyncIterator[bytes]:
            self.entered.set()
            await asyncio.Event().wait()
            yield b"unreachable"

        async def aclose(self) -> None:
            self.closing.set()
            await self.allow_close.wait()
            self.closed.set()

    stream = DelayedCloseStream()

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream, headers={"content-type": "application/json"})

    async with source_resources(
        kernel_settings(preflight_max_active=1, preflight_max_waiting=0, preflight_cleanup_timeout_seconds=0.02),
        kernel_transport=httpx.MockTransport(respond),
    ) as sources:

        async def read() -> None:
            async with sources.preflight.operation() as budget:
                await sources.require_kernel().fetch_manifest(budget=budget)

        task = asyncio.create_task(read())
        await stream.entered.wait()
        task.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await task
            assert stream.closing.is_set() and not stream.closed.is_set()
            assert sources.preflight.active_count == 1
            with pytest.raises(PreflightSaturated):
                async with sources.preflight.operation():
                    pytest.fail("HTTP cleanup must retain its slot")
        finally:
            stream.allow_close.set()
            await stream.closed.wait()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        assert sources.preflight.active_count == sources.preflight.waiting_count == 0


@pytest.mark.parametrize("termination", ["cancel", "deadline"])
async def test_complete_http_body_cleanup_retains_slot_after_cancellation_or_deadline(termination: str) -> None:
    class CompleteBodyDelayedCloseStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.body_consumed = asyncio.Event()
            self.closing = asyncio.Event()
            self.allow_close = asyncio.Event()
            self.closed = asyncio.Event()
            self.close_cancelled = asyncio.Event()
            self.close_calls = 0

        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield json.dumps(manifest_fixture()).encode("utf-8")
            self.body_consumed.set()

        async def aclose(self) -> None:
            self.close_calls += 1
            self.closing.set()
            try:
                await self.allow_close.wait()
            except asyncio.CancelledError:
                self.close_cancelled.set()
                raise
            self.closed.set()

    stream = CompleteBodyDelayedCloseStream()
    responses: list[httpx.Response] = []

    def respond(request: httpx.Request) -> httpx.Response:
        response = (
            httpx.Response(200, stream=stream, headers={"content-type": "application/json"})
            if not responses
            else httpx.Response(200, json=manifest_fixture())
        )
        responses.append(response)
        return response

    async with source_resources(
        kernel_settings(
            preflight_max_active=1,
            preflight_max_waiting=1,
            preflight_total_timeout_seconds=1,
            preflight_cleanup_timeout_seconds=0.02,
        ),
        kernel_transport=httpx.MockTransport(respond),
    ) as sources:
        first_admitted = asyncio.Event()
        first_budgets: list[PreflightBudget] = []

        async def read() -> CapabilityManifest:
            async with sources.preflight.operation() as budget:
                first_budgets.append(budget)
                first_admitted.set()
                return await sources.require_kernel().fetch_manifest(budget=budget)

        caller = asyncio.create_task(read())
        queued: asyncio.Task[CapabilityManifest] | None = None
        try:
            await asyncio.wait_for(stream.closing.wait(), timeout=0.5)
            assert first_admitted.is_set() and stream.body_consumed.is_set()
            assert first_budgets[0].remaining_seconds() > 0
            # HTTPX's flag is already true, although the transport has not
            # finished closing. The first close must survive cancellation.
            assert responses[0].is_closed
            assert not stream.closed.is_set()
            if termination == "cancel":
                caller.cancel()
            done, _ = await asyncio.wait({caller}, timeout=1.5 if termination == "deadline" else 0.5)
            assert caller in done
            if termination == "cancel":
                with pytest.raises(asyncio.CancelledError):
                    caller.result()
            else:
                with pytest.raises(PreflightDeadlineExceeded):
                    caller.result()
            assert sources.preflight.active_count == 1
            assert not stream.closed.is_set() and not stream.close_cancelled.is_set()
            assert stream.close_calls == 1

            queued_attempted = asyncio.Event()
            queued_admitted = asyncio.Event()

            async def next_read() -> CapabilityManifest:
                queued_attempted.set()
                async with sources.preflight.operation() as budget:
                    queued_admitted.set()
                    return await sources.require_kernel().fetch_manifest(budget=budget)

            queued = asyncio.create_task(next_read())
            await asyncio.wait_for(queued_attempted.wait(), timeout=0.5)
            assert not queued_admitted.is_set()
            assert sources.preflight.active_count == sources.preflight.waiting_count == 1
            with pytest.raises(PreflightSaturated):
                async with sources.preflight.operation():
                    pytest.fail("unfinished HTTP cleanup must not admit extra source work")
            assert len(responses) == 1

            stream.allow_close.set()
            done, _ = await asyncio.wait({queued}, timeout=0.5)
            assert queued in done
            manifest = queued.result()
            assert stream.closed.is_set() and not stream.close_cancelled.is_set()
            assert stream.close_calls == 1
            assert queued_admitted.is_set()
            assert manifest.manifest_version == EXPECTED_DIGEST
            assert len(responses) == 2
            assert sources.preflight.active_count == sources.preflight.waiting_count == 0
        finally:
            stream.allow_close.set()
            tasks = {caller} if queued is None else {caller, queued}
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.wait(tasks, timeout=1.5)
            for task in tasks:
                if task.done() and not task.cancelled():
                    task.exception()
