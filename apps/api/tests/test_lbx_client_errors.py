from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from app.infrastructure.preflight import PreflightDeadlineExceeded, PreflightSaturated
from app.integrations.lbx.errors import (
    LbxAttemptsExhausted,
    LbxAuthenticationFailed,
    LbxError,
    LbxRateLimited,
    LbxResponseInvalid,
    LbxScopeForbidden,
    LbxTimeout,
    LbxUnavailable,
)
from apps.api.tests.support.lbx import (
    FIXTURES,
    PASSWORD,
    SERVICE,
    TARIFF,
    TOKEN,
    USERNAME,
    admission,
    fixture_response,
    lbx_settings,
    lbx_source,
    respond_with_fixture,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize("persistent", [False, True])
async def test_one_controlled_get_reauth_and_no_reauth_loop(persistent: bool) -> None:
    auth_count = 0
    get_count = 0
    seen_tokens: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal auth_count, get_count
        if request.url.path.endswith("/auth"):
            auth_count += 1
            return httpx.Response(
                200, json={"code": 200, "response": {"token": f"{TOKEN}-{auth_count}", "expires_in": 600}}
            )
        get_count += 1
        seen_tokens.append(request.headers["authorization"])
        return httpx.Response(401) if persistent or get_count == 1 else fixture_response("tariff")

    async with lbx_source(httpx.MockTransport(respond)) as (client, owner):
        async with owner.operation() as budget:
            deadline = budget.deadline
            if persistent:
                with pytest.raises(LbxAuthenticationFailed):
                    await client.get_tariff(tariff_id=TARIFF, budget=budget)
            else:
                assert (await client.get_tariff(tariff_id=TARIFF, budget=budget)).value.tariff_id == TARIFF
            assert budget.deadline == deadline
    assert auth_count == get_count == 2
    assert seen_tokens == [f"Bearer {TOKEN}-1", f"Bearer {TOKEN}-2"]


async def test_stale_unauthorized_response_does_not_discard_another_callers_new_token() -> None:
    both_old_reads = asyncio.Event()
    new_read_completed = asyncio.Event()
    racing = False
    old_read_count = 0
    auth_count = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal auth_count, old_read_count
        if request.url.path.endswith("/auth"):
            auth_count += 1
            return httpx.Response(
                200, json={"code": 200, "response": {"token": f"{TOKEN}-{auth_count}", "expires_in": 600}}
            )
        if racing and request.headers["authorization"] == f"Bearer {TOKEN}-1":
            old_read_count += 1
            number = old_read_count
            if number == 2:
                both_old_reads.set()
            await both_old_reads.wait()
            if number == 2:
                await new_read_completed.wait()
            return httpx.Response(401)
        if racing:
            new_read_completed.set()
        return fixture_response("tariff")

    async with lbx_source(httpx.MockTransport(respond)) as (client, owner):

        async def read() -> None:
            async with owner.operation() as budget:
                await client.get_tariff(tariff_id=TARIFF, budget=budget)

        await read()
        racing = True
        await asyncio.gather(read(), read())
        assert auth_count == old_read_count == 2


@pytest.mark.parametrize("status,expected", [(401, LbxAuthenticationFailed), (403, LbxScopeForbidden)])
async def test_auth_endpoint_denials_are_not_retried(status: int, expected: type[LbxError]) -> None:
    count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        assert request.url.path.endswith("/auth")
        return httpx.Response(status, text=f"private {PASSWORD} {TOKEN}")

    async with lbx_source(httpx.MockTransport(respond)) as (client, owner):
        with pytest.raises(expected) as error:
            async with owner.operation() as budget:
                await client.get_tariff(tariff_id=TARIFF, budget=budget)
        assert count == 1 and owner.active_count == 0
    assert PASSWORD not in str(error.value) and TOKEN not in str(error.value)


@pytest.mark.parametrize(
    "status,expected,exchanges",
    [
        (403, LbxScopeForbidden, 2),
        (404, LbxResponseInvalid, 2),
        (501, LbxUnavailable, 2),
        (429, LbxRateLimited, 5),
        (500, LbxUnavailable, 5),
        (502, LbxUnavailable, 5),
        (503, LbxUnavailable, 5),
        (504, LbxUnavailable, 5),
    ],
)
async def test_http_failure_classification_and_finite_total_attempts(
    status: int, expected: type[LbxError], exchanges: int
) -> None:
    count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if request.url.path.endswith("/auth"):
            return fixture_response("auth")
        return httpx.Response(status, text=f"private {PASSWORD}")

    async with lbx_source(httpx.MockTransport(respond)) as (client, owner):
        with pytest.raises(expected):
            async with owner.operation() as budget:
                await client.get_tariff(tariff_id=TARIFF, budget=budget)
        assert owner.active_count == 0
    assert count == exchanges


async def test_auth_transients_and_read_transients_share_one_attempt_counter() -> None:
    count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(503)
        if request.url.path.endswith("/auth"):
            return fixture_response("auth")
        return httpx.Response(429)

    async with lbx_source(httpx.MockTransport(respond), lbx_max_get_attempts=4) as (client, owner):
        with pytest.raises(LbxRateLimited):
            async with owner.operation() as budget:
                await client.get_tariff(tariff_id=TARIFF, budget=budget)
    assert count == 4  # auth fail, auth success, read fail, read fail; no reset.


async def test_safe_auth_and_selected_get_retries_can_recover_within_one_budget() -> None:
    count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(503)
        if count == 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return respond_with_fixture(request)

    async with lbx_source(httpx.MockTransport(respond), lbx_max_get_attempts=4) as (client, owner):
        async with owner.operation() as budget:
            deadline = budget.deadline
            result = await client.get_tariff(tariff_id=TARIFF, budget=budget)
            assert result.value.tariff_id == TARIFF
            assert budget.deadline == deadline
    assert count == 4


async def test_reauth_cannot_reset_total_get_attempt_limit() -> None:
    count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return fixture_response("auth") if request.url.path.endswith("/auth") else httpx.Response(401)

    async with lbx_source(httpx.MockTransport(respond), lbx_max_get_attempts=3) as (client, owner):
        with pytest.raises(LbxAttemptsExhausted):
            async with owner.operation() as budget:
                await client.get_tariff(tariff_id=TARIFF, budget=budget)
    assert count == 3


@pytest.mark.parametrize("kind,expected", [("timeout", LbxTimeout), ("network", LbxUnavailable)])
async def test_transport_errors_are_redacted_and_retries_are_bounded(
    kind: str, expected: type[LbxError], caplog: pytest.LogCaptureFixture
) -> None:
    count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        error = httpx.ReadTimeout if kind == "timeout" else httpx.ReadError
        raise error(f"{PASSWORD} {USERNAME} {TOKEN}", request=request)

    async with lbx_source(httpx.MockTransport(respond)) as (client, owner):
        with pytest.raises(expected) as caught:
            async with owner.operation() as budget:
                await client.get_tariff(tariff_id=TARIFF, budget=budget)
        assert owner.active_count == 0
    assert count == 5
    assert caught.value.__cause__ is None
    for private in (PASSWORD, USERNAME, TOKEN):
        assert private not in str(caught.value)
        assert private not in repr(caught.value)
        assert private not in caplog.text


async def test_vendor_debug_headers_urls_and_errors_do_not_enter_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    # Use diagnostic canaries, not credentials, to exercise log suppression.
    header_canary = "SIMULATED-vendor-header-canary"
    error_canary = "SIMULATED-vendor-error-canary"

    def respond(request: httpx.Request) -> httpx.Response:
        logging.getLogger("httpcore.http11").debug("response_headers=%r", {"Set-Cookie": header_canary})
        logging.getLogger("httpcore.connection").debug("connection_error=%s", error_canary)
        return respond_with_fixture(request)

    async with lbx_source(httpx.MockTransport(respond)) as (client, owner):
        async with owner.operation() as budget:
            await client.get_tariff(tariff_id=TARIFF, budget=budget)
        logging.getLogger("httpx").info("outside_lbx_http_context")
    assert "outside_lbx_http_context" in caplog.text
    assert PASSWORD not in caplog.text and TOKEN not in caplog.text
    assert header_canary not in caplog.text and error_canary not in caplog.text
    assert "lbx-client.test" not in caplog.text


@pytest.mark.parametrize(
    "body",
    [
        b'{"code":200,"response":[{"price_id":1,"period_id":901,"price":NaN}]}',
        b'{"code":200,"response":[{"price_id":1,"period_id":901,"price":Infinity}]}',
        b'{"code":200,"response":[{"price_id":1,"period_id":901,"price":-Infinity}]}',
        b'{"code":200,"response":[{"price_id":1,"period_id":901,"price":"0.1"}]}',
        b'{"code":200,"response":[{"price_id":1,"period_id":901,"price":true}]}',
        b'{"code":200,"response":[{"price_id":1.0,"period_id":901}]}',
        b'{"code":200,"response":[{"price_id":true,"period_id":901}]}',
        b'{"code":200,"response":[{"price_id":"1","period_id":901}]}',
        b'{"code":200,"response":[{"price_id":-1,"period_id":901}]}',
        b'{"code":200,"response":[{"price_id":1,"period_id":901,"start_date":"2026-02-30"}]}',
        b'{"code":200,"response":[{"price_id":1,"period_id":901,"start_date":"2026-10-01T00:00:00Z"}]}',
        b'{"code":200,"response":[{"price_id":1,"price_id":2,"period_id":901}]}',
        b'{"code":201,"response":[]}',
        b'{"code":200.0,"response":[]}',
        b'{"code":200}',
        b'{"response":[]}',
        b'{"code":200,"response":{}}',
        b'{"code":200,"response":[],"unknown_page":2}',
        b"not JSON",
        b"\xff",
    ],
)
async def test_malformed_envelopes_numbers_dates_and_ids_are_never_repaired(body: bytes) -> None:
    reads = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal reads
        if request.url.path.endswith("/auth"):
            return fixture_response("auth")
        reads += 1
        return httpx.Response(200, content=body, headers={"Content-Type": "application/json"})

    async with lbx_source(httpx.MockTransport(respond)) as (client, owner):
        with pytest.raises(LbxResponseInvalid):
            async with owner.operation() as budget:
                await client.list_service_prices(tariff_id=TARIFF, tariff_service_id=SERVICE, budget=budget)
    assert reads == 1


@pytest.mark.parametrize(
    "body",
    [
        b'{"code":200,"response":{"token":"secret"}}',
        b'{"code":200,"response":{"token":"secret","expires_in":0}}',
        b'{"code":200,"response":{"token":"secret","expires_in":600.0}}',
        b'{"code":200,"response":{"token":7,"expires_in":600}}',
        b'{"code":200,"response":{"token":"bad token","expires_in":600}}',
        b'{"code":200,"response":{"token":"bad\\r\\ntoken","expires_in":600}}',
        b'{"code":200,"response":{"token":"secret","expires_in":' + b"9" * 400 + b"}}",
    ],
)
async def test_malformed_session_never_reaches_selected_get(body: bytes) -> None:
    count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        assert request.url.path.endswith("/auth")
        return httpx.Response(200, content=body, headers={"Content-Type": "application/json"})

    async with lbx_source(httpx.MockTransport(respond)) as (client, owner):
        with pytest.raises(LbxResponseInvalid):
            async with owner.operation() as budget:
                await client.get_tariff(tariff_id=TARIFF, budget=budget)
    assert count == 1


async def test_redirect_does_not_forward_either_basic_or_bearer_credentials() -> None:
    for redirect_auth in (True, False):
        seen: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.url.path.endswith("/auth") and not redirect_auth:
                return fixture_response("auth")
            return httpx.Response(302, headers={"Location": "https://unverified.test/steal"})

        async with lbx_source(httpx.MockTransport(respond)) as (client, owner):
            with pytest.raises(LbxResponseInvalid):
                async with owner.operation() as budget:
                    await client.get_tariff(tariff_id=TARIFF, budget=budget)
        assert len(seen) == (1 if redirect_auth else 2)
        assert all(request.url.host == "lbx-client.test" for request in seen)


async def test_refresh_lock_wait_uses_waiting_callers_deadline_without_cancelling_owner() -> None:
    auth_entered = asyncio.Event()
    allow_auth = asyncio.Event()
    auth_count = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal auth_count
        if request.url.path.endswith("/auth"):
            auth_count += 1
            auth_entered.set()
            await allow_auth.wait()
        return respond_with_fixture(request)

    short_owner = admission(lbx_settings(preflight_total_timeout_seconds=0.08, preflight_cleanup_timeout_seconds=0.01))
    async with lbx_source(httpx.MockTransport(respond)) as (client, owner):

        async def read_owner() -> None:
            async with owner.operation() as budget:
                await client.get_tariff(tariff_id=TARIFF, budget=budget)

        task = asyncio.create_task(read_owner())
        try:
            await asyncio.wait_for(auth_entered.wait(), timeout=1)
            with pytest.raises(PreflightDeadlineExceeded):
                async with short_owner.operation() as budget:
                    await client.get_tariff(tariff_id=TARIFF, budget=budget)
            assert auth_count == 1 and owner.active_count == 1
            assert short_owner.active_count == short_owner.waiting_count == 0
        finally:
            allow_auth.set()
            await task
            await short_owner.aclose()


@pytest.mark.parametrize("hint", ["999999999999999999999999", "http-date", "invalid"])
async def test_retry_after_and_backoff_cannot_extend_absolute_deadline(hint: str) -> None:
    reads = 0
    if hint == "http-date":
        hint = format_datetime(datetime.now(UTC) + timedelta(days=1), usegmt=True)

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal reads
        if request.url.path.endswith("/auth"):
            return fixture_response("auth")
        reads += 1
        return httpx.Response(429, headers={"Retry-After": hint})

    async with lbx_source(
        httpx.MockTransport(respond),
        preflight_total_timeout_seconds=0.1,
        preflight_cleanup_timeout_seconds=0.01,
        lbx_retry_delay_seconds=0.3,
        lbx_max_retry_delay_seconds=0.3,
    ) as (client, owner):
        with pytest.raises(PreflightDeadlineExceeded):
            async with owner.operation() as budget:
                await client.get_tariff(tariff_id=TARIFF, budget=budget)
        assert owner.active_count == 0
    assert reads == 1


async def test_full_body_read_is_size_bounded_and_stream_is_closed() -> None:
    class OversizedStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b" " * 1024
            yield b" "

        async def aclose(self) -> None:
            self.closed = True

    stream = OversizedStream()

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth"):
            return fixture_response("auth")
        return httpx.Response(200, stream=stream, headers={"Content-Type": "application/json"})

    async with lbx_source(httpx.MockTransport(respond), lbx_max_response_bytes=1024) as (client, owner):
        with pytest.raises(LbxResponseInvalid):
            async with owner.operation() as budget:
                await client.get_tariff(tariff_id=TARIFF, budget=budget)
        assert stream.closed and owner.active_count == 0


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Type": "text/html"},
        {"Content-Type": "application/json", "Content-Encoding": "gzip"},
        {"Content-Type": "application/json", "Content-Length": "-1"},
        {"Content-Type": "application/json", "Content-Length": "invalid"},
        {"Content-Type": "application/json", "Content-Length": "1048577"},
        {"Content-Type": "application/json", "Content-Length": "1"},
    ],
)
async def test_unsupported_response_metadata_is_refused(headers: dict[str, str]) -> None:
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield (FIXTURES / "tariff.json").read_bytes()

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth"):
            return fixture_response("auth")
        return httpx.Response(200, stream=Body(), headers=headers)

    async with lbx_source(httpx.MockTransport(respond)) as (client, owner):
        with pytest.raises(LbxResponseInvalid):
            async with owner.operation() as budget:
                await client.get_tariff(tariff_id=TARIFF, budget=budget)


@pytest.mark.parametrize("complete_body", [False, True])
@pytest.mark.parametrize("termination", ["cancel", "deadline"])
async def test_body_and_cleanup_keep_source_accounted_until_actual_close(complete_body: bool, termination: str) -> None:
    entered = asyncio.Event()
    closing = asyncio.Event()
    allow_close = asyncio.Event()
    closed = asyncio.Event()
    close_count = 0

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            entered.set()
            if complete_body:
                yield (FIXTURES / "tariff.json").read_bytes()
            else:
                yield b'{"code":200'
                await asyncio.Event().wait()

        async def aclose(self) -> None:
            nonlocal close_count
            close_count += 1
            closing.set()
            await allow_close.wait()
            closed.set()

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth"):
            return fixture_response("auth")
        return httpx.Response(200, stream=SlowStream(), headers={"Content-Type": "application/json"})

    async with lbx_source(
        httpx.MockTransport(respond),
        preflight_max_active=1,
        preflight_max_waiting=0,
        preflight_total_timeout_seconds=0.15,
        preflight_cleanup_timeout_seconds=0.02,
    ) as (client, owner):

        async def read() -> None:
            async with owner.operation() as budget:
                await client.get_tariff(tariff_id=TARIFF, budget=budget)

        caller = asyncio.create_task(read())
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            if complete_body:
                await asyncio.wait_for(closing.wait(), timeout=1)
            if termination == "cancel":
                caller.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await caller
            else:
                with pytest.raises(PreflightDeadlineExceeded):
                    await caller
            assert closing.is_set() and not closed.is_set()
            assert owner.active_count == 1 and close_count == 1
            with pytest.raises(PreflightSaturated):
                async with owner.operation():
                    pytest.fail("unfinished cleanup must retain its source slot")
        finally:
            allow_close.set()
            await asyncio.wait_for(closed.wait(), timeout=1)
            await asyncio.gather(caller, return_exceptions=True)
            for _ in range(10):
                if owner.active_count == 0:
                    break
                await asyncio.sleep(0)
        assert owner.active_count == 0 and close_count == 1
