"""The same V1 reverse usage boundary works for each configured owner."""

from copy import deepcopy
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from app.composition.sources import source_resources
from app.integrations.kernel.client import BackendUsageInvalid
from apps.api.tests.test_any766_technical_sources import source_settings

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def response() -> dict[str, object]:
    rows = json.loads(
        (Path(__file__).resolve().parents[3] / "docs/contracts/portal-kernel-paid/fixtures/valid.json").read_text()
    )
    return next(row["payload"] for row in rows if row["name"] == "usage-mixed")


@pytest.mark.parametrize(
    "product,host", [("proposal_ai", "kernel.example.test"), ("synthetic_summary", "summary.example.test")]
)
async def test_backend_usage_uses_owner_directional_key_and_exact_query(product: str, host: str) -> None:
    config = source_settings()
    body = response()
    consumer = next(item for item in config.backend_consumers if product in item.allowed_products)

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == host
        assert (
            request.headers["Authorization"] == "Bearer " + consumer.portal_to_backend_current_secret.get_secret_value()
        )
        assert request.url.path == "/internal/v1/usage/" + body["user_id"]
        assert request.url.params.get_list("allowance_id") == [item["allowance_id"] for item in body["items"]]
        return httpx.Response(200, json=body)

    async with source_resources(config, kernel_transport=httpx.MockTransport(respond)) as sources:
        async with sources.preflight.operation() as budget:
            result = await sources.technical_source(product).client.fetch_usage(
                UUID(body["user_id"]),
                tuple(UUID(item["allowance_id"]) for item in body["items"]),
                budget=budget,
            )
    assert [item.allowance_id for item in result.items] == [item["allowance_id"] for item in body["items"]]
    assert result.model_dump(mode="json") == body


@pytest.mark.parametrize(
    "change", ["owner", "order", "duplicate", "missing", "boolean", "counter", "version", "unknown-status"]
)
async def test_backend_usage_refuses_foreign_incomplete_and_malformed_response(change: str) -> None:
    original = response()
    body = deepcopy(original)
    if change == "owner":
        body["region"] = "foreign"
    elif change == "order":
        body["items"].reverse()
    elif change == "duplicate":
        body["items"] = [body["items"][0]] * len(body["items"])
    elif change == "missing":
        body["items"].pop()
    elif change == "version":
        body["schema_version"] = True
    elif change == "unknown-status":
        body["items"][0]["status"] = "unknown"
    elif change == "boolean":
        body["items"][0]["quantity"] = True
    else:
        body["items"][0]["available"] += 1
    async with source_resources(
        source_settings(), kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    ) as sources:
        async with sources.preflight.operation() as budget:
            with pytest.raises(BackendUsageInvalid):
                await sources.technical_source("proposal_ai").client.fetch_usage(
                    UUID(original["user_id"]),
                    tuple(UUID(item["allowance_id"]) for item in original["items"]),
                    budget=budget,
                )
