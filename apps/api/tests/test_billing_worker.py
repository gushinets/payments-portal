"""Worker budgets, resource ownership, health and configuration. Synthetic only."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.composition.billing_worker import billing_worker_resources
from app.core.time import utc_now
from app.infrastructure.preflight import (
    PreflightAdmission,
    PreflightCleanupPending,
    PreflightDeadlineExceeded,
    PreflightPolicy,
)
from app.jobs.billing import BillingWorker
from app.http import health
from app.domains.billing.work import spread_seconds
from app.domains.billing.work_contracts import WorkLane
from app.main import create_app
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.lbx import lbx_settings
from apps.api.tests.factories.reconciliation import subject_factory

pytestmark = pytest.mark.anyio
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize(
    "field,value",
    [
        ("billing_worker_scan_batch_size", 101),
        ("billing_worker_scan_batch_size", 0),
        ("billing_worker_urgent_concurrency", 0),
        ("billing_worker_normal_concurrency", 17),
        ("billing_worker_io_timeout_seconds", float("inf")),
        ("billing_worker_io_timeout_seconds", 0.1),
    ],
)
def test_billing_worker_settings_refuse_unbounded_or_invalid(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        step1_settings(**{field: value})


def test_billing_worker_settings_propagate_and_match_documentation() -> None:
    defaults = {
        "BILLING_WORKER_ENABLED": "true",
        "BILLING_WORKER_URGENT_CONCURRENCY": "2",
        "BILLING_WORKER_NORMAL_CONCURRENCY": "1",
        "BILLING_WORKER_IO_TIMEOUT_SECONDS": "60",
        "BILLING_WORKER_SCAN_BATCH_SIZE": "100",
    }
    for path in ("docker-compose.yml", "docker-compose.prod.yml", "docker-compose.agent.yml"):
        config = yaml.safe_load((ROOT / path).read_text())["services"]
        for key, value in defaults.items():
            assert config["api"]["environment"][key] == f"${{{key}:-{value}}}"
    for path in (".env.example", ".env.production.example"):
        for key, value in defaults.items():
            assert f"{key}={value}" in (ROOT / path).read_text()
    text = (ROOT / "docs/engineering/ANY-715-billing-operations.md").read_text()
    for key in defaults:
        assert key in text
    assert "per-process" in text and "standalone" in text and "100" in text


async def test_billing_worker_unconfigured_or_disabled_creates_no_resources() -> None:
    for config in (
        step1_settings(billing_worker_enabled=False),
        lbx_settings(lbx_base_url="", lbx_server_username="", lbx_server_password="", billing_worker_enabled=True),
    ):
        async with billing_worker_resources(config) as worker:
            assert worker is None


async def test_billing_worker_health_named_schema_and_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "database_is_ready", lambda: True)
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/api/health/billing").json()["status"] == "disabled"
        worker = BillingWorker(step1_settings(), lambda: None, object())
        app.state.billing_worker = worker
        worker.last_scan_at = utc_now()
        assert client.get("/api/health/billing").json()["status"] == "running"
        worker.failures = 7  # A source outage alone leaves the identity API ready.
        assert client.get("/api/health/ready").status_code == 200
        worker.failed = True
        assert client.get("/api/health/ready").status_code == 503
        assert client.get("/api/health/live").status_code == 200
        assert client.get("/api/health/billing").json()["status"] == "degraded"
    schema = app.openapi()["paths"]["/api/health/billing"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert schema["$ref"].endswith("BillingHealthResponse")


async def test_billing_worker_cleanup_stays_counted_and_prevents_new_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = PreflightAdmission(PreflightPolicy(0.06, 0.01, 1, 0))
    release = asyncio.Event()
    entered = asyncio.Event()
    calls = 0

    async def source(budget: object) -> None:
        entered.set()
        try:
            await asyncio.sleep(10)
        finally:
            with budget.protect_source_cleanup():
                await release.wait()

    async def attempt() -> None:
        async with admission.operation() as budget:
            await budget.run(lambda: source(budget))

    task = asyncio.create_task(attempt())
    await entered.wait()
    with pytest.raises(PreflightDeadlineExceeded):
        await task
    assert admission.active_count == admission.cleanup_pending_count == 1
    worker = BillingWorker(step1_settings(billing_worker_urgent_concurrency=1), lambda: None, object())
    worker.admissions[WorkLane.URGENT] = admission
    worker.last_scan_at = utc_now()
    assert worker.ready and not worker.healthy

    async def forbidden(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        raise AssertionError("claimed while HTTP slot occupied")

    monkeypatch.setattr(worker, "db", forbidden)
    assert await worker.tick(WorkLane.URGENT) is False and calls == 0
    with pytest.raises(PreflightCleanupPending):
        await worker.aclose()
    assert worker.failed and admission.active_count == 1
    release.set()
    for _ in range(10):
        await asyncio.sleep(0)
    assert admission.active_count == 0
    await admission.aclose()


def test_billing_worker_spreading_is_earlier_only_and_lease_covers_io() -> None:
    identity = subject_factory().subscription_id
    for interval in (300, 900):
        value = spread_seconds(identity, interval)
        assert interval * 0.8 <= value <= interval
        assert spread_seconds(identity, interval) == value


async def test_billing_worker_cancelled_db_waiter_retains_capacity_context_and_shutdown_ownership() -> None:
    from contextvars import ContextVar
    from threading import Event

    release, entered = Event(), Event()
    context = ContextVar("billing_test_context", default="missing")
    observed: list[str] = []
    worker = BillingWorker(
        step1_settings(billing_worker_io_timeout_seconds=0.06, preflight_cleanup_timeout_seconds=0.01),
        lambda: None,
        object(),
    )
    worker.last_scan_at = utc_now()

    def unit() -> None:
        entered.set()
        assert release.wait(5)
        observed.append(context.get())

    context.set("request-context")
    task = asyncio.create_task(worker.db(WorkLane.LOCAL, unit))
    try:
        async with asyncio.timeout(2):
            while not entered.is_set():
                await asyncio.sleep(0.005)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert worker.db_limiters[WorkLane.LOCAL].borrowed_tokens == 1
        assert worker.cleanup_pending == 1 and not worker.healthy
        assert not await worker.tick(WorkLane.LOCAL)
        with pytest.raises(RuntimeError, match="resource owners"):
            await worker.start()
        with pytest.raises(PreflightCleanupPending):
            await worker.aclose()
        assert worker.failed and worker.db_limiters[WorkLane.LOCAL].borrowed_tokens == 1
    finally:
        release.set()
        owners = set(worker.db_tasks[WorkLane.LOCAL])
        if owners:
            await asyncio.wait_for(asyncio.gather(*owners), 2)
    assert observed == ["request-context"]
    assert worker.cleanup_pending == worker.db_limiters[WorkLane.LOCAL].borrowed_tokens == 0
    await worker.aclose()
