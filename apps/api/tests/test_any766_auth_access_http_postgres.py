"""Step 12 TCP auth/access checkpoint; no live LBX, provider or external backend."""

import json
import os
import socket
import subprocess
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from threading import Thread
from time import monotonic, sleep

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from app.composition.backend_consumers import initialize_backend_consumers
from app.composition.backend_introspection import backend_introspection_resources
from app.composition.paid_reads import paid_read_resources
from app.core.database import get_db
from app.domains.billing import snapshot_router
from app.domains.identity import backend_router
from app.domains.identity.services.backend_delegation import pkce_challenge
from app.http import backend_auth
from app.main import create_app
from apps.api.tests.support.backend_consumers import backend_consumer, second_consumer
from apps.api.tests.test_access_snapshot_postgres import production_scenario as production_scenario
from apps.api.tests.factories.paid_runtime import reconcile
from apps.api.tests.test_any709_step2_postgres import TOKEN

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@contextmanager
def tcp_server(app: FastAPI) -> Iterator[str]:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = monotonic() + 10
            while not server.started:
                assert thread.is_alive() and monotonic() < deadline, "Portal HTTP startup failed"
                sleep(0.01)
            yield origin
        finally:
            server.should_exit = True
            thread.join(10)
            assert not thread.is_alive(), "Portal HTTP cleanup failed"


async def test_actual_portal_kernel_tcp_auth_access_for_two_consumers(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = Path(os.environ.get("ANY766_KERNEL_ROOT", Path(__file__).resolve().parents[4] / "anytoolai-platform"))
    executable = kernel / ".quick-check-venv/bin/python"
    probe = kernel / "tests/support/portal_auth_access_probe.py"
    if not executable.is_file() or not probe.is_file():
        pytest.skip("Step 12 TCP checkpoint requires the prepared paired Kernel checkout (ANY766_KERNEL_ROOT)")
    scenario, factory = production_scenario, postgres_session_factory
    await reconcile(scenario, factory)
    consumers = (backend_consumer(), second_consumer())
    config = scenario[2].model_copy(update={"backend_consumers": consumers})
    for module in (backend_auth, backend_router, snapshot_router):
        monkeypatch.setattr(module, "settings", config)
    app = create_app()

    def database_session() -> Iterator[Session]:
        with factory() as db:
            yield db

    @asynccontextmanager
    async def local_resources(app: FastAPI) -> AsyncIterator[None]:
        initialize_backend_consumers(config, factory)
        async with (
            paid_read_resources(config, factory=factory) as reads,
            backend_introspection_resources(config, factory=factory) as introspection,
        ):
            app.state.paid_reads = reads
            app.state.backend_introspection = introspection
            yield

    app.dependency_overrides[get_db] = database_session
    app.router.lifespan_context = local_resources
    verifier = "synthetic-tcp-verifier-" + "v" * 32
    with tcp_server(app) as origin, httpx.Client(base_url=origin, trust_env=False) as client:
        cases = []
        for consumer in consumers:
            response = client.post(
                "/api/backend-session-codes",
                headers={"Authorization": "Bearer " + TOKEN},
                json={
                    "consumer_id": consumer.consumer_id,
                    "code_challenge": pkce_challenge(verifier),
                    "code_challenge_method": "S256",
                },
            )
            assert response.status_code == 200
            cases.append(
                {
                    "consumer_id": consumer.consumer_id,
                    "code": response.json()["code"],
                    "service_token": consumer.backend_to_portal_current_secret.get_secret_value(),
                    "products": ["proposal_ai"] if consumer.consumer_id == "platform-kernel" else [],
                }
            )
        environment = os.environ.copy()
        environment["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
        environment["ANYTOOLAI_POSTGRES_TEST_DATABASE_URL"] = (
            factory.kw["bind"].url.set(database="postgres").render_as_string(hide_password=False)
        )
        environment["ANYTOOLAI_DATABASE_URL"] = environment["ANYTOOLAI_POSTGRES_TEST_DATABASE_URL"]
        result = subprocess.run(
            [str(executable), str(probe)],
            cwd=kernel,
            env=environment,
            input=json.dumps({"portal_origin": origin, "verifier": verifier, "consumers": cases}),
            text=True,
            capture_output=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "PASS: two consumer-bound TCP exchanges" in result.stdout
        # Runtime Swagger/OpenAPI is served by the same actual application.
        assert client.get("/docs").status_code == 200
        operation = client.get("/openapi.json").json()["paths"]["/internal/v1/access-snapshots/{user_id}"]["get"]
        assert operation["security"] == [{"BackendServiceBearer": []}]
