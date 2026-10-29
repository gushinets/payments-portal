"""Real local HTTP pools preserve urgent capacity under normal source saturation."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.composition.billing_worker import billing_worker_resources
from app.domains.billing.work_contracts import WorkLane
from app.jobs.billing import BillingWorker
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.lbx import FIXTURES

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize("resource", ["users", "tariffs"])
async def test_billing_worker_http_pools_reserve_all_urgent_slots(
    monkeypatch: pytest.MonkeyPatch, resource: str
) -> None:
    normal_count, urgent_count = 4, 2
    release, saturated = asyncio.Event(), asyncio.Event()
    held: set[int] = set()
    reached: set[int] = set()
    handlers: set[asyncio.Task[None]] = set()
    tariff = json.loads((FIXTURES / "tariff.json").read_text())["response"]

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        owner = asyncio.current_task()
        handlers.add(owner)
        try:
            request = await reader.readuntil(b"\r\n\r\n")
            path = request.split(b" ", 2)[1].decode("ascii")
            if path.endswith("/auth"):
                data = {"token": "synthetic-worker-pool-token", "expires_in": 600}
            else:
                identity = int(path.rsplit("/", 1)[1])
                reached.add(identity)
                if 100 <= identity < 100 + normal_count:
                    held.add(identity)
                    if len(held) == normal_count:
                        saturated.set()
                    await release.wait()
                data = (
                    {**tariff, "tariff_id": identity}
                    if "/tariffs/" in path
                    else {"user_id": identity, "outer_id": "synthetic-worker-pool"}
                )
            body = json.dumps({"code": 200, "response": data}).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\n\r\n"
                + body
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            handlers.discard(owner)

    async def no_start(self: BillingWorker) -> None:
        # Exercise production resource composition without claiming DB work.
        pass

    def forbidden_database() -> None:
        raise AssertionError("HTTP capacity test must not use a database")

    monkeypatch.setattr(BillingWorker, "start", no_start)
    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    configuration = step1_settings(
        lbx_base_url=f"http://127.0.0.1:{port}",
        billing_worker_enabled=True,
        billing_worker_normal_concurrency=normal_count,
        billing_worker_urgent_concurrency=urgent_count,
        billing_worker_io_timeout_seconds=20,
        preflight_max_active=1,
        lbx_connect_timeout_seconds=0.3,
        lbx_read_timeout_seconds=10,
        lbx_max_get_attempts=2,
    )
    try:
        async with server, billing_worker_resources(configuration, factory=forbidden_database) as worker:
            async with worker.admissions[WorkLane.URGENT].operation(bound_scope=False) as budget:
                await worker.client.get_user(user_id=1, budget=budget)

            async def read(lane: WorkLane, identity: int) -> None:
                async with worker.admissions[lane].operation(bound_scope=False) as budget:
                    if resource == "users":
                        await worker.client.get_user(user_id=identity, budget=budget)
                    else:
                        await worker.client.get_tariff(tariff_id=identity, budget=budget)

            normal = [asyncio.create_task(read(WorkLane.NORMAL, 100 + i)) for i in range(normal_count)]
            try:
                await asyncio.wait_for(saturated.wait(), timeout=5)
                async with asyncio.TaskGroup() as urgent:
                    for identity in range(900, 900 + urgent_count):
                        urgent.create_task(read(WorkLane.URGENT, identity))
                assert reached.issuperset(range(900, 900 + urgent_count))
                assert worker.admissions[WorkLane.NORMAL].active_count == normal_count
                assert not release.is_set()
            finally:
                release.set()
                await asyncio.gather(*normal)
    finally:
        release.set()
        server.close()
        await server.wait_closed()
        if handlers:
            await asyncio.gather(*handlers)
