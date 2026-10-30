"""Synthetic HTTP/authentication/body/privacy and code-to-runbook contracts."""

from collections.abc import AsyncIterator
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
import yaml

from app.core.settings import Settings
from app.domains.billing.webhook_contracts import HintReceipt
from app.http import billing_webhook as entrypoint
from app.http.dependencies import get_session_factory
from app.integrations.lbx import webhook
from app.main import create_app
from apps.api.tests.factories.billing_webhook import AUTH_HEADER, AUTH_VALUE, PATH, hint_payload, webhook_settings
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.lbx import lbx_settings

pytestmark = pytest.mark.anyio
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setattr(entrypoint, "settings", webhook_settings())
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as connection:
        yield connection


@pytest.mark.parametrize("enabled,credentials", [(False, AUTH_VALUE), (True, ""), (True, "wrong")])
async def test_billing_webhook_authenticates_before_body_or_database(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, enabled: bool, credentials: str
) -> None:
    monkeypatch.setattr(entrypoint, "settings", webhook_settings(lbx_webhook_enabled=enabled))
    consumed = False

    async def forbidden_body() -> AsyncIterator[bytes]:
        nonlocal consumed
        consumed = True
        raise AssertionError("body read before authentication")
        yield b""

    response = await client.post(
        PATH + "?token=" + AUTH_VALUE,
        content=forbidden_body(),
        headers={AUTH_HEADER: credentials, "Content-Type": "application/json"},
    )
    assert response.status_code == (401 if enabled else 404)
    assert consumed is False
    assert AUTH_VALUE not in response.text


async def test_billing_webhook_rejects_duplicate_headers_and_exact_value_mismatch(client: httpx.AsyncClient) -> None:
    for headers in (
        [(AUTH_HEADER, AUTH_VALUE), (AUTH_HEADER.lower(), AUTH_VALUE)],
        [(AUTH_HEADER, AUTH_VALUE + " ")],
        [(AUTH_HEADER, AUTH_VALUE.upper())],
        [("Authorization", AUTH_VALUE)],
    ):
        response = await client.post(PATH, json=hint_payload(), headers=headers)
        assert response.status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        b"{",
        b"\xff",
        b"null",
        b"[]",
        b'{"event":"change_subscription","parameters":[]}',
        json.dumps(hint_payload(subscription_id=True)).encode(),
        json.dumps(hint_payload(subscription_id="567")).encode(),
        json.dumps(hint_payload(subscription_id=0)).encode(),
        json.dumps(hint_payload(agreement_id=10**20)).encode(),
        json.dumps(hint_payload(user_id=None)).encode(),
    ],
)
async def test_billing_webhook_rejects_invalid_input_without_echo(client: httpx.AsyncClient, payload: bytes) -> None:
    response = await client.post(
        PATH, content=payload, headers={AUTH_HEADER: AUTH_VALUE, "Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "lbx_webhook_invalid"}


async def test_billing_webhook_unsupported_event_content_type_and_size_limits(client: httpx.AsyncClient) -> None:
    response = await client.post(PATH, json=hint_payload(event="make_payment"), headers={AUTH_HEADER: AUTH_VALUE})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "lbx_webhook_event_unsupported"
    assert (await client.post(PATH, content=b"{}", headers={AUTH_HEADER: AUTH_VALUE})).status_code == 415
    response = await client.post(
        PATH,
        content=b"x" * (webhook.MAX_BODY_BYTES + 1),
        headers={AUTH_HEADER: AUTH_VALUE, "Content-Type": "application/json"},
    )
    assert response.status_code == 413

    async def chunks() -> AsyncIterator[bytes]:
        yield b"x" * webhook.MAX_BODY_BYTES
        yield b"x"

    response = await client.post(
        PATH, content=chunks(), headers={AUTH_HEADER: AUTH_VALUE, "Content-Type": "application/json"}
    )
    assert response.status_code == 413  # No Content-Length: enforce while streaming too.


@pytest.mark.parametrize("length", ["no", "-1", "9" * 100, "10,10"])
async def test_billing_webhook_invalid_declared_length(client: httpx.AsyncClient, length: str) -> None:
    response = await client.post(
        PATH,
        content=b"{}",
        headers={AUTH_HEADER: AUTH_VALUE, "Content-Type": "application/json", "Content-Length": length},
    )
    assert response.status_code in {400, 413}


async def test_billing_webhook_named_response_and_resource_owning_delegation(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    event_loop_thread = threading.get_ident()
    identity = uuid4()
    marker = object()
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: marker

    def receive(factory: object, config: Settings, hint: object) -> HintReceipt:
        assert threading.get_ident() != event_loop_thread
        assert factory is marker and config.lbx_webhook_enabled
        assert hint.event == "change_subscription" and hint.subscription_id == "567"
        assert not hasattr(hint, "email")
        return HintReceipt(identity, True)

    monkeypatch.setattr(entrypoint, "receive_hint", receive)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as connection:
        response = await connection.post(
            PATH,
            json=hint_payload(email="pii-canary@test.invalid", password=AUTH_VALUE),
            headers={AUTH_HEADER: AUTH_VALUE},
        )
    assert response.status_code == 200 and response.json() == {"delivery_id": str(identity), "outcome": "queued"}
    assert response.headers["Cache-Control"] == "no-store"
    assert app.openapi()["paths"][PATH]["post"]["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/BillingWebhookResponse"
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"lbx_webhook_auth_header": ""},
        {"lbx_webhook_auth_header": "Invalid Header"},
        {"lbx_webhook_auth_header": "Content-Length"},
        {"lbx_webhook_auth_header": "X-Request-ID"},
        {"lbx_webhook_auth_header": "traceparent"},
        {"lbx_webhook_auth_header": "User-Agent"},
        {"lbx_webhook_auth_value": ""},
        {"lbx_webhook_auth_value": "secret\r\ninjection"},
        {"lbx_webhook_auth_value": " secret"},
        {"lbx_base_url": ""},
    ],
)
def test_billing_webhook_settings_fail_closed_without_secret_in_errors(overrides: dict) -> None:
    with pytest.raises(ValidationError) as caught:
        webhook_settings(**overrides)
    assert AUTH_VALUE not in str(caught.value)


def test_billing_webhook_default_disabled_and_secret_repr() -> None:
    assert step1_settings().lbx_webhook_enabled is False
    assert AUTH_VALUE not in repr(webhook_settings())
    assert lbx_settings(lbx_base_url="", lbx_server_username="", lbx_server_password="").lbx_webhook_enabled is False


@pytest.mark.parametrize("event", list(webhook.SubscriptionEvent))
def test_billing_webhook_decoder_retains_only_safe_hint(event: webhook.SubscriptionEvent) -> None:
    hint = webhook.decode_hint(json.dumps(hint_payload(event=event, email="pii-canary", user_id=345)).encode())
    assert hint.event == event.value and hint.customer_id == "345"
    assert len(hint.payload_hash) == 64 and "pii-canary" not in repr(hint)


def test_billing_webhook_deployment_and_documentation_contract() -> None:
    defaults = {"LBX_WEBHOOK_ENABLED": "false", "LBX_WEBHOOK_AUTH_HEADER": "", "LBX_WEBHOOK_AUTH_VALUE": ""}
    for key, value in defaults.items():
        default = Settings.model_fields[key.lower()].default
        assert (
            str(default).lower()
            if isinstance(default, bool)
            else default.get_secret_value()
            if key.endswith("VALUE")
            else default
        ) == value
    for path in ("docker-compose.yml", "docker-compose.prod.yml", "docker-compose.agent.yml"):
        config = yaml.safe_load((ROOT / path).read_text())["services"]["api"]["environment"]
        for key, value in defaults.items():
            assert config[key] == f"${{{key}:-{value}}}"
    for path in (".env.example", ".env.production.example"):
        for key, value in defaults.items():
            assert f"{key}={value}\n" in (ROOT / path).read_text()
    text = (ROOT / "docs/engineering/ANY-715-billing-operations.md").read_text()
    assert f"POST {PATH}" in text
    for event in webhook.SubscriptionEvent:
        assert f"`{event.value}`" in text
    for key, value in defaults.items():
        assert f"`{key}={value}`" in text
    assert str(webhook.MAX_BODY_BYTES) in text
    for required in (
        "DISABLED/POLLING-ONLY",
        "Test URL",
        "Production URL",
        "Repeat request",
        "Rollback",
        "NOT_RUN",
        "enqueue_generation",
        "pending",
        "processed",
        "ignored",
    ):
        assert required in text


@pytest.mark.parametrize("from_environment", [False, True])
def test_billing_webhook_harness_forwards_private_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    from_environment: bool,
) -> None:
    from scripts import repo

    harness = tmp_path / ".harness"
    monkeypatch.setattr(repo, "HARNESS_DIR", harness)
    monkeypatch.setattr(repo, "RUNTIME_ENV", harness / "runtime.env")
    monkeypatch.setattr(repo, "RUNTIME_JSON", harness / "runtime.json")
    monkeypatch.setattr(repo, "kernel_mock_enabled", lambda: False)
    expected = {
        "LBX_WEBHOOK_ENABLED": "true",
        "LBX_WEBHOOK_AUTH_HEADER": "X-Lbx-Test-Auth",
        "LBX_WEBHOOK_AUTH_VALUE": "synthetic-$secret #with'quote",
    }
    local = {name: "overridden" for name in expected} if from_environment else expected
    monkeypatch.setattr(repo, "read_dotenv", lambda: local)
    for name, value in expected.items():
        if from_environment:
            monkeypatch.setenv(name, value)
        else:
            monkeypatch.delenv(name, raising=False)
    repo.write_runtime(repo.runtime_config(root=tmp_path))
    written = repo.read_runtime_env()
    assert {name: written[name] for name in expected} == expected
    public = json.loads(repo.RUNTIME_JSON.read_text())
    assert not set(expected).intersection(public)
    assert repo.RUNTIME_ENV.stat().st_mode & 0o077 == 0
    output = capsys.readouterr()
    assert expected["LBX_WEBHOOK_AUTH_VALUE"] not in output.out + output.err + json.dumps(public)
