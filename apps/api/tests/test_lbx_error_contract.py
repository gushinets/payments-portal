"""Synthetic Server API failures share classification, safe facts and GET-only retries."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import asdict

import httpx
import pytest

from app.core.observability import request_id_context
from app.integrations.lbx._transport import customer_diagnostics
from app.integrations.lbx.customer import LbxUser, NewCustomer
from app.integrations.lbx.dto import LbxEnvelope
from app.integrations.lbx.errors import (
    LbxAuthenticationFailed,
    LbxCreateNotSent,
    LbxError,
    LbxProviderRejected,
    LbxRateLimited,
    LbxResponseInvalid,
    LbxScopeForbidden,
    LbxTimeout,
    LbxUnavailable,
)
from apps.api.tests.support.lbx import TARIFF, fixture_response, lbx_source

pytestmark = pytest.mark.anyio
PRIVATE = "private@example.test Private-Name password=private-pass token=private-token"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize(
    "status,code,message,expected,kind,retry",
    [
        (500, 500, PRIVATE, LbxProviderRejected, "provider", True),
        (500, 500, f"Invalid email {PRIVATE}. Email must be unique", LbxProviderRejected, "provider", False),
        (500, 500, f"Invalid login/pass. Client login: {PRIVATE}", LbxAuthenticationFailed, "authorization", False),
        (200, 400, PRIVATE, LbxProviderRejected, "provider", False),
        (200, 500, PRIVATE, LbxProviderRejected, "provider", True),
        (200, 200, PRIVATE, LbxProviderRejected, "provider", False),
        (200, 401, PRIVATE, LbxAuthenticationFailed, "authorization", False),
        (200, 403, PRIVATE, LbxScopeForbidden, "authorization", False),
        (200, 429, PRIVATE, LbxRateLimited, "rate_limit", True),
        (400, 400, PRIVATE, LbxProviderRejected, "provider", False),
        (401, 500, PRIVATE, LbxAuthenticationFailed, "authorization", False),
        (403, 500, PRIVATE, LbxScopeForbidden, "authorization", False),
        (409, 409, PRIVATE, LbxProviderRejected, "provider", False),
        (429, 429, PRIVATE, LbxRateLimited, "rate_limit", True),
        (502, 502, PRIVATE, LbxProviderRejected, "provider", True),
        (503, 503, PRIVATE, LbxProviderRejected, "provider", True),
        (504, 504, PRIVATE, LbxProviderRejected, "provider", True),
    ],
)
async def test_shared_error_envelope_and_independent_retry_policy(
    method: str,
    status: int,
    code: int,
    message: str,
    expected: type[LbxError],
    kind: str,
    retry: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path.endswith("/auth"):
            return fixture_response("auth")
        calls += 1
        return httpx.Response(status, json={"code": code, "response": {"error": message}})

    context = request_id_context.set("safe-request")
    try:
        with caplog.at_level(logging.DEBUG):
            async with lbx_source(httpx.MockTransport(respond), lbx_max_get_attempts=3) as (client, owner):
                async with owner.operation() as budget:
                    await client.prepare_customer_create(budget=budget)
                    with customer_diagnostics("safe-operation"), pytest.raises(expected) as caught:
                        if method == "POST":
                            await client.create_user(
                                NewCustomer(outer_id="opaque", email="synthetic@example.com"), budget=budget
                            )
                        else:
                            await client.get_tariff(tariff_id=TARIFF, budget=budget)
    finally:
        request_id_context.reset(context)
    assert calls == (1 if method == "POST" else 3 if retry else 2 if expected is LbxAuthenticationFailed else 1)
    facts = caught.value.response_facts
    assert facts is not None
    assert (facts.http_status, facts.lbx_code, facts.failure_kind) == (status, code, kind)
    assert facts.provider_error_present and facts.retryable_get == retry
    assert facts.reason == (
        "email_not_unique"
        if "Email must be unique" in message
        else "credentials_denied"
        if message.startswith("Invalid login/pass")
        else "provider_rejected"
    )
    assert facts.method == method and facts.endpoint == ("/users" if method == "POST" else "/tariffs/{id}")
    assert facts.request_id == "safe-request" and facts.create_operation_id == "safe-operation"
    records = [
        r.structured for r in caplog.records if r.getMessage() == "lbx_http" and r.structured["endpoint"] != "/auth"
    ]
    assert len(records) == calls and records[-1]["failure_kind"] == kind
    rendered = caplog.text + repr(records) + repr(caught.value) + str(caught.value) + repr(asdict(facts))
    for private in (PRIVATE, "private@example.test", "Private-Name", "private-pass", "private-token"):
        assert private not in rendered


@pytest.mark.parametrize("path", ["/users", "/tariffs", "/agreements", "/subscriptions"])
async def test_error_decoding_is_endpoint_independent(path: str) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth"):
            return fixture_response("auth")
        return httpx.Response(500, json={"code": 500, "response": {"error": PRIVATE}})

    async with lbx_source(httpx.MockTransport(respond), lbx_max_get_attempts=2) as (client, owner):
        with pytest.raises(LbxProviderRejected) as caught:
            async with owner.operation() as budget:
                await client._read(path, LbxEnvelope[list[LbxUser]], budget=budget)
    assert caught.value.response_facts.endpoint == path


@pytest.mark.parametrize("status", [200, 500])
@pytest.mark.parametrize("value", [None, "", "  ", 5, False, [], {}, [PRIVATE]])
async def test_invalid_error_fields_are_not_successful_customer_dtos(status: int, value: object) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth"):
            return fixture_response("auth")
        # LbxUser normally discards unknown credential fields; error must be
        # refused before even a valid user identity can reach that DTO.
        return httpx.Response(status, json={"code": status, "response": {"user_id": 345, "error": value}})

    async with lbx_source(httpx.MockTransport(respond)) as (client, owner):
        with pytest.raises(LbxResponseInvalid) as caught:
            async with owner.operation() as budget:
                await client.get_user(user_id=345, budget=budget)
    facts = caught.value.response_facts
    assert facts.provider_error_present and facts.reason == "schema_invalid"
    assert facts.failure_kind == "invalid_response" and facts.retryable_get == (status == 500)


@pytest.mark.parametrize(
    "status,body,expected,kind,retry",
    [
        (500, b'{"code":200,"response":[]}', LbxUnavailable, "unavailable", True),
        (500, b"{}", LbxUnavailable, "unavailable", True),
        (500, b'{"code":500}', LbxProviderRejected, "provider", True),
        (200, b'{"code":409}', LbxProviderRejected, "provider", False),
        (200, b'{"code":200,"response":{"error":"opaque"}}', LbxProviderRejected, "provider", False),
        (200, b'{"code":"500","response":{"error":"opaque"}}', LbxResponseInvalid, "invalid_response", False),
        (200, b'{"code":true,"response":{"error":"opaque"}}', LbxResponseInvalid, "invalid_response", False),
        (200, b'{"code":200,"response":{}}', LbxResponseInvalid, "invalid_response", False),
        (200, b"null", LbxResponseInvalid, "invalid_response", False),
        (200, b"[]", LbxResponseInvalid, "invalid_response", False),
        (200, b"not json", LbxResponseInvalid, "invalid_response", False),
        (500, b"not json", LbxUnavailable, "unavailable", True),
        (502, b"not json", LbxUnavailable, "unavailable", True),
        (503, b"not json", LbxUnavailable, "unavailable", True),
        (504, b"not json", LbxUnavailable, "unavailable", True),
        (200, b" " * 1025, LbxResponseInvalid, "invalid_response", False),
        (500, b" " * 1025, LbxUnavailable, "unavailable", True),
    ],
)
async def test_codes_invalid_envelopes_and_non_provider_failures(
    status: int,
    body: bytes,
    expected: type[LbxError],
    kind: str,
    retry: bool,
) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path.endswith("/auth"):
            return fixture_response("auth")
        calls += 1
        return httpx.Response(status, content=body, headers={"Content-Type": "application/json"})

    async with lbx_source(httpx.MockTransport(respond), lbx_max_get_attempts=3, lbx_max_response_bytes=1024) as (
        client,
        owner,
    ):
        with pytest.raises(expected) as caught:
            async with owner.operation() as budget:
                await client.get_user(user_id=345, budget=budget)
    assert calls == (2 if retry else 1)  # initial auth consumes one of three attempts
    facts = caught.value.response_facts
    assert facts.http_status == status and facts.failure_kind == kind and facts.retryable_get == retry
    assert PRIVATE not in repr(facts)


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize(
    "transport_error,kind",
    [(httpx.ReadTimeout, "timeout"), (httpx.ReadError, "network"), (httpx.ConnectError, "network")],
)
async def test_no_response_has_safe_context_and_no_post_retry(
    method: str,
    transport_error: type[httpx.TransportError],
    kind: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path.endswith("/auth"):
            return fixture_response("auth")
        calls += 1
        raise transport_error(PRIVATE, request=request)

    expected = (
        LbxCreateNotSent
        if method == "POST" and transport_error is httpx.ConnectError
        else LbxTimeout
        if kind == "timeout"
        else LbxUnavailable
    )
    with caplog.at_level(logging.DEBUG):
        async with lbx_source(httpx.MockTransport(respond), lbx_max_get_attempts=3) as (client, owner):
            async with owner.operation() as budget:
                await client.prepare_customer_create(budget=budget)
                with pytest.raises(expected) as caught:
                    if method == "POST":
                        await client.create_user(
                            NewCustomer(outer_id="opaque", email="synthetic@example.com"), budget=budget
                        )
                    else:
                        await client.get_user(user_id=345, budget=budget)
    facts = caught.value.response_facts
    assert facts.http_status is facts.lbx_code is None
    assert facts.failure_kind == kind and not facts.provider_error_present
    assert calls == (1 if method == "POST" else 3)
    assert PRIVATE not in caplog.text + str(caught.value) + repr(facts)


async def test_unknown_endpoint_diagnostics_never_retain_url_or_identifiers(caplog: pytest.LogCaptureFixture) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth"):
            return fixture_response("auth")
        return httpx.Response(400, json={"code": 400, "response": {"error": PRIVATE}})

    with caplog.at_level(logging.DEBUG):
        async with lbx_source(httpx.MockTransport(respond)) as (client, owner):
            with pytest.raises(LbxProviderRejected) as caught:
                async with owner.operation() as budget:
                    await client._read(
                        "/users/private@example.test?token=private-token", LbxEnvelope[LbxUser], budget=budget
                    )
    assert caught.value.response_facts.endpoint == "server_api"
    assert "private@example.test" not in caplog.text + repr(caught.value.response_facts)
    assert "private-token" not in caplog.text + repr(caught.value.response_facts)


@pytest.mark.parametrize("transport_error,kind", [(httpx.ReadTimeout, "timeout"), (httpx.ReadError, "network")])
async def test_partial_response_transport_failure_retains_http_status(
    transport_error: type[httpx.TransportError],
    kind: str,
) -> None:
    class InterruptedBody(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b'{"code":500,"response":'
            raise transport_error(PRIVATE)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth"):
            return fixture_response("auth")
        return httpx.Response(500, stream=InterruptedBody(), headers={"Content-Type": "application/json"})

    async with lbx_source(httpx.MockTransport(respond), lbx_max_get_attempts=2) as (client, owner):
        with pytest.raises(LbxTimeout if kind == "timeout" else LbxUnavailable) as caught:
            async with owner.operation() as budget:
                await client.get_user(user_id=345, budget=budget)
    facts = caught.value.response_facts
    assert facts.http_status == 500 and facts.lbx_code is None
    assert facts.failure_kind == kind and not facts.provider_error_present
    assert PRIVATE not in str(caught.value) + repr(facts)
