from __future__ import annotations

import importlib
import json
from functools import partial
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock
from urllib.parse import quote

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from apps.api.tests.support.backend_consumers import backend_consumer, second_consumer
from tools.joint_paid_runtime import runtime


def test_disposable_databases_use_independent_consistent_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime, "free_port", lambda: 54321)
    pair = runtime.JointRuntime()
    pair.run = tmp_path
    monkeypatch.setattr(pair, "compose", MagicMock())
    connect = MagicMock()
    monkeypatch.setattr(runtime.psycopg, "connect", connect)

    passwords = []
    for owner, prefix in (("portal", "POSTGRES"), ("kernel", "ANYTOOLAI_POSTGRES")):
        url = make_url(pair.database(owner))
        values = dict(line.split("=", 1) for line in (tmp_path / f"{owner}.env").read_text().splitlines())
        password = values[f"{prefix}_PASSWORD"]
        assert password
        assert url.password == password == connect.call_args.kwargs["password"]
        assert url.database == values[f"{prefix}_DB"] == connect.call_args.kwargs["dbname"]
        assert (tmp_path / f"{owner}.env").stat().st_mode & 0o077 == 0
        passwords.append(password)

    assert passwords[0] != passwords[1]
    pair.stack.close()


@pytest.fixture
def summary_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    consumers = []
    for configured in (backend_consumer(), second_consumer()):
        consumer = configured.model_dump(mode="json")
        for name in (
            "portal_to_backend_current_secret",
            "backend_to_portal_current_secret",
            "backend_to_portal_previous_secret",
        ):
            secret = getattr(configured, name)
            consumer[name] = secret.get_secret_value() if secret is not None else None
        consumers.append(consumer)
    consumer = consumers[1]
    monkeypatch.setenv("ANY766_RUN_DIR", str(tmp_path))
    monkeypatch.setenv("BACKEND_CONSUMERS", json.dumps(consumers))
    monkeypatch.setenv("ANY766_PORTAL_ORIGIN", "http://127.0.0.1:54321")
    module = importlib.import_module("tools.joint_paid_runtime.summary")
    monkeypatch.setattr(module, "RUN", tmp_path)
    monkeypatch.setattr(module, "CONSUMER", consumer)
    return module


@pytest.mark.parametrize("user_id", ["not-a-uuid", "user?override=1", "user#fragment"])
def test_summary_rejects_invalid_user_ids_before_outbound_io(
    summary_backend: ModuleType, user_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_client(**kwargs: object) -> None:
        raise AssertionError("invalid identity must not reach the Portal client")

    monkeypatch.setattr(summary_backend.httpx, "AsyncClient", unexpected_client)
    with TestClient(summary_backend.app) as client:
        response = client.get(
            "/internal/v1/usage/" + quote(user_id, safe=""),
            headers={"Authorization": "Bearer " + summary_backend.CONSUMER["portal_to_backend_current_secret"]},
        )
    assert response.status_code == 422


def test_summary_preserves_uuid_and_snapshot_path(summary_backend: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = "11111111-1111-4111-8111-111111111111"
    requests: list[httpx.Request] = []

    def snapshot(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"allowances": []})

    monkeypatch.setattr(
        summary_backend.httpx,
        "AsyncClient",
        partial(httpx.AsyncClient, transport=httpx.MockTransport(snapshot)),
    )
    with TestClient(summary_backend.app) as client:
        response = client.get(
            f"/internal/v1/usage/{user_id}",
            headers={"Authorization": "Bearer " + summary_backend.CONSUMER["portal_to_backend_current_secret"]},
        )
    assert response.status_code == 200
    assert response.json()["user_id"] == user_id
    assert len(requests) == 1
    assert requests[0].url.path == f"/internal/v1/access-snapshots/{user_id}"
    assert dict(requests[0].url.params) == {"tenant_id": "anytoolai", "region": "ru"}
