from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx2
import pytest

from apps.api.tests.support.settings import api_test_environment


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _stop_process(process: subprocess.Popen[str]) -> str:
    if process.poll() is None:
        process.terminate()

    try:
        output, _ = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate(timeout=5)

    return output or ""


def test_uvicorn_serves_application_with_production_proxy_flags(tmp_path: Path) -> None:
    _assert_uvicorn_serves_application(tmp_path)


def test_uvicorn_retries_connection_timeout_during_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_get = httpx2.get
    attempts = 0

    def get_after_startup_timeout(url: str, *, headers: dict[str, str], timeout: float) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx2.ConnectTimeout("synthetic startup timeout")
        return original_get(url, headers=headers, timeout=timeout)

    monkeypatch.setattr(httpx2, "get", get_after_startup_timeout)
    _assert_uvicorn_serves_application(tmp_path)
    assert attempts >= 2


def _assert_uvicorn_serves_application(tmp_path: Path) -> None:
    port = _available_port()
    environment = api_test_environment(
        **{
            "DATABASE_URL": f"sqlite+pysqlite:///{tmp_path / 'uvicorn-smoke.db'}",
            "PYTHONPATH": "apps/api",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318",
        }
    )
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.models; from app.core.database import Base, engine; Base.metadata.create_all(engine)",
        ],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--app-dir",
            "apps/api",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--proxy-headers",
            "--forwarded-allow-ips",
            "127.0.0.1",
            "--log-level",
            "warning",
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    response = None
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                response = httpx2.get(
                    f"http://127.0.0.1:{port}/api/health/live",
                    headers={"X-Request-ID": "uvicorn-compatibility"},
                    timeout=0.5,
                )
                break
            # On Windows an early loopback connection can time out instead
            # of being refused. Both are transient until the readiness deadline.
            except (httpx2.ConnectError, httpx2.ConnectTimeout):
                time.sleep(0.1)
    finally:
        output = _stop_process(process)

    if response is None:
        raise AssertionError(f"Uvicorn did not become ready:\n{output}")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    assert response.headers["X-Request-ID"] == "uvicorn-compatibility"
