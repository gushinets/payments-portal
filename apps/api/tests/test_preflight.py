from __future__ import annotations

import asyncio
import time

import pytest

from app.infrastructure.preflight import (
    PreflightAdmission,
    PreflightCleanupPending,
    PreflightClosed,
    PreflightDeadlineExceeded,
    PreflightPolicy,
    PreflightSaturated,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _owner(*, total: float = 1, cleanup: float = 0.02, waiting: int = 1) -> PreflightAdmission:
    return PreflightAdmission(PreflightPolicy(total, cleanup, max_active=1, max_waiting=waiting))


async def test_active_and_waiting_capacity_is_finite_and_local_work_remains_independent() -> None:
    owner = _owner()
    queued_entered = asyncio.Event()

    async def queued_operation() -> None:
        async with owner.operation():
            queued_entered.set()

    async with owner.operation():
        queued = asyncio.create_task(queued_operation())
        await asyncio.sleep(0)
        assert owner.active_count == owner.waiting_count == 1
        with pytest.raises(PreflightSaturated):
            async with owner.operation():
                pytest.fail("saturated operation was admitted")
        # Pure synchronous Application/DB-only work has no dependency on owner.
        local_result = sum((1, 2, 3))
        assert local_result == 6
        assert not queued_entered.is_set()
    await queued
    assert queued_entered.is_set()
    assert owner.active_count == owner.waiting_count == 0
    await owner.aclose()


async def test_queue_time_consumes_same_budget_before_any_source_starts() -> None:
    owner = _owner(total=0.18)
    release = asyncio.Event()
    entered = asyncio.Event()
    elapsed: list[float] = []

    async def occupy() -> None:
        async with owner.operation():
            entered.set()
            await release.wait()

    holder = asyncio.create_task(occupy())
    await entered.wait()

    async def queued_read() -> None:
        started = time.monotonic()
        with pytest.raises(PreflightDeadlineExceeded):
            async with owner.operation() as budget:
                elapsed.append(time.monotonic() - started)
                assert budget.deadline - started < 0.19
                # Queue + source exceeds the total; source alone would fit.
                await budget.run(lambda: asyncio.sleep(0.12))

    queued = asyncio.create_task(queued_read())
    await asyncio.sleep(0.08)
    release.set()
    await holder
    await queued
    assert elapsed[0] >= 0.06
    assert owner.active_count == owner.waiting_count == 0
    await owner.aclose()


async def test_expired_queue_entry_never_starts_source_work() -> None:
    owner = _owner(total=0.1)
    entered = asyncio.Event()
    release_cleanup = asyncio.Event()
    cleanup_started = asyncio.Event()

    async def slow_close() -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            await release_cleanup.wait()

    async def holder() -> None:
        with pytest.raises(PreflightDeadlineExceeded):
            async with owner.operation() as budget:
                await budget.run(slow_close)

    holder_task = asyncio.create_task(holder())
    await entered.wait()
    with pytest.raises(PreflightDeadlineExceeded):
        async with owner.operation():
            pytest.fail("queued source work must not start after its deadline")
    await holder_task
    assert cleanup_started.is_set()
    assert owner.active_count == 1
    assert owner.waiting_count == 0
    release_cleanup.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert owner.active_count == 0
    await owner.aclose()


async def test_two_sequential_source_consumers_share_one_absolute_budget() -> None:
    owner = _owner(total=0.16)
    with pytest.raises(PreflightDeadlineExceeded):
        async with owner.operation() as budget:
            deadline = budget.deadline
            await budget.run(lambda: asyncio.sleep(0.08))
            assert budget.deadline == deadline
            await budget.run(lambda: asyncio.sleep(0.08))
    assert owner.active_count == owner.waiting_count == 0
    await owner.aclose()


async def test_budget_covers_normalization_and_rejects_success_after_expiry() -> None:
    owner = _owner(total=0.08)
    with pytest.raises(PreflightDeadlineExceeded):
        async with owner.operation() as budget:
            await budget.run(lambda: asyncio.sleep(0))
            # Deliberate blocking fault only in this test. A bounded synchronous
            # normalizer must check before/after and cannot return late success.
            time.sleep(0.09)
    assert owner.active_count == 0
    await owner.aclose()


@pytest.mark.parametrize("cancel", [True, False])
async def test_cancellation_or_deadline_retains_slot_until_source_cleanup_finishes(cancel: bool) -> None:
    owner = _owner(total=0.1)
    entered = asyncio.Event()
    cleanup_started = asyncio.Event()
    cleanup_finished = asyncio.Event()
    release_cleanup = asyncio.Event()

    async def source() -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            await release_cleanup.wait()
            cleanup_finished.set()

    async def operation() -> None:
        async with owner.operation() as budget:
            await budget.run(source)

    task = asyncio.create_task(operation())
    await entered.wait()
    started = time.monotonic()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(PreflightDeadlineExceeded):
            await task
    assert time.monotonic() - started < 0.2
    assert cleanup_started.is_set() and not cleanup_finished.is_set()
    assert owner.active_count == 1
    queued_entered = asyncio.Event()

    async def queued_operation() -> None:
        async with owner.operation():
            queued_entered.set()

    queued = asyncio.create_task(queued_operation())
    await asyncio.sleep(0)
    assert owner.waiting_count == 1
    assert not queued_entered.is_set()
    with pytest.raises(PreflightSaturated):
        async with owner.operation():
            pytest.fail("abandoned cleanup must not free capacity")
    release_cleanup.set()
    await queued
    assert cleanup_finished.is_set() and queued_entered.is_set()
    assert owner.active_count == owner.waiting_count == 0
    await owner.aclose()


async def test_cancelled_waiter_is_removed_without_leaking_or_releasing_active_slot() -> None:
    owner = _owner()

    async def queued_operation() -> None:
        async with owner.operation():
            pytest.fail("cancelled waiter was admitted")

    async with owner.operation():
        queued = asyncio.create_task(queued_operation())
        await asyncio.sleep(0)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert owner.active_count == 1
        assert owner.waiting_count == 0
    assert owner.active_count == 0
    await owner.aclose()


async def test_transport_error_does_not_leak_a_slot_and_budget_cannot_be_reused() -> None:
    owner = _owner()

    async def fail() -> None:
        raise ValueError("simulated source failure")

    with pytest.raises(ValueError):
        async with owner.operation() as budget:
            await budget.run(fail)
    assert owner.active_count == owner.waiting_count == 0
    with pytest.raises(PreflightClosed):
        await budget.run(lambda: asyncio.sleep(0))
    async with owner.operation():
        assert owner.active_count == 1
    await owner.aclose()
    with pytest.raises(PreflightClosed):
        async with owner.operation():
            pytest.fail("closed owner was reused")


async def test_shutdown_is_bounded_and_retains_unfinished_source_capacity() -> None:
    owner = _owner()
    entered = asyncio.Event()
    release_cleanup = asyncio.Event()
    cleanup_started = asyncio.Event()

    async def source() -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            await release_cleanup.wait()

    async def operation() -> None:
        async with owner.operation() as budget:
            await budget.run(source)

    task = asyncio.create_task(operation())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleanup_started.is_set()
    with pytest.raises(PreflightCleanupPending):
        await owner.aclose()
    assert owner.active_count == 1
    release_cleanup.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert owner.active_count == 0


async def test_token_lock_wait_and_retry_work_use_existing_budget() -> None:
    owner = _owner(total=0.08)
    lock = asyncio.Lock()
    await lock.acquire()
    with pytest.raises(PreflightDeadlineExceeded):
        async with owner.operation() as budget:
            await budget.run(lock.acquire)
    assert lock.locked()
    lock.release()
    assert owner.active_count == owner.waiting_count == 0
    await owner.aclose()


async def test_shutdown_keeps_already_running_protected_cleanup_counted_and_uncancelled() -> None:
    owner = _owner()
    cleanup_started = asyncio.Event()
    allow_cleanup = asyncio.Event()
    cleanup_finished = asyncio.Event()
    cleanup_cancelled = asyncio.Event()

    async def operation() -> None:
        async with owner.operation() as budget:

            async def source() -> None:
                with budget.protect_source_cleanup():
                    cleanup_started.set()
                    try:
                        await allow_cleanup.wait()
                    except asyncio.CancelledError:
                        cleanup_cancelled.set()
                        raise
                    cleanup_finished.set()

            await budget.run(source)

    caller = asyncio.create_task(operation())
    try:
        await asyncio.wait_for(cleanup_started.wait(), timeout=0.5)
        with pytest.raises(PreflightCleanupPending):
            await owner.aclose()
        assert owner.active_count == 1
        assert not cleanup_cancelled.is_set() and not cleanup_finished.is_set()
        assert not caller.done()
        allow_cleanup.set()
        done, _ = await asyncio.wait({caller}, timeout=0.5)
        assert caller in done
        with pytest.raises(PreflightClosed):
            caller.result()
        assert cleanup_finished.is_set() and not cleanup_cancelled.is_set()
        assert owner.active_count == owner.waiting_count == 0
    finally:
        allow_cleanup.set()
        if not caller.done():
            caller.cancel()
        await asyncio.wait({caller}, timeout=0.5)
        if caller.done() and not caller.cancelled():
            caller.exception()
