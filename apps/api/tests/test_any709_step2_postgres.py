"""Customer concurrency, recovery, session and populated forward-migration checks."""

from __future__ import annotations

import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from alembic import command
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing import bootstrap_account
from app.composition.sources import source_resources
from app.core.time import utc_now
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import (
    apply_customer_read,
    claim_customer_send,
    escalate_overdue_customers,
    reserve_customer,
)
from app.domains.identity.services.auth import register_user
from app.models import (
    AuthSession,
    BillingWorkItem,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    ExternalCreateOperationState as State,
    ExternalCreateOperationKind as Kind,
    ManualReviewCase,
    PurchaseIntent,
    User,
)
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.postgres import alembic_test_config, reset_public_schema

pytestmark = pytest.mark.postgres
TOKEN = "isolated-portal-token"


def seed(factory: sessionmaker[Session], *, verified: bool = True) -> None:
    config = step1_settings()
    with factory() as db:
        user = User(
            id=uuid4(),
            tenant_id=config.instance_tenant_id,
            region=config.instance_region,
            email="synthetic@example.com",
            email_normalized="synthetic@example.com",
            email_verified_at=utc_now() if verified else None,
            first_name="Synthetic",
        )
        db.add(user)
        db.flush()
        db.add(
            AuthSession(
                user_id=user.id,
                tenant_id=user.tenant_id,
                region=user.region,
                token_hash=hashlib.sha256(TOKEN.encode()).hexdigest(),
                expires_at=utc_now() + timedelta(days=1),
            )
        )
        db.commit()


def test_any709_step2_two_tabs_products_have_one_send_identity(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    config = step1_settings()
    seed(factory)
    with ThreadPoolExecutor(max_workers=2) as pool:
        slots = list(pool.map(lambda _: reserve_customer(factory, config, TOKEN), range(2)))
    assert slots[0].customer_id == slots[1].customer_id
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda slot: claim_customer_send(factory, config, TOKEN, slot), slots))
    assert sum(claim.may_create for claim in claims) == 1
    with factory() as db:
        op = db.scalar(select(ExternalCreateOperation))
        work = db.scalar(select(BillingWorkItem))
        assert op.purchase_intent_id is None and op.send_fence is not None
        assert op.unknown_recovery_deadline_at == op.unknown_since + timedelta(hours=2)
        assert work.next_attempt_at == op.unknown_recovery_deadline_at
        assert db.scalar(select(func.count()).select_from(PurchaseIntent)) == 0
        assert db.scalar(select(func.count()).select_from(ExternalBillingCustomer)) == 1


@pytest.mark.parametrize("candidates", [0, 1, 2])
def test_any709_step2_crash_zero_one_multiple_and_overdue_recovery(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], candidates: int
) -> None:
    factory = postgres_session_factory
    config = step1_settings()
    seed(factory)
    initial = reserve_customer(factory, config, TOKEN)
    claim = claim_customer_send(factory, config, TOKEN, initial)
    # Simulated crash immediately after committed possible_send: new process/open.
    reopened = reserve_customer(factory, config, TOKEN)
    assert not reopened.may_create and reopened.fence == claim.fence
    sends = []

    def transport(request: httpx.Request) -> httpx.Response:
        sends.append((request.method, request.url.path))
        if request.url.path.endswith("/auth"):
            return httpx.Response(200, json={"code": 200, "response": {"token": "server", "expires_in": 600}})
        rows = [{"user_id": 345 + i, "outer_id": initial.outer_key} for i in range(candidates)]
        return httpx.Response(
            200, json={"code": 200, "response": rows if request.url.path.endswith("/users") else rows[0]}
        )

    async def open_account() -> None:
        async with source_resources(config, lbx_transport=httpx.MockTransport(transport)) as sources:
            if candidates == 1:
                result = await bootstrap_account(sources, config, factory=factory, token=TOKEN)
                assert result.credential.get_secret_value()
            else:
                with pytest.raises(
                    BillingRefused, match="billing_identity_conflict" if candidates == 2 else "billing_customer_pending"
                ):
                    await bootstrap_account(sources, config, factory=factory, token=TOKEN)

    asyncio.run(open_account())
    assert all(method == "GET" for method, _ in sends)
    if candidates == 0:
        with factory() as db:
            op = db.scalar(select(ExternalCreateOperation))
            deadline = op.unknown_recovery_deadline_at
        assert escalate_overdue_customers(factory, now=deadline + timedelta(seconds=1)) == 1
        assert escalate_overdue_customers(factory, now=deadline + timedelta(hours=1)) == 0
        with factory() as db:
            op = db.scalar(select(ExternalCreateOperation))
            assert op.operation_state == State.MANUAL_REVIEW and op.resolved_at is None
            assert op.unknown_recovery_deadline_at == deadline
            assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 1


def test_any709_step2_late_fence_and_outer_key_drift(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    seed(factory)
    slot = reserve_customer(factory, step1_settings(), TOKEN)
    claim = claim_customer_send(factory, step1_settings(), TOKEN, slot)
    bound = apply_customer_read(factory, claim, provider_id="345", outer_key=claim.outer_key)
    repeated = apply_customer_read(factory, bound, provider_id="345", outer_key=bound.outer_key)
    assert repeated.fence == bound.fence
    with pytest.raises(BillingRefused, match="billing_customer_pending"):
        apply_customer_read(factory, claim, provider_id="346", outer_key=claim.outer_key)
    with pytest.raises(BillingRefused, match="billing_identity_conflict"):
        apply_customer_read(factory, bound, provider_id="345", outer_key="changed-provider-key")
    with factory() as db:
        customer = db.scalar(select(ExternalBillingCustomer))
        assert customer.billing_customer_key == claim.outer_key and customer.provider_customer_id == "345"
        assert customer.binding_state == "identity_conflict"


@pytest.mark.parametrize("failure", ["lost_reply", "malformed_success", "client_not_ready", "stale_session", "none"])
def test_any709_step2_real_bootstrap_reuses_one_customer_and_never_persists_secrets(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], failure: str
) -> None:
    factory = postgres_session_factory
    seed(factory)
    config = step1_settings(
        lbx_seller_organization_id="",
        kernel_base_url="",
        kernel_service_token="",
        kernel_mock_enabled=False,
    )
    posts = []
    outer = ""

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal outer
        if request.url.path.endswith("/auth"):
            return httpx.Response(200, json={"code": 200, "response": {"token": "server-secret", "expires_in": 600}})
        if request.method == "POST":
            posts.append(json.loads(request.content))
            outer = posts[-1]["outer_id"]
            assert posts[-1]["email"] == "synthetic@example.com"
            assert posts[-1]["user_name"] == "Synthetic" and "user_surname" not in posts[-1]
            if failure == "lost_reply":
                raise httpx.ReadTimeout("private transport exception", request=request)
            return httpx.Response(
                201, json={"code": 201, "response": {} if failure == "malformed_success" else {"user_id": 345}}
            )
        if request.url.path.endswith("/client/user"):
            if failure == "client_not_ready":
                return httpx.Response(401, json={"code": 401, "response": "Invalid login/pass"})
            if failure == "stale_session":
                with factory() as db:
                    auth = db.scalar(select(AuthSession))
                    db.delete(auth)
                    db.commit()
        row = {"user_id": 345, "outer_id": outer}
        return httpx.Response(
            200,
            json={"code": 200, "response": ([row] if outer else []) if request.url.path.endswith("/users") else row},
        )

    async def scenario() -> None:
        async with source_resources(config, lbx_transport=httpx.MockTransport(transport)) as sources:
            if failure in {"client_not_ready", "stale_session"}:
                with pytest.raises(BillingRefused):
                    await bootstrap_account(sources, config, factory=factory, token=TOKEN)
            else:
                assert (await bootstrap_account(sources, config, factory=factory, token=TOKEN)).credential
            if failure != "stale_session":
                if failure == "client_not_ready":
                    with pytest.raises(BillingRefused, match="billing_client_not_ready"):
                        await bootstrap_account(sources, config, factory=factory, token=TOKEN)
                else:
                    assert (await bootstrap_account(sources, config, factory=factory, token=TOKEN)).credential

    asyncio.run(scenario())
    assert len(posts) == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ExternalBillingCustomer)) == 1
        assert db.scalar(select(func.count()).select_from(ExternalCreateOperation)) == 1
        assert db.scalar(select(func.count()).select_from(PurchaseIntent)) == 0
        documents = [str(row.recovery_hint_document) for row in db.scalars(select(ExternalCreateOperation))]
        documents += [str(row.payload_document) for row in db.scalars(select(BillingWorkItem))]
        for secret in [posts[0]["password"], posts[0]["login"], "synthetic@example.com", "server-secret", "Synthetic"]:
            assert all(secret not in document for document in documents)


def test_any709_step2_existing_users_nullable_and_immutable_on_upgrade(
    postgres_engine: Engine, database_test_url: URL
) -> None:
    reset_public_schema(postgres_engine)
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "20261026_0004")
        user_id = uuid4()
        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id,tenant_id,region,email,email_normalized,status,metadata) VALUES (:id,'anytoolai','ru','synthetic@example.com','synthetic@example.com','active','{}')"
                ),
                {"id": user_id},
            )
        command.upgrade(config, "head")
    with postgres_engine.connect() as connection:
        row = connection.execute(
            text("SELECT id, first_name, surname, patronymic FROM users WHERE id=:id"), {"id": user_id}
        ).one()
        assert tuple(row) == (user_id, None, None, None)


def test_any709_step2_registration_does_not_allocate_billing(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    with postgres_session_factory() as db:
        result = register_user(
            db,
            tenant_id="anytoolai",
            region="ru",
            email="new@example.com",
            password="Very-secret-pass1!",
            personal_consent=True,
            offer_consent=True,
            client_ip=None,
            user_agent=None,
            route_locale="ru",
            surname="  Synthetic  ",
        )
        assert result.authentication.surname == "Synthetic" and result.authentication.first_name is None
        assert db.scalar(select(func.count()).select_from(ExternalBillingCustomer)) == 0
        assert db.scalar(select(func.count()).select_from(ExternalCreateOperation)) == 0


def test_any709_step2_provider_id_and_permanent_operation_uniqueness(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    seed(factory)
    claim = claim_customer_send(factory, step1_settings(), TOKEN, reserve_customer(factory, step1_settings(), TOKEN))
    apply_customer_read(factory, claim, provider_id="345", outer_key=claim.outer_key)
    with factory() as db:
        db.add(
            ExternalCreateOperation(
                customer_id=claim.customer_id,
                operation_kind=Kind.CUSTOMER,
                request_correlation_key="different",
                operation_state=State.PENDING,
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
        user = db.scalar(select(User))
        db.add(
            ExternalBillingCustomer(
                external_billing_account_id=step1_settings().lbx_external_billing_account_id,
                user_id=user.id,
                billing_customer_key="other",
                provider_customer_id="345",
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()


@pytest.mark.parametrize("verified", [True, False])
def test_any709_step2_bootstrap_http_guards_no_store_and_no_provider_input(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    verified: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import FastAPI
    from app.domains.billing import router as billing_router
    from app.http.dependencies import get_session_factory

    seed(postgres_session_factory, verified=verified)
    config = step1_settings()
    monkeypatch.setattr(billing_router, "settings", config)

    async def scenario() -> None:
        async with source_resources(
            config, lbx_transport=httpx.MockTransport(lambda _: pytest.fail("guard sent HTTP"))
        ) as sources:
            app = FastAPI()
            app.include_router(billing_router.router)
            app.state.sources = sources
            app.dependency_overrides[get_session_factory] = lambda: postgres_session_factory
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://portal.test"
            ) as client:
                anonymous = await client.post("/api/billing/widget-bootstrap", json={})
                assert anonymous.status_code == 401 and anonymous.headers["cache-control"] == "no-store"
                assert (await client.get("/api/billing/widget-bootstrap")).status_code == 405
                rejected = await client.post(
                    "/api/billing/widget-bootstrap",
                    json={"provider_customer_id": "345", "disablePayments": False},
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )
                assert rejected.status_code == 422
                if not verified:
                    unverified = await client.post(
                        "/api/billing/widget-bootstrap", json={}, headers={"Authorization": f"Bearer {TOKEN}"}
                    )
                    assert unverified.status_code == 403
                    assert unverified.json()["detail"]["code"] == "billing_email_verification_required"

    asyncio.run(scenario())


def test_any709_step2_provider_id_unique_across_different_users(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    seed(factory)
    claim = claim_customer_send(factory, step1_settings(), TOKEN, reserve_customer(factory, step1_settings(), TOKEN))
    apply_customer_read(factory, claim, provider_id="345", outer_key=claim.outer_key)
    with factory() as db:
        other = User(
            id=uuid4(),
            tenant_id="anytoolai",
            region="ru",
            email="other@example.com",
            email_normalized="other@example.com",
        )
        db.add(other)
        db.flush()
        db.add(
            ExternalBillingCustomer(
                external_billing_account_id=step1_settings().lbx_external_billing_account_id,
                user_id=other.id,
                billing_customer_key="other-opaque-key",
                provider_customer_id="345",
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()


def test_any709_step2_origin_change_does_not_reuse_old_provider_id(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    seed(factory)
    slot = reserve_customer(factory, step1_settings(), TOKEN)
    claim_customer_send(factory, step1_settings(), TOKEN, slot)
    with pytest.raises(BillingRefused, match="billing_connection_conflict"):
        reserve_customer(factory, step1_settings(lbx_base_url="https://different-provider.test"), TOKEN)


def test_any709_step2_only_proven_unsent_claim_can_reset_same_operation(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    from app.domains.billing.customers import release_unsent_claim

    factory = postgres_session_factory
    config = step1_settings()
    seed(factory)
    slot = reserve_customer(factory, config, TOKEN)
    first = claim_customer_send(factory, config, TOKEN, slot)
    release_unsent_claim(factory, first)
    with pytest.raises(BillingRefused, match="billing_customer_pending"):
        apply_customer_read(factory, first, provider_id="345", outer_key=first.outer_key)
    second = claim_customer_send(factory, config, TOKEN, reserve_customer(factory, config, TOKEN))
    assert second.may_create and second.fence != first.fence
    assert second.operation_id == first.operation_id and second.outer_key == first.outer_key
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(BillingWorkItem)) == 1
        assert (
            db.scalar(select(BillingWorkItem)).next_attempt_at
            == db.scalar(select(ExternalCreateOperation)).unknown_recovery_deadline_at
        )


def test_any709_step2_concurrent_real_bootstraps_dispatch_one_post(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    config = step1_settings()
    seed(factory)
    posts = []

    async def transport(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth"):
            return httpx.Response(200, json={"code": 200, "response": {"token": "server", "expires_in": 600}})
        if request.method == "POST":
            posts.append(json.loads(request.content))
            await asyncio.sleep(0)
            return httpx.Response(201, json={"code": 201, "response": {"user_id": 345}})
        rows = [{"user_id": 345, "outer_id": posts[0]["outer_id"]}] if posts else []
        return httpx.Response(
            200, json={"code": 200, "response": rows if request.url.path.endswith("/users") else rows[0]}
        )

    async def scenario() -> None:
        async with source_resources(config, lbx_transport=httpx.MockTransport(transport)) as sources:
            results = await asyncio.gather(
                *(bootstrap_account(sources, config, factory=factory, token=TOKEN) for _ in range(2)),
                return_exceptions=True,
            )
            assert all(
                not isinstance(result, BaseException) or isinstance(result, BillingRefused) for result in results
            )
            assert (await bootstrap_account(sources, config, factory=factory, token=TOKEN)).credential

    asyncio.run(scenario())
    assert len(posts) == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ExternalBillingCustomer)) == 1
        assert db.scalar(select(func.count()).select_from(ExternalCreateOperation)) == 1


def test_any709_step2_successful_http_bootstrap_is_no_store(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import FastAPI
    from app.domains.billing import router as billing_router
    from app.http.dependencies import get_session_factory

    config = step1_settings()
    seed(postgres_session_factory)
    monkeypatch.setattr(billing_router, "settings", config)
    outer = ""

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal outer
        if request.url.path.endswith("/auth"):
            return httpx.Response(200, json={"code": 200, "response": {"token": "server", "expires_in": 600}})
        if request.method == "POST":
            outer = json.loads(request.content)["outer_id"]
            return httpx.Response(201, json={"code": 201, "response": {"user_id": 345}})
        if request.url.path.endswith("/users"):
            return httpx.Response(200, json={"code": 200, "response": []})
        return httpx.Response(200, json={"code": 200, "response": {"user_id": 345, "outer_id": outer}})

    async def scenario() -> None:
        async with source_resources(config, lbx_transport=httpx.MockTransport(transport)) as sources:
            app = FastAPI()
            app.include_router(billing_router.router)
            app.state.sources = sources
            app.dependency_overrides[get_session_factory] = lambda: postgres_session_factory
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://portal.test"
            ) as client:
                response = await client.post(
                    "/api/billing/widget-bootstrap", json={}, headers={"Authorization": f"Bearer {TOKEN}"}
                )
                assert response.status_code == 200
                assert response.headers["cache-control"] == "no-store"
                assert response.headers["pragma"] == "no-cache"
                assert response.json()["presentation"] == "account"
                assert response.json()["disablePayments"] is True
                assert response.json()["serviceBaseUrl"] == config.lbx_provider_origin + "/api/rest/v1/client"

    asyncio.run(scenario())
