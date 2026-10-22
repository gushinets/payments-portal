"""Step 7 smoke: actual HTTP Kernel, recorded LBX, real publisher/DB/API.

The independent HTTP test target below serves literal contract bytes; it is a
test fixture only, never another development mock or production producer.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.cli import commercial_mappings as cli
from app.composition.sources import source_resources
from app.core import database
from app.core.database import get_db
from app.core.errors import AppError
from app.core.settings import AppEnv, Settings
from app.domains.catalog import router as catalog_http
from app.domains.catalog.mapping_evidence import MappingDocument, MappingRefused
from app.domains.catalog.publication import publish_mapping
from app.infrastructure.preflight import PreflightSaturated
from app.main import create_app
from apps.api.tests.support import kernel_walkthrough as walkthrough
from apps.api.tests.support.commercial_mappings import SIMULATED_OFFER_ID, SIMULATED_UID, operator_settings
from apps.api.tests.support.lbx import PASSWORD, USERNAME
from apps.api.tests.support.lbx import TOKEN as LBX_TOKEN
from apps.api.tests.support.lbx_selected_offer import SelectedOfferRecording
from tools.kernel_manifest_mock.server import ManifestMockServer, MockConfig, Scenario


pytestmark = pytest.mark.usefixtures("mapping_clock")


ROOT = Path(__file__).resolve().parents[3]
TOKEN = "explicit-step7-test-token"


@contextmanager
def serve(server: ThreadingHTTPServer) -> Iterator[str]:
    with server:
        worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            worker.join(timeout=3)
            assert not worker.is_alive()


@pytest.fixture
def operator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    if os.name != "posix":
        pytest.skip("Operator flock requires Unix")
    monkeypatch.setattr(os, "geteuid", lambda: SIMULATED_UID, raising=False)
    walkthrough.prepare_inputs(tmp_path)
    return operator_settings(
        app_env=AppEnv.DEVELOPMENT,
        postgres_db="payments_12345678",
        database_url="postgresql+psycopg://unused@localhost/payments_12345678",
        kernel_service_token=TOKEN,
        mapping_approval_file=tmp_path / "approval.json",
        mapping_source_inputs_file=tmp_path / "inputs.json",
        mapping_operator_lock_file=tmp_path / "operator.lock",
        preflight_total_timeout_seconds=3,
        preflight_cleanup_timeout_seconds=0.1,
        kernel_read_timeout_seconds=0.1,
        kernel_max_retries=0,
    )


def test_fresh_http_publication_faults_outage_restart_and_recovery(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    operator: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(database, "SessionLocal", postgres_session_factory)
    app = create_app()

    def db() -> Iterator[Session]:
        with postgres_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = db
    proposal = tmp_path / "proposal.json"
    publish = cli.parser().parse_args(["publish", "--proposal", str(proposal), "--expected-previous-revision", "0"])
    query = cli.parser().parse_args(["query", "--offer-id", SIMULATED_OFFER_ID])
    server = ManifestMockServer(("127.0.0.1", 0), MockConfig(app_env="test", token=TOKEN))
    recording = SelectedOfferRecording()
    recording.replace(
        "tariff",
        '"additional_fields":[]',
        '"additional_fields":[{"name":"contact","element_value":"walkthrough-person@example.invalid"}]',
    )
    monkeypatch.setattr(walkthrough, "SelectedOfferRecording", lambda: recording)
    with serve(server) as origin:
        configuration = Settings(
            **{
                **operator.model_dump(),
                "kernel_base_url": origin,
                "database_url": "postgresql+psycopg://SIMULATED-user:SIMULATED-url-canary@localhost/payments_12345678",
                "postgres_password": "SIMULATED-db-canary",
                "smtp_password": "SIMULATED-mail-canary",
                "lbx_server_password": "SIMULATED-configured-lbx-canary",
            }
        )

        def configured_settings(**values: object) -> Settings:
            # The helper also constructs source Settings with explicit overrides.
            return Settings(**values) if values else configuration

        monkeypatch.setattr(walkthrough, "Settings", configured_settings)

        def run_operator(argv: list[str]) -> dict[str, Any]:
            assert walkthrough.main(argv) == 0
            captured = capsys.readouterr()
            assert captured.err == ""
            assert all(
                marker not in captured.out
                for marker in (
                    TOKEN,
                    PASSWORD,
                    LBX_TOKEN,
                    USERNAME,
                    "SIMULATED-url-canary",
                    "SIMULATED-db-canary",
                    "SIMULATED-mail-canary",
                    "SIMULATED-configured-lbx-canary",
                    "walkthrough-person@example.invalid",
                )
            )
            return json.loads(captured.out)

        monkeypatch.setattr(catalog_http, "settings", configuration)
        preview = run_operator(["dry-run", "--proposal", str(proposal)])
        first = run_operator(["publish", "--proposal", str(proposal), "--expected-previous-revision", "0"])
        assert not preview["persisted"] and first["persisted"] and first["inserted"]
        assert preview["evaluation"]["evaluated_at"] != first["evaluation"]["evaluated_at"]
        assert first["stored_document"]["evidence_mode"] == "SIMULATED"
        saved = run_operator(["query", "--offer-id", SIMULATED_OFFER_ID])
        assert saved["document"] == first["stored_document"]
        document = MappingDocument.model_validate_json(json.dumps(saved["document"]))
        assert document.reason == preview["evaluation"]["reason"]
        assert saved["billing_offer_id"] == first["billing_offer_id"] == SIMULATED_OFFER_ID
        assert saved["operator_audit"]["execution_principal"] == f"os-euid:{SIMULATED_UID}"
        with TestClient(app, raise_server_exceptions=False) as client:
            # Lifespan's source owner uses no startup HTTP; catalog uses DB only.
            assert client.get("/api/catalog/products/proposal_ai").json()["availability"] == "SIMULATED_PREVIEW"
            for scenario, code in (
                (Scenario.DISABLED_PRODUCT, "selected_product_disabled"),
                (Scenario.MISSING_PRODUCT, "selected_product_missing"),
                (Scenario.DISABLED_METRIC, "selected_metric_disabled"),
                (Scenario.MISSING_METRIC, "selected_metric_missing"),
                (Scenario.MALFORMED_JSON, "kernel_manifest_invalid"),
                (Scenario.WRONG_SCHEMA, "kernel_manifest_invalid"),
                (Scenario.UNAUTHORIZED, "kernel_authentication_failed"),
                (Scenario.TIMEOUT, "kernel_timeout"),
                (Scenario.UNAVAILABLE, "kernel_unavailable"),
            ):
                server.config = MockConfig(app_env="test", token=TOKEN, scenario=scenario, delay_seconds=0.2)
                with pytest.raises(AppError, match=code):
                    walkthrough.execute(publish, configuration)
                assert json.loads(walkthrough.execute(query, configuration))["document"] == saved["document"]
                assert client.get("/api/catalog/products/proposal_ai").status_code == 200
            server.config = MockConfig(app_env="test", token=TOKEN, scenario=Scenario.TIMEOUT, delay_seconds=0.2)

            async def slow_saturation() -> None:
                bounded = Settings(
                    **{**configuration.model_dump(), "preflight_max_active": 1, "preflight_max_waiting": 0}
                )
                async with source_resources(bounded) as sources:
                    async with sources.preflight.operation() as budget:
                        pending = asyncio.create_task(sources.require_kernel().fetch_manifest(budget=budget))
                        try:
                            await asyncio.sleep(0)
                            assert not pending.done()
                            with pytest.raises(PreflightSaturated):
                                async with sources.preflight.operation():
                                    raise AssertionError("full source owner admitted more work")
                            queried = json.loads(walkthrough.execute(query, configuration))
                            assert queried["document"] == saved["document"]
                            assert client.get("/api/catalog/products/proposal_ai").status_code == 200
                        finally:
                            with pytest.raises(AppError):
                                await pending

            with asyncio.Runner() as runner:
                runner.run(slow_saturation())
            server.config = MockConfig(app_env="test", token=TOKEN)
            recovered = json.loads(walkthrough.execute(publish, configuration))
            assert recovered["mapping_revision_id"] == first["mapping_revision_id"]
            assert not recovered["inserted"]
            assert recovered["evaluation"]["evaluated_at"] != first["evaluation"]["evaluated_at"]
    # Physically closed listener; fresh reads fail, saved evidence stays readable.
    with pytest.raises(AppError, match="kernel_unavailable"):
        walkthrough.execute(publish, configuration)
    assert json.loads(walkthrough.execute(query, configuration))["document"] == saved["document"]
    monkeypatch.setattr("app.main.settings", configuration)
    monkeypatch.setenv("SKIP_LEGAL_SEED", "true")
    with TestClient(app) as restarted:
        assert restarted.get("/api/health/live").status_code == 200
        assert restarted.get("/api/health/ready").status_code == 200
        assert restarted.get("/api/catalog/products/proposal_ai").status_code == 200


def test_independent_http_target_switch_changes_only_url_and_credentials(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    operator: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_token = "different-independent-test-credential"
    body = (ROOT / "docs/contracts/kernel-capability-manifest/v1/fixtures/valid-manifest.json").read_bytes()

    class LiteralTarget(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            assert self.path == "/internal/v1/capability-manifest?tenant_id=anytoolai&region=ru"
            assert self.headers.get("Authorization") == f"Bearer {target_token}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    monkeypatch.setattr(database, "SessionLocal", postgres_session_factory)
    args = cli.parser().parse_args(
        ["publish", "--proposal", str(tmp_path / "proposal.json"), "--expected-previous-revision", "0"]
    )
    with serve(ManifestMockServer(("127.0.0.1", 0), MockConfig(app_env="test", token=TOKEN))) as origin:
        original = Settings(**{**operator.model_dump(), "kernel_base_url": origin})
        first = json.loads(walkthrough.execute(args, original))
    with serve(ThreadingHTTPServer(("127.0.0.1", 0), LiteralTarget)) as target:
        switched = Settings(
            **{**original.model_dump(), "kernel_base_url": target, "kernel_service_token": target_token}
        )
        second = json.loads(walkthrough.execute(args, switched))
    assert second["mapping_revision_id"] == first["mapping_revision_id"]
    assert second["stored_document"]["evidence_mode"] == second["evaluation"]["evidence_mode"] == "SIMULATED"
    # The existing genuine publication gate also rejects already stored simulation.
    with pytest.raises(MappingRefused, match="mapping_simulation_forbidden"):
        publish_mapping(
            postgres_session_factory,
            evaluation=MappingDocument.model_validate_json(json.dumps(second["evaluation"])),
            expected_previous_revision=0,
            deadline=0,
            evidence_valid_until=datetime(2026, 10, 16, 21, tzinfo=UTC),
            lock_timeout_seconds=0.2,
            allow_simulated=False,
        )
    app = create_app()

    def db() -> Iterator[Session]:
        with postgres_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = db
    production = operator_settings(
        app_env=AppEnv.PRODUCTION,
        app_public_base_url="https://portal.example.com",
        cors_allow_origins=("https://portal.example.com",),
        kernel_base_url="",
        kernel_service_token="",
        lbx_base_url="",
        lbx_external_billing_account_id="",
        lbx_server_username="",
        lbx_server_password="",
    )
    monkeypatch.setattr(catalog_http, "settings", production)
    with TestClient(app) as client:
        assert client.get("/api/catalog/products").json() == {"products": []}
        assert client.get("/api/catalog/products/proposal_ai").status_code == 404
