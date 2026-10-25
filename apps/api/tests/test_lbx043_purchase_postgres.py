"""Portal/PG + separate Kernel HTTP mock + in-process 043 protocol fixtures.

No stand requests. Preserve the same holds, send journal and UNKNOWN recovery
across application reconstruction; credentials are inspected only in memory.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from pathlib import Path
from threading import Thread
import time
from uuid import UUID

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import app.composition.purchases as composition
from app.core.database import get_db
from app.domains.catalog.publication import publish_mapping
from app.domains.catalog.mapping_evidence import MappingDocument
from app.domains.purchases import router as purchase_http
from app.domains.purchases.contracts import SellerEvidence
from app.legal_seed import seed_legal_documents
from app.main import create_app
from app.models import ExternalBillingCustomer, ExternalCreateOperation, ExternalSubscription, PurchaseIntent, User
from apps.api.tests.support.lbx043 import (
    NOW,
    StandRecording,
    configured_profile,
    mapping_for,
    stand_offer,
    stand_settings,
    stand_source,
)
from apps.api.tests.support.purchases import PurchaseHarness, _seed_user
from apps.api.tests.support.kernel import TOKEN
from tools.kernel_manifest_mock.server import ManifestMockServer, MockConfig


pytestmark = [pytest.mark.postgres, pytest.mark.usefixtures("mapping_clock")]


@pytest.fixture
def stand_harness(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[PurchaseHarness, StandRecording]]:
    factory = postgres_session_factory
    recording = StandRecording()
    profile = configured_profile()

    async def evaluation() -> MappingDocument:
        async with stand_source(recording) as (client, owner):
            return mapping_for(await stand_offer(client, owner))

    stored = publish_mapping(
        factory,
        evaluation=asyncio.run(evaluation()),
        expected_previous_revision=0,
        deadline=time.monotonic() + 10,
        evidence_valid_until=NOW + timedelta(days=1),
        lock_timeout_seconds=0.2,
        allow_simulated=True,
    ).stored
    with factory() as db:
        seed_legal_documents(db)
    with factory.begin() as db:
        user_id = _seed_user(db, "stand-test-session")
        _seed_user(db, "other-stand-test-session")
        db.get(User, user_id).user_name = "Анна"
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "LOCAL-043-purchase-profile-v1",
                "selection": profile.selection.model_dump(mode="json"),
                "inputs": profile.inputs.model_dump(mode="json"),
                "recurring_required": False,
                "seller": SellerEvidence(
                    evidence_mode="CONFIGURED_SOURCE",
                    organization_id=21,
                    reference=profile.seller_evidence.reference,
                    revision=profile.seller_evidence.revision,
                ).model_dump(mode="json"),
            }
        )
    )
    (tmp_path / "preparation.json").write_text(
        json.dumps(
            profile.model_dump(mode="json", exclude={"server_username"}) | {"server_username": "COMPOSITION-ONLY"}
        )
    )
    original_client = composition.LbxServerClient
    monkeypatch.setattr(
        composition,
        "LbxServerClient",
        lambda configuration, **kwargs: original_client(
            configuration,
            transport=httpx.MockTransport(recording.respond),
            stand_permission=kwargs.get("stand_permission"),
        ),
    )

    def observe(path: str, body: dict) -> None:
        if path == "/users":
            assert body["user_name"] == "Анна" and "user_surname" not in body
            assert "login" in body and "password" in body
            recording.rows["user"]["outer_id"] = body["outer_id"]
            recording.rows["users"] = [recording.rows["user"]]
        elif path == "/agreements":
            assert "debt_threshold" not in body and body["organization_id"] == 21
            recording.rows["agreement"].update(body)
            recording.rows["agreements"].append(recording.rows["agreement"])
        else:
            assert "subscription_start_date" not in body
            recording.rows["subscription"]["outer_id"] = body["outer_id"]
            recording.rows["subscriptions"] = [recording.rows["subscription"]]

    recording.inspect_post = observe
    server = ManifestMockServer(("127.0.0.1", 0), MockConfig(app_env="test", token=TOKEN))
    worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    with server:
        worker.start()
        try:
            configuration = stand_settings(
                purchase_stand_profile_file=path,
                lbx043_test_user_ids=(user_id,),
                kernel_base_url=f"http://127.0.0.1:{server.server_port}",
                kernel_service_token=TOKEN,
                lbx_widget_signing_secret="test-only-widget-secret-at-least-32-bytes",
            )
            import app.main as main

            monkeypatch.setattr(main, "settings", configuration)
            monkeypatch.setenv("SKIP_LEGAL_SEED", "true")
            app = create_app()

            def database() -> Iterator[Session]:
                with factory() as db:
                    yield db

            app.dependency_overrides[get_db] = database
            with TestClient(app, raise_server_exceptions=False) as client:
                harness = PurchaseHarness(
                    client, factory, server, path, stored, user_id, "stand-test-session", "other-stand-test-session"
                )
                app.dependency_overrides[purchase_http.application] = lambda: composition.purchase_application(
                    configuration,
                    factory,
                    app.state.sources,
                    clock=lambda: harness.now,
                )
                yield harness, recording
        finally:
            server.shutdown()
            worker.join(timeout=3)


def continue_intent(harness: PurchaseHarness, intent: str) -> httpx.Response:
    return harness.client.post(f"/api/purchases/{intent}/continue", headers=harness.headers)


def bootstrap(harness: PurchaseHarness, intent: str, token: str | None = None) -> httpx.Response:
    return harness.client.post(
        "/api/billing/widget-bootstrap",
        headers={"Authorization": "Bearer " + (token or harness.token)},
        json={"product_id": "proposal_ai", "purchase_intent_id": intent},
    )


def test_local_stand_scope_persists_names_separately_and_widget_reopens_without_post(stand_harness: tuple) -> None:
    harness, traffic = stand_harness
    result = harness.post(harness.payload())
    assert result.status_code == 202, result.text
    intent = result.json()["purchase_intent_id"]
    result = continue_intent(harness, intent)
    assert result.status_code == 202 and result.json()["state"] == "linked", result.text
    with harness.factory() as db:
        purchase = db.get(PurchaseIntent, UUID(intent))
        assert "Анна" not in json.dumps(purchase.accepted_snapshot, ensure_ascii=False)
        operations = list(db.scalars(select(ExternalCreateOperation)))
        assert len(operations) == 3
        for operation in operations:
            serialized = json.dumps(operation.recovery_hint_document, ensure_ascii=False)
            assert "Анна" not in serialized
            pending: list[object] = [operation.recovery_hint_document]
            while pending:
                value = pending.pop()
                if isinstance(value, dict):
                    # Policy lists name allowed fields; persisted objects must
                    # never contain their transient credential or name values.
                    assert not {
                        "login",
                        "password",
                        "server_username",
                        "user_surname",
                        "user_name",
                        "user_patronymic",
                    }.intersection(value)
                    pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)
        subscription = db.scalars(select(ExternalSubscription)).one()
        assert subscription.external_agreement_id == "1601"
        assert subscription.external_subscription_id == "1701"
        assert subscription.financial_access_status == "blocked"
        assert db.scalars(select(ExternalBillingCustomer)).one().provider_customer_id == "1501"
        observation = next(op for op in operations if op.operation_kind == "subscription").recovery_hint_document[
            "provider_observation"
        ]
        assert observation["last_tariffication_period_start"] is None
        assert observation["subscription_start_date"].startswith("3000-01-01")
    posts = Counter(path for method, path in traffic.requests if method == "POST")
    assert posts == {"/users": 1, "/agreements": 1, "/subscriptions": 1}
    first, second = bootstrap(harness, intent), bootstrap(harness, intent)
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert first.json()["mode"] == "LOCAL_043" and first.json()["sdk"] == "lbxwidget"
    assert first.headers["cache-control"] == "no-store"
    assert first.headers["referrer-policy"] == "no-referrer"
    assert first.json()["disablePayments"] is True
    assert bootstrap(harness, intent, harness.other_token).status_code in {403, 404, 409}
    assert Counter(path for method, path in traffic.requests if method == "POST") == posts
    traffic.rows["subscription"]["services"][0]["price"] = 101
    assert bootstrap(harness, intent).status_code != 200


def test_timeout_restart_discovery_and_concurrent_continue_never_repeat_post(stand_harness: tuple) -> None:
    harness, traffic = stand_harness
    intent = harness.post(harness.payload()).json()["purchase_intent_id"]
    traffic.post_fault = True
    result = continue_intent(harness, intent)
    assert result.json()["state"] == "awaiting_external_result", result.text
    assert bootstrap(harness, intent).status_code != 200
    traffic.post_fault = False
    # Every dependency invocation constructs a fresh application/client from DB.
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: continue_intent(harness, intent), range(2)))
    assert all(result.status_code == 202 for result in results)
    final = continue_intent(harness, intent)
    assert final.json()["state"] == "linked", final.text
    assert Counter(path for method, path in traffic.requests if method == "POST") == {
        "/users": 1,
        "/agreements": 1,
        "/subscriptions": 1,
    }
    assert harness.post(harness.payload(), key="new-after-restart").status_code == 409
    assert bootstrap(harness, intent).status_code == 200


def test_stale_mapping_and_non_allowlisted_user_cannot_get_live_authority(stand_harness: tuple) -> None:
    harness, traffic = stand_harness
    payload = harness.payload()
    forbidden = harness.client.post(
        "/api/purchases",
        headers={"Authorization": "Bearer " + harness.other_token, "Idempotency-Key": "foreign"},
        json=payload,
    )
    assert forbidden.status_code == 403
    assert not any(method == "POST" for method, _ in traffic.requests)
    intent = harness.post(payload).json()["purchase_intent_id"]
    assert continue_intent(harness, intent).json()["state"] == "linked"
    assert bootstrap(harness, intent).status_code == 200

    async def replacement() -> MappingDocument:
        async with stand_source(traffic) as (client, owner):
            return mapping_for(await stand_offer(client, owner), allowance=26, revision="fixture-v2")

    publish_mapping(
        harness.factory,
        evaluation=asyncio.run(replacement()),
        expected_previous_revision=1,
        deadline=time.monotonic() + 10,
        evidence_valid_until=NOW + timedelta(days=1),
        lock_timeout_seconds=0.2,
        allow_simulated=True,
    )
    assert bootstrap(harness, intent).status_code == 409
    assert Counter(path for method, path in traffic.requests if method == "POST") == {
        "/users": 1,
        "/agreements": 1,
        "/subscriptions": 1,
    }
