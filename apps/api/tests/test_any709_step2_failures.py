"""Review regressions using only isolated HTTP transports; no real LBX calls."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

import httpx
import pytest

from app.composition.sources import source_resources
from app.core.observability import JsonFormatter, request_id_context
from app.infrastructure.preflight import PreflightDeadlineExceeded
from app.integrations.lbx.customer import NewCustomer, sign_widget_jwt
from app.integrations.lbx.errors import (
    LbxAuthenticationFailed,
    LbxCreateNotSent,
    LbxProviderRejected,
    LbxRateLimited,
    LbxResponseInvalid,
    LbxTimeout,
    LbxUnavailable,
)
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.lbx import PASSWORD, USERNAME


@pytest.mark.parametrize(
    "failure,expected,attempts",
    [
        (503, LbxProviderRejected, 3),
        (429, LbxRateLimited, 3),
        ("timeout", LbxTimeout, 3),
        (401, LbxAuthenticationFailed, 1),
        ("invalid", LbxResponseInvalid, 1),
    ],
)
def test_any709_step2_preauth_failures_are_typed_and_never_create(
    failure: int | str, expected: type[Exception], attempts: int
) -> None:
    calls: list[tuple[str, str]] = []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if failure == "timeout":
            raise httpx.ReadTimeout("private transport error", request=request)
        if failure == "invalid":
            return httpx.Response(200, json={"code": 200, "response": {}})
        return httpx.Response(failure, json={"code": failure}, headers={"Retry-After": "0"})

    async def scenario() -> None:
        config = step1_settings(lbx_max_get_attempts=3)
        async with source_resources(config, lbx_transport=httpx.MockTransport(transport)) as sources:
            async with sources.billing.operation() as budget:
                deadline = budget.deadline
                with pytest.raises(expected):
                    await sources.lbx.prepare_customer_create(budget=budget)
                assert budget.deadline == deadline

    asyncio.run(scenario())
    assert calls == [("GET", "/api/rest/v1/auth")] * attempts


@pytest.mark.parametrize("refusal", ["deadline", "closed", "busy"])
def test_any709_step2_budget_refusal_before_scheduling_is_definitely_unsent(refusal: str) -> None:
    calls: list[str] = []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json={"code": 200, "response": {"token": "private-server", "expires_in": 600}})

    async def scenario() -> None:
        async with source_resources(step1_settings(), lbx_transport=httpx.MockTransport(transport)) as sources:
            async with sources.billing.operation() as budget:
                await sources.lbx.prepare_customer_create(budget=budget)
                original_deadline = budget.work_deadline
                release = asyncio.Event()
                entered = asyncio.Event()

                async def occupied() -> None:
                    entered.set()
                    await release.wait()

                task = None
                if refusal == "deadline":
                    budget._work_deadline = 0
                elif refusal == "closed":
                    sources.billing.closed = True
                else:
                    task = asyncio.create_task(budget.run(occupied))
                    await entered.wait()
                try:
                    with pytest.raises(LbxCreateNotSent):
                        await sources.lbx.create_user(
                            NewCustomer(outer_id="opaque", email="synthetic@example.com"), budget=budget
                        )
                finally:
                    release.set()
                    if task is not None:
                        await task
                    # Let the enclosing operation close normally after the injected refusal.
                    budget._work_deadline = original_deadline
                    sources.billing.closed = False

    asyncio.run(scenario())
    assert calls == ["GET"]


def test_any709_step2_running_post_after_deadline_is_not_reported_unsent() -> None:
    async def scenario() -> None:
        release = asyncio.Event()
        still_running = asyncio.Event()
        finished = asyncio.Event()
        posts: list[str] = []

        async def transport(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/auth"):
                return httpx.Response(
                    200, json={"code": 200, "response": {"token": "private-server", "expires_in": 600}}
                )
            posts.append(request.method)
            try:
                await release.wait()
            except asyncio.CancelledError:
                still_running.set()
                await release.wait()  # Transport deliberately outlives its waiter.
            finished.set()
            return httpx.Response(201, json={"code": 201, "response": {"user_id": 345}})

        config = step1_settings(preflight_total_timeout_seconds=0.2, preflight_cleanup_timeout_seconds=0.03)
        async with source_resources(config, lbx_transport=httpx.MockTransport(transport)) as sources:
            try:
                with pytest.raises(PreflightDeadlineExceeded):
                    async with sources.billing.operation() as budget:
                        await sources.lbx.prepare_customer_create(budget=budget)
                        await sources.lbx.create_user(
                            NewCustomer(outer_id="opaque", email="synthetic@example.com"), budget=budget
                        )
                await still_running.wait()
                assert sources.billing.active_count == 1
                assert posts == ["POST"]
            finally:
                release.set()
                await asyncio.wait_for(finished.wait(), timeout=1)
                # Allow the same counted task's final budget check and callback to finish.
                async with asyncio.timeout(1):
                    while sources.billing.active_count:
                        await asyncio.sleep(0)

    asyncio.run(scenario())


@pytest.mark.parametrize("known", [True, False])
def test_any709_step2_client_error_has_only_allowlisted_diagnostics(
    known: bool, caplog: pytest.LogCaptureFixture
) -> None:
    config = step1_settings()
    token = sign_widget_jwt(customer_id="345", secret=config.lbx_widget_signing_secret)
    private = [
        "private-login",
        "private-password",
        "synthetic@example.com",
        "Private Surname",
        token.get_secret_value(),
        USERNAME,
        PASSWORD,
    ]
    response_text = ("Invalid login/pass. Client login: " if known else "Unrecognized provider error: ") + " ".join(
        private
    )

    def transport(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/client/user")
        return httpx.Response(500, json={"code": 401 if known else 500, "response": response_text})

    async def scenario() -> None:
        context = request_id_context.set("safe-request-123")
        try:
            async with source_resources(config, lbx_transport=httpx.MockTransport(transport)) as sources:
                async with sources.billing.operation() as budget:
                    with pytest.raises(LbxAuthenticationFailed if known else LbxProviderRejected) as caught:
                        await sources.lbx.client_user(token=token, budget=budget)
                    assert all(value not in str(caught.value) for value in private)
        finally:
            request_id_context.reset(context)

    with caplog.at_level(logging.DEBUG):
        asyncio.run(scenario())
    diagnostics = [record.structured for record in caplog.records if record.getMessage() == "lbx_http"]
    assert len(diagnostics) == 1 and diagnostics[0]["duration_ms"] >= 0
    diagnostics = [{key: value for key, value in item.items() if key != "duration_ms"} for item in diagnostics]
    assert diagnostics == [
        {
            "stage": "client_readiness",
            "method": "GET",
            "endpoint": "/client/user",
            "status": 500,
            "lbx_code": 401 if known else 500,
            "reason": "credentials_denied" if known else "provider_rejected",
            "provider_error_present": False,
            "failure_kind": "authorization" if known else "provider",
            "retryable_get": not known,
            "request_id": "safe-request-123",
            "create_operation_id": None,
        }
    ]
    evidence = (
        caplog.text + json.dumps(diagnostics) + "".join(JsonFormatter().format(record) for record in caplog.records)
    )
    assert all(value not in evidence for value in private)
    assert response_text not in evidence


@pytest.mark.parametrize(
    "body", [b'{"code":500,"response":"' + b"x" * 2048 + b'"}', b'{"code":500,"code":401}', b"not json"]
)
def test_any709_step2_invalid_error_envelope_never_supplies_a_reason(
    body: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    async def scenario() -> None:
        config = step1_settings(lbx_max_response_bytes=1024)
        async with source_resources(
            config,
            lbx_transport=httpx.MockTransport(
                lambda _: httpx.Response(500, content=body, headers={"Content-Type": "application/json"})
            ),
        ) as sources:
            async with sources.billing.operation() as budget:
                with pytest.raises(LbxUnavailable):
                    await sources.lbx.client_user(
                        token=sign_widget_jwt(customer_id="345", secret=config.lbx_widget_signing_secret), budget=budget
                    )

    with caplog.at_level(logging.INFO):
        asyncio.run(scenario())
    facts = [record.structured for record in caplog.records if record.getMessage() == "lbx_http"]
    assert len(facts) == 1 and facts[0]["reason"] == "schema_invalid" and facts[0]["lbx_code"] is None


def test_any709_step2_chunked_error_body_stops_at_the_existing_size_cap() -> None:
    chunks: list[int] = []
    closed: list[bool] = []

    class ErrorStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            for index in range(3):
                chunks.append(index)
                yield b"x" * 700

        async def aclose(self) -> None:
            closed.append(True)

    async def scenario() -> None:
        config = step1_settings(lbx_max_response_bytes=1024)
        async with source_resources(
            config,
            lbx_transport=httpx.MockTransport(
                lambda _: httpx.Response(500, stream=ErrorStream(), headers={"Content-Type": "application/json"})
            ),
        ) as sources:
            async with sources.billing.operation() as budget:
                with pytest.raises(LbxUnavailable):
                    await sources.lbx.client_user(
                        token=sign_widget_jwt(customer_id="345", secret=config.lbx_widget_signing_secret), budget=budget
                    )

    asyncio.run(scenario())
    assert chunks == [0, 1] and closed == [True]
