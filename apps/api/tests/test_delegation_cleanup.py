"""The loop drains actual thread owners before its pool may be closed."""

import asyncio
from threading import Event

import pytest

from app.jobs import delegation_cleanup as jobs
from app.infrastructure.preflight import PreflightCleanupPending

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize("fail", [False, True])
async def test_shutdown_retains_running_database_owner(monkeypatch: pytest.MonkeyPatch, fail: bool) -> None:
    entered, release = Event(), Event()
    reports: list[Exception] = []

    def held_batch(*args: object, **kwargs: object) -> bool:
        entered.set()
        assert release.wait(5)
        if fail:
            raise RuntimeError("synthetic cleanup failure during shutdown")
        return False

    monkeypatch.setattr(jobs, "cleanup_batch", held_batch)
    monkeypatch.setattr(jobs, "report_exception", lambda error, **kwargs: reports.append(error))
    worker = jobs.DelegationCleanup(lambda: None, tenant_id="anytoolai", region="ru", cleanup_timeout=0.02)
    worker.start()
    try:
        async with asyncio.timeout(3):
            while not entered.is_set():
                await asyncio.sleep(0.001)
        with pytest.raises(PreflightCleanupPending):
            await worker.aclose()
        assert worker.owner is not None and not worker.owner.done()
    finally:
        release.set()
        worker.cleanup_timeout = 3
        await worker.aclose()
    assert worker.owner.done()
    assert len(reports) == int(fail)


async def test_backlog_continues_without_interval_and_errors_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    recovered = Event()
    reports: list[Exception] = []

    def batches(*args: object, **kwargs: object) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic database failure")
        if calls < 5:
            return True
        recovered.set()
        return False

    monkeypatch.setattr(jobs, "CLEANUP_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(jobs, "cleanup_batch", batches)
    monkeypatch.setattr(jobs, "report_exception", lambda error, **kwargs: reports.append(error))
    worker = jobs.DelegationCleanup(lambda: None, tenant_id="anytoolai", region="ru", cleanup_timeout=3)
    worker.start()
    try:
        async with asyncio.timeout(3):
            while not recovered.is_set():
                await asyncio.sleep(0.001)
    finally:
        await worker.aclose()
    assert calls >= 5 and len(reports) == 1
