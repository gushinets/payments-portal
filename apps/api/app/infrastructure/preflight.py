"""Bounded, process-local outer I/O, independent of FastAPI's sync/DB workers.

One owner per application lifespan and event loop. With W worker processes the
limits multiply by W (the current launches default to one worker). The operator
CLI additionally holds operator_preflight_lock for one active dry-run/publish
across processes sharing its trusted local file; this is not a distributed cap.
Only fresh source evaluation uses these slots, never DB-only reads or future
reserved reconciliation/recovery. No SQLAlchemy resource belongs in this scope.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from collections.abc import AsyncIterator, Callable, Coroutine, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Any, TypeVar

from app.core.errors import AppError


class PreflightDeadlineExceeded(AppError):
    def __init__(self) -> None:
        super().__init__("preflight_deadline_exceeded")


class PreflightSaturated(AppError):
    def __init__(self) -> None:
        super().__init__("preflight_saturated")


class PreflightClosed(AppError):
    def __init__(self) -> None:
        super().__init__("preflight_closed")


class PreflightCleanupPending(AppError):
    def __init__(self) -> None:
        super().__init__("preflight_cleanup_pending")


@dataclass(frozen=True)
class PreflightPolicy:
    total_timeout_seconds: float
    cleanup_timeout_seconds: float
    max_active: int
    max_waiting: int

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.total_timeout_seconds)
            or not math.isfinite(self.cleanup_timeout_seconds)
            or not 0 < self.cleanup_timeout_seconds < self.total_timeout_seconds
            or not 1 <= self.max_active <= 128
            or not 0 <= self.max_waiting <= 128
        ):
            raise ValueError("invalid finite preflight policy")


T = TypeVar("T")


class PreflightBudget:
    """One nonrenewable deadline, created BEFORE admission wait.

    run() bounds a complete async read including stream close. Cancellation
    starts at work_deadline, leaving a cleanup reserve inside deadline. If a
    transport ignores cancellation, its task stays attached to the occupied
    slot until it actually stops. At most one source task per occupied slot is
    allowed; replacement calls cannot accumulate abandoned work. Once a source
    enters protected cleanup, cancellation stops only its bounded waiter: the
    same counted source task owns cleanup through completion.
    """

    def __init__(self, owner: PreflightAdmission) -> None:
        self._owner = owner
        self._deadline = time.monotonic() + owner.policy.total_timeout_seconds
        self._work_deadline = self.deadline - owner.policy.cleanup_timeout_seconds
        self._admitted = False
        self._finished = False
        self._tasks: set[asyncio.Task[Any]] = set()
        self._cleanup_tasks: set[asyncio.Task[Any]] = set()

    @property
    def deadline(self) -> float:
        return self._deadline

    @property
    def work_deadline(self) -> float:
        return self._work_deadline

    def remaining_seconds(self) -> float:
        self.check()
        return max(0.0, self.work_deadline - time.monotonic())

    def check(self) -> None:
        if time.monotonic() >= self.work_deadline:
            raise PreflightDeadlineExceeded()
        if self._owner.closed or self._finished:
            raise PreflightClosed()

    def _source_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        self._cleanup_tasks.discard(task)
        # Consume failures even if cancellation/deadline ended the caller.
        if not task.cancelled():
            task.exception()
        self._release_if_finished()

    def _release_if_finished(self) -> None:
        if self._finished and self._admitted and not self._tasks:
            self._admitted = False
            self._owner._release(self)

    @contextmanager
    def protect_source_cleanup(self) -> Iterator[None]:
        """Keep this resource-owning source task alive until cleanup finishes.

        Register before the first close await, including HTTPX's automatic
        close at EOF. No child task or shield is created. run()/aclose() still
        bound their wait but cannot cancel this phase or release its slot.
        """
        task = asyncio.current_task()
        if task is None or task not in self._tasks:
            raise RuntimeError("cleanup must belong to a counted source task")
        already_protected = task in self._cleanup_tasks
        self._cleanup_tasks.add(task)
        try:
            yield
        finally:
            if not already_protected:
                self._cleanup_tasks.discard(task)

    def _cancel_source(self, task: asyncio.Task[Any]) -> None:
        if task not in self._cleanup_tasks and not task.cancelling():
            task.cancel()

    async def _cancel_and_drain(self, task: asyncio.Task[Any]) -> None:
        self._cancel_source(task)
        remaining = min(
            self._owner.policy.cleanup_timeout_seconds,
            max(0.0, self.deadline - time.monotonic()),
        )
        if remaining:
            # wait() bounds this waiter without pretending the task was stopped.
            await asyncio.wait({task}, timeout=remaining)

    async def run(
        self,
        source: Callable[[], Coroutine[Any, Any, T]],
        *,
        on_schedule: Callable[[asyncio.Task[T]], None] | None = None,
    ) -> T:
        """Await genuine outer I/O, token-lock waits or retry waits on this budget.

        The source owns all its HTTP resources, including close in finally.
        Never pass blocking work, DB sessions or detached workers here.
        on_schedule synchronously exposes this call's counted task before the
        first waiter await. Admission refusal creates no task. After scheduling,
        only task.done(), not waiter failure, proves it cannot send later.
        """
        self.check()
        if not self._admitted or self._tasks:
            raise PreflightSaturated()
        task = asyncio.create_task(source())
        self._tasks.add(task)
        task.add_done_callback(self._source_done)
        try:
            if on_schedule is not None:
                on_schedule(task)
            done, _ = await asyncio.wait({task}, timeout=self.remaining_seconds())
            if not done:
                raise PreflightDeadlineExceeded()
            result = task.result()
            self.check()
            return result
        except BaseException:
            # Includes cancellation and the deadline expiring between task
            # creation and the first wait. Never abandon newly started I/O.
            if not task.done():
                await self._cancel_and_drain(task)
            raise
        finally:
            if task.done():
                self._tasks.discard(task)


class PreflightAdmission:
    def __init__(self, policy: PreflightPolicy) -> None:
        self.policy = policy
        self.closed = False
        self._active: set[PreflightBudget] = set()
        self._waiting: deque[tuple[asyncio.Future[None], PreflightBudget]] = deque()
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def cleanup_pending_count(self) -> int:
        return sum(budget._finished and bool(budget._tasks) for budget in self._active)

    @property
    def waiting_count(self) -> int:
        return len(self._waiting)

    def _activate(self, budget: PreflightBudget) -> None:
        budget._admitted = True
        self._active.add(budget)

    def _release(self, budget: PreflightBudget) -> None:
        self._active.discard(budget)
        while not self.closed and self._waiting and self.active_count < self.policy.max_active:
            waiter, queued = self._waiting.popleft()
            if waiter.done():
                continue
            if time.monotonic() >= queued.work_deadline:
                waiter.set_exception(PreflightDeadlineExceeded())
                continue
            self._activate(queued)
            waiter.set_result(None)

    @asynccontextmanager
    async def operation(self, *, bound_scope: bool = True) -> AsyncIterator[PreflightBudget]:
        loop = asyncio.get_running_loop()
        if self.closed:
            raise PreflightClosed()
        if self._loop is not None and loop is not self._loop:
            raise RuntimeError("preflight owner cannot cross event loops")
        self._loop = loop
        budget = PreflightBudget(self)
        waiter: asyncio.Future[None] | None = None
        try:
            if self.active_count < self.policy.max_active and not self._waiting:
                self._activate(budget)
            else:
                if self.waiting_count >= self.policy.max_waiting:
                    raise PreflightSaturated()
                waiter = loop.create_future()
                self._waiting.append((waiter, budget))
                try:
                    await asyncio.wait_for(waiter, timeout=budget.remaining_seconds())
                except TimeoutError:
                    raise PreflightDeadlineExceeded() from None
            budget.check()
            # Also bound waits between reads. Sync normalization must check the
            # same budget before/after; bounded payloads limit its input size.
            if bound_scope:
                try:
                    async with asyncio.timeout(budget.remaining_seconds()):
                        yield budget
                        budget.check()
                except TimeoutError:
                    raise PreflightDeadlineExceeded() from None
            else:
                # Worker source calls still use run()/check() on this absolute
                # budget. Short fenced DB units finish outside the I/O timeout;
                # their resource ownership and finite leases remain separate.
                yield budget
        finally:
            if waiter is not None:
                entry = (waiter, budget)
                if entry in self._waiting:
                    self._waiting.remove(entry)
            budget._finished = True
            budget._release_if_finished()

    async def aclose(self) -> None:
        """Stop admission; bounded shutdown retains counts for unfinished I/O."""
        self.closed = True
        while self._waiting:
            waiter, _ = self._waiting.popleft()
            if not waiter.done():
                waiter.set_exception(PreflightClosed())
        tasks: set[asyncio.Task[Any]] = set()
        for budget in self._active:
            for task in budget._tasks:
                tasks.add(task)
                budget._cancel_source(task)
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=self.policy.cleanup_timeout_seconds)
            if pending:
                raise PreflightCleanupPending()
