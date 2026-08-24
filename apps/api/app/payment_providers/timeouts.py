from __future__ import annotations

import time
from dataclasses import dataclass

import httpx


class PaymentsApiRequestBudget:
    """Wall-clock budget shared by provider attempts and retry backoff.

    The budget limits work between attempts. It cannot interrupt an in-flight
    synchronous ``httpx.Client.request`` call; HTTPX phase timeouts remain the
    mechanism that bounds connection, read, write, and pool inactivity.
    """

    def __init__(self, *, timeout_seconds: float) -> None:
        self.expires_at = time.perf_counter() + timeout_seconds

    def remaining_seconds(self) -> float:
        return max(0.0, self.expires_at - time.perf_counter())


@dataclass(frozen=True)
class PaymentsApiTimeoutPolicy:
    timeout_seconds: float
    connect_timeout_seconds: float
    read_timeout_seconds: float
    write_timeout_seconds: float
    pool_timeout_seconds: float

    def default_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            timeout=self.timeout_seconds,
            connect=self.connect_timeout_seconds,
            read=self.read_timeout_seconds,
            write=self.write_timeout_seconds,
            pool=self.pool_timeout_seconds,
        )

    def budget_for_request(self, *, timeout_seconds: float | None) -> PaymentsApiRequestBudget:
        return PaymentsApiRequestBudget(timeout_seconds=self.request_timeout_seconds(timeout_seconds))

    def request_timeout(
        self,
        *,
        timeout_seconds: float | None,
        remaining_seconds: float | None = None,
    ) -> httpx.Timeout:
        timeout = self.request_timeout_seconds(timeout_seconds)
        if remaining_seconds is not None:
            timeout = min(timeout, remaining_seconds)
        return httpx.Timeout(
            timeout=timeout,
            connect=min(timeout, self.connect_timeout_seconds),
            read=min(timeout, self.read_timeout_seconds),
            write=min(timeout, self.write_timeout_seconds),
            pool=min(timeout, self.pool_timeout_seconds),
        )

    def request_timeout_seconds(self, timeout_seconds: float | None) -> float:
        return timeout_seconds if timeout_seconds is not None else self.timeout_seconds
