"""Mandatory backend identity stays available while purchase authentication waits."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import UUID

import anyio
import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app import main
from app.composition.sources import source_resources
from app.core.database import get_db
from app.domains.billing import snapshot_router
from app.domains.identity import backend_router
from app.domains.identity.services import backend_delegation as delegation
from app.domains.purchases import router as purchases_router
from app.http import backend_auth
from app.http.dependencies import get_session_factory
from app.models import AuthSession, User, UserStatus
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.backend_consumers import backend_consumer
from apps.api.tests.support.kernel import manifest_fixture

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_purchase_authentication_cannot_starve_independent_introspection(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = postgres_session_factory
    consumer = backend_consumer()
    config = step1_settings(
        database_url=migrated_database.url.render_as_string(hide_password=False),
        backend_consumers=(consumer,),
        paid_access_clock_skew_seconds=5,
        billing_worker_enabled=False,
    )
    for module in (main, backend_router, backend_auth, snapshot_router, purchases_router):
        monkeypatch.setattr(module, "settings", config)
    monkeypatch.setattr(main, "SessionLocal", factory)
    monkeypatch.setattr(
        main,
        "source_resources",
        partial(
            source_resources,
            kernel_transport=httpx.MockTransport(lambda _: httpx.Response(200, json=manifest_fixture())),
        ),
    )
    parents: dict[str, str] = {}
    users: dict[str, UUID] = {}
    with factory() as db:
        for name in ("buyer", "paid"):
            user = User(
                tenant_id="anytoolai",
                region="ru",
                email=name + "@example.invalid",
                email_normalized=name + "@example.invalid",
                status=UserStatus.ACTIVE,
                email_verified_at=datetime.now(UTC),
            )
            db.add(user)
            db.flush()
            users[name] = user.id
            parents[name] = name + "p" * 43
            db.add(
                AuthSession(
                    user_id=user.id,
                    tenant_id=user.tenant_id,
                    region=user.region,
                    token_hash=delegation.credential_hash(parents[name]),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
        db.commit()
        code = delegation.issue_code(
            db,
            token=parents["paid"],
            tenant_id="anytoolai",
            region="ru",
            code_challenge=delegation.pkce_challenge("v" * 43),
            consumer_id=consumer.consumer_id,
        )
        token = delegation.exchange_code(
            db,
            code=code.code,
            verifier="v" * 43,
            tenant_id="anytoolai",
            region="ru",
            consumer_id=consumer.consumer_id,
        ).access_token

    def local_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    app = main.create_app()
    app.dependency_overrides[get_db] = local_db
    app.dependency_overrides[get_session_factory] = lambda: factory
    headers = {"Authorization": "Bearer " + consumer.backend_to_portal_current_secret.get_secret_value()}
    intro = "/internal/v1/backend-sessions/introspect"
    snapshot = f"/internal/v1/access-snapshots/{users['paid']}?tenant_id=anytoolai&region=ru"
    buyer_headers = {"Authorization": "Bearer " + parents["buyer"]}
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as client,
    ):
        assert (await client.post(intro, headers=headers, json={"access_token": token})).status_code == 200
        assert (await client.get(snapshot, headers=headers)).status_code == 200
        assert (
            await client.post("/api/purchases/review", headers=buyer_headers, json={"product_id": "proposal_ai"})
        ).status_code == 409
        requests: list[asyncio.Task[httpx.Response]] = []
        identity_request: asyncio.Task[httpx.Response] | None = None
        with factory() as holder:
            holder.scalars(select(AuthSession).where(AuthSession.user_id == users["buyer"]).with_for_update()).one()
            try:
                limiter = anyio.to_thread.current_default_thread_limiter()
                requests = [
                    asyncio.create_task(
                        client.post("/api/purchases/review", headers=buyer_headers, json={"product_id": "proposal_ai"})
                    )
                    for _ in range(int(limiter.total_tokens))
                ]
                async with asyncio.timeout(5):
                    while limiter.borrowed_tokens != limiter.total_tokens:
                        await asyncio.sleep(0.01)
                assert app.state.sources.preflight.active_count == 0
                assert (await asyncio.wait_for(client.get(snapshot, headers=headers), 2)).status_code == 200
                identity_request = asyncio.create_task(
                    client.post(intro, headers=headers, json={"access_token": token})
                )
                # Kernel's real identity timeout is two seconds. Do not release the buyer first.
                response = await asyncio.wait_for(asyncio.shield(identity_request), 2)
                assert response.status_code == 200, response.text
                assert response.json()["user_id"] == str(users["paid"])
            finally:
                holder.rollback()
                await asyncio.gather(*requests)
                if identity_request is not None:
                    await identity_request

        # Contention in introspection's own storage is bounded and remains fail-closed.
        with factory() as holder:
            holder.execute(text("LOCK TABLE backend_session_delegations IN ACCESS EXCLUSIVE MODE"))
            try:
                refused = await asyncio.wait_for(client.post(intro, headers=headers, json={"access_token": token}), 2)
                assert refused.status_code == 503
                assert refused.json() == {"detail": {"code": "backend_session_unavailable"}}
                assert refused.headers["cache-control"] == "no-store"
            finally:
                holder.rollback()
        assert (await client.post(intro, headers=headers, json={"access_token": token})).status_code == 200
