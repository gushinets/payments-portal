"""One safe duration per HTTP attempt, including body read/close and failures."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from types import SimpleNamespace

import httpx
import pytest

from app.composition.sources import source_resources
from app.core.observability import JsonFormatter, request_id_context
from app.integrations.lbx import _transport
from app.integrations.lbx.dto import LbxEnvelope, LbxSession
from app.integrations.lbx.errors import LbxError
from apps.api.tests.support.any709_step1 import step1_settings

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize("outcome", ["success", "authorization", "timeout"])
async def test_duration_includes_body_and_close_without_changing_failure(
    outcome: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    clock = [10.0]
    closed = False
    monkeypatch.setattr(_transport, "time", SimpleNamespace(perf_counter=lambda: clock[0]))

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            clock[0] += 0.025
            yield b'{"code":200,"response":{"token":"private-provider-token","expires_in":600}}'

        async def aclose(self) -> None:
            nonlocal closed
            if not closed:
                clock[0] += 0.01
                closed = True

    def transport(request: httpx.Request) -> httpx.Response:
        clock[0] += 0.025
        if outcome == "timeout":
            raise httpx.ReadTimeout("private-provider-transport", request=request)
        return httpx.Response(
            401 if outcome == "authorization" else 200, stream=Body(), headers={"Content-Type": "application/json"}
        )

    config = step1_settings()
    context = request_id_context.set("safe-duration-request")
    try:
        with caplog.at_level(logging.INFO, logger="payment_portal.lbx"):
            async with (
                source_resources(config) as sources,
                httpx.AsyncClient(base_url=config.lbx_base_url, transport=httpx.MockTransport(transport)) as pool,
                sources.billing.operation() as budget,
            ):

                async def attempt() -> LbxSession:
                    return await _transport.request_once(
                        pool, config, "/auth", LbxEnvelope[LbxSession], _transport._Attempts(1), budget
                    )

                if outcome == "success":
                    result = await budget.run(attempt)
                    assert result.expires_in == 600
                else:
                    with pytest.raises((LbxError, _transport._Retryable)) as caught:
                        await budget.run(attempt)
                    failure = caught.value.failure if isinstance(caught.value, _transport._Retryable) else caught.value
                    assert failure.code == ("lbx_timeout" if outcome == "timeout" else "lbx_authentication_failed")
    finally:
        request_id_context.reset(context)

    records = [record for record in caplog.records if record.getMessage() == "lbx_http"]
    assert len(records) == 1
    fields = records[0].structured
    assert fields["duration_ms"] == pytest.approx(25 if outcome == "timeout" else 60)
    assert fields["request_id"] == "safe-duration-request"
    assert fields["endpoint"] == "/auth"
    assert (
        fields["failure_kind"]
        == {"success": "success", "authorization": "authorization", "timeout": "timeout"}[outcome]
    )
    assert closed is (outcome != "timeout")
    assert "private-provider" not in json.dumps(fields) + JsonFormatter().format(records[0])
