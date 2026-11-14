"""One cleanup loop and one shielded database owner, independent of billing."""

import asyncio
from functools import partial
import logging

import anyio

from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.delegation_cleanup import cleanup_batch
from app.infrastructure.preflight import PreflightCleanupPending
from app.infrastructure.sentry import Operation, report_exception

logger = logging.getLogger(__name__)
CLEANUP_INTERVAL_SECONDS = 60


class DelegationCleanup:
    def __init__(self, factory: SessionFactory, *, tenant_id: str, region: str, cleanup_timeout: float) -> None:
        self.factory = factory
        self.tenant_id = tenant_id
        self.region = region
        self.cleanup_timeout = cleanup_timeout
        self.stopping = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self.owner: asyncio.Task[bool] | None = None
        self.limiter = anyio.CapacityLimiter(1)

    def start(self) -> None:
        self.task = asyncio.create_task(self._loop(), name="delegation-cleanup")

    async def _loop(self) -> None:
        while not self.stopping.is_set():
            more = False
            self.owner = asyncio.create_task(
                anyio.to_thread.run_sync(
                    partial(cleanup_batch, self.factory, tenant_id=self.tenant_id, region=self.region),
                    limiter=self.limiter,
                )
            )
            self.owner.add_done_callback(self._completed)
            try:
                more = await asyncio.shield(self.owner)
            except Exception:
                # The actual owner's completion reports the failure, including
                # after waiter cancellation. Retry on the next interval.
                pass
            if more:
                await asyncio.sleep(0)
            else:
                try:
                    await asyncio.wait_for(self.stopping.wait(), timeout=CLEANUP_INTERVAL_SECONDS)
                except TimeoutError:
                    pass

    @staticmethod
    def _completed(owner: asyncio.Task[bool]) -> None:
        if not owner.cancelled():
            error = owner.exception()
            if error is not None:
                # No SQL parameters, credential hashes or identities in logs.
                logger.error("delegation_cleanup_failed")
                report_exception(error, operation=Operation.DELEGATION_CLEANUP)

    async def aclose(self) -> None:
        self.stopping.set()
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        # Cancelling the waiter must not close the pool under its still-running thread.
        if self.owner is not None:
            done, pending = await asyncio.wait({self.owner}, timeout=self.cleanup_timeout)
            if pending:
                raise PreflightCleanupPending()
            for owner in done:
                if not owner.cancelled():
                    owner.exception()
