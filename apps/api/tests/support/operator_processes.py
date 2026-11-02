"""Shared subprocess CLI fixture with real local HTTP and controlled clocks."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread

import httpx
import pytest

from apps.api.tests.support.commercial_mappings import reviewed_fixture
from apps.api.tests.support.kernel import TOKEN as KERNEL_TOKEN
from apps.api.tests.support.kernel import manifest_fixture
from apps.api.tests.support.lbx import ACCOUNT, PASSWORD, USERNAME
from apps.api.tests.support.lbx_selected_offer import SelectedOfferRecording, simulated_inputs
from apps.api.tests.support.settings import DEFAULT_API_TEST_ENV


ROOT = Path(__file__).resolve().parents[4]
# Test-only clock injection for the recorded historical approval; production
# CLI has no clock flag/environment override or unlocked transport fallback.
CLI = """
from datetime import UTC, datetime
from apps.api.tests.support import v1_mapping_operator as mapping_operator
mapping_operator.utc_now = lambda: datetime(2026, 10, 16, 12, tzinfo=UTC)
from app.domains.catalog import publication
publication.utc_now = mapping_operator.utc_now
from apps.api.tests.support.v1_cli import main
raise SystemExit(main())
"""


@dataclass
class OperatorProcesses:
    directory: Path
    environment: dict[str, str]
    entered: Event
    release: Event
    requests: list[str]
    children: list[subprocess.Popen[str]] = field(default_factory=list)

    def argv(self, command: str) -> list[str]:
        arguments = [sys.executable, "-c", CLI, command, "--proposal", str(self.directory / "proposal.json")]
        if command == "publish":
            arguments += ["--expected-previous-revision", "0"]
        return arguments

    def start(self, command: str) -> subprocess.Popen[str]:
        process = subprocess.Popen(
            self.argv(command),
            cwd=ROOT,
            env=self.environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.children.append(process)
        return process

    def run(self, command: str, **environment: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.argv(command),
            cwd=ROOT,
            env={**self.environment, **environment},
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )


@pytest.fixture
def processes(tmp_path: Path) -> Iterator[OperatorProcesses]:
    with asyncio.Runner() as runner:
        reviewed = runner.run(reviewed_fixture())
    for name, model in (
        ("proposal", reviewed.proposal),
        ("approval", reviewed.approval),
        ("inputs", simulated_inputs()),
    ):
        (tmp_path / f"{name}.json").write_text(model.model_dump_json(), encoding="utf-8")
    entered, release = Event(), Event()
    requests: list[str] = []
    recording = SelectedOfferRecording()

    class Sources(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            if self.path.startswith("/internal/v1/capability-manifest"):
                if not entered.is_set():
                    entered.set()
                    assert release.wait(15), "test did not release first Kernel read"
                body = json.dumps(manifest_fixture()).encode()
            else:
                body = recording.respond(httpx.Request("GET", "http://lbx.test" + self.path)).content
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # The crash regression deliberately kills this reader.

        def log_message(self, format: str, *args: object) -> None:
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Sources) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        environment = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith(("MAPPING_", "KERNEL_", "LBX_", "PREFLIGHT_"))
        }
        environment.update(
            **DEFAULT_API_TEST_ENV,
            PYTHONPATH=".:apps/api",
            MAPPING_OPERATOR_UIDS=json.dumps([os.geteuid()]),
            MAPPING_ACCOUNT_ID=ACCOUNT,
            MAPPING_APPROVAL_FILE=str(tmp_path / "approval.json"),
            MAPPING_SOURCE_INPUTS_FILE=str(tmp_path / "inputs.json"),
            MAPPING_OPERATOR_LOCK_FILE=str(tmp_path / "operator.lock"),
            KERNEL_BASE_URL=origin,
            KERNEL_SERVICE_TOKEN=KERNEL_TOKEN,
            KERNEL_READ_TIMEOUT_SECONDS="30",
            KERNEL_MAX_RETRIES="0",
            LBX_BASE_URL=origin,
            LBX_EXTERNAL_BILLING_ACCOUNT_ID=ACCOUNT,
            LBX_SERVER_USERNAME=USERNAME,
            LBX_SERVER_PASSWORD=PASSWORD,
            LBX_WIDGET_SIGNING_SECRET="simulated-widget-secret",
            LBX_SELLER_ORGANIZATION_ID="21",
            PREFLIGHT_TOTAL_TIMEOUT_SECONDS="30",
        )
        result = OperatorProcesses(tmp_path, environment, entered, release, requests)
        try:
            yield result
        finally:
            release.set()
            for child in result.children:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=5)
            server.shutdown()
            thread.join(timeout=3)
            assert not thread.is_alive()
