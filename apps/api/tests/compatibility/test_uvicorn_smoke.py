from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

import httpx2


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def test_uvicorn_serves_application_with_production_proxy_flags() -> None:
    port = _available_port()
    environment = {
        **os.environ,
        "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318",
        "SKIP_LEGAL_SEED": "true",
    }
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

    try:
        deadline = time.monotonic() + 10
        response = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                response = httpx2.get(
                    f"http://127.0.0.1:{port}/health/live",
                    headers={"X-Request-ID": "uvicorn-compatibility"},
                    timeout=0.5,
                )
                break
            except httpx2.ConnectError:
                time.sleep(0.1)

        if response is None:
            output = process.stdout.read() if process.stdout is not None else ""
            raise AssertionError(f"Uvicorn did not become ready:\n{output}")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert response.headers["X-Request-ID"] == "uvicorn-compatibility"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
