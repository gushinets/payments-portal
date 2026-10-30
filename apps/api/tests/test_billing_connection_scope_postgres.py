"""Origin-scoped admission interleavings on real PostgreSQL; synthetic HTTP only."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event
from types import ModuleType

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.purchases import review_purchase
from app.composition.sources import source_resources
from app.core.settings import Settings
from app.domains.billing import customer_scope, customers
from app.domains.billing.contracts import BillingRefused
from app.domains.catalog import link_publication as links
from app.domains.catalog.mapping_evidence import MappingRefused
from app.domains.catalog.product_link import CurrentOffer
from app.domains.purchases import service
from app.domains.purchases.contracts import LegalEvidence, LegalSelection, PurchaseMeaning
from app.models import CommercialProductHead, ExternalBillingCustomer, PurchaseIntent
from apps.api.tests.support.any709_step1 import link_document, step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.test_any709_connection_scope_postgres import head, open_account, publish_existing
from apps.api.tests.test_any709_step2_postgres import TOKEN, seed

pytestmark = pytest.mark.postgres


def wait_for_advisory_wait(engine: Engine, pid: int) -> None:
    deadline = time.monotonic() + 0.7
    while time.monotonic() < deadline:
        with engine.connect() as db:
            if db.scalar(
                text("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=:pid AND NOT granted)"),
                {"pid": pid},
            ):
                return
        time.sleep(0.005)
    raise AssertionError("contender did not wait on the shared advisory lock")


def observed_lock(monkeypatch: pytest.MonkeyPatch, module: ModuleType) -> tuple[Event, list[int]]:
    entered, pids = Event(), []
    original = getattr(module, "lock_connection_scope")

    def record(db: Session, **kwargs: str) -> None:
        pids.append(db.scalar(text("SELECT pg_backend_pid()")))
        entered.set()
        original(db, **kwargs)

    monkeypatch.setattr(module, "lock_connection_scope", record)
    return entered, pids


def test_customer_read_serializes_origin_publication(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    head(factory, config, legacy=True, proven=False)
    read, release = Event(), Event()
    original = customer_scope.connection_accounts

    def pause(db: Session, origin: str) -> set[str]:
        result = original(db, origin)
        read.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(customer_scope, "connection_accounts", pause)
    attempted, pids = observed_lock(monkeypatch, links)
    with ThreadPoolExecutor(max_workers=2) as pool:
        opening = pool.submit(customers.reserve_customer, factory, config, TOKEN)
        try:
            assert read.wait(5)
            publication = pool.submit(publish_existing, factory, config)
            assert attempted.wait(5)
            wait_for_advisory_wait(migrated_database, pids[0])
        finally:
            release.set()
        with pytest.raises(BillingRefused, match="billing_connection_conflict"):
            opening.result(5)
        assert not publication.result(5).inserted
    monkeypatch.setattr(customer_scope, "connection_accounts", original)
    transport = PurchaseTransport()
    transport.pool = migrated_database.pool
    assert open_account(factory, config, transport).credential
    assert transport.creates("/users") == 1
    with factory() as db:
        assert original(db, config.lbx_provider_origin) == {config.lbx_legacy_credential_scope}
        assert (
            db.scalar(select(ExternalBillingCustomer)).external_billing_account_id == config.lbx_legacy_credential_scope
        )


@pytest.mark.parametrize("rollback", [False, True])
def test_publication_serializes_customer_and_releases_lock(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    rollback: bool,
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    head(factory, config, legacy=True, proven=False)
    entered, release = Event(), Event()
    original = links.require_compatible_connection

    def pause(db: Session, **kwargs: object) -> None:
        original(db, **kwargs)
        entered.set()
        assert release.wait(5)
        if rollback:
            raise MappingRefused("synthetic_rollback")

    monkeypatch.setattr(links, "require_compatible_connection", pause)
    attempted, pids = observed_lock(monkeypatch, customer_scope)
    with ThreadPoolExecutor(max_workers=2) as pool:
        publication = pool.submit(publish_existing, factory, config)
        try:
            assert entered.wait(5)
            opening = pool.submit(customers.reserve_customer, factory, config, TOKEN)
            assert attempted.wait(5)
            wait_for_advisory_wait(migrated_database, pids[0])
        finally:
            release.set()
        if rollback:
            with pytest.raises(MappingRefused, match="synthetic_rollback"):
                publication.result(5)
            with pytest.raises(BillingRefused, match="billing_connection_conflict"):
                opening.result(5)
            with factory() as db:
                assert db.scalar(select(func.count()).select_from(ExternalBillingCustomer)) == 0
        else:
            assert not publication.result(5).inserted
            slot = opening.result(5)
            with factory() as db:
                assert (
                    db.get(ExternalBillingCustomer, slot.customer_id).external_billing_account_id
                    == config.lbx_legacy_credential_scope
                )


def test_contention_timeout_is_bounded_and_does_not_reserve(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    head(factory, config, legacy=True, proven=False)
    entered, release = Event(), Event()
    original = links.require_compatible_connection

    def pause(db: Session, **kwargs: object) -> None:
        original(db, **kwargs)
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(links, "require_compatible_connection", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        publication = pool.submit(publish_existing, factory, config)
        try:
            assert entered.wait(5)
            started = time.monotonic()
            with pytest.raises(BillingRefused, match="billing_busy"):
                customers.reserve_customer(factory, config, TOKEN)
            assert time.monotonic() - started < 2
            with factory() as db:
                assert db.scalar(select(func.count()).select_from(ExternalBillingCustomer)) == 0
        finally:
            release.set()
        publication.result(5)


def test_other_origin_is_not_blocked(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    from app.infrastructure.persistence.billing_connections import lock_connection_scope

    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    with factory() as held:
        lock_connection_scope(
            held,
            tenant_id=config.instance_tenant_id,
            region=config.instance_region,
            provider_origin="https://unrelated.test",
        )
        result = customers.reserve_customer(factory, config, TOKEN)
        assert result.customer_id


def test_repeatable_read_is_not_silently_accepted(migrated_database: Engine) -> None:
    from app.infrastructure.persistence.billing_connections import lock_connection_scope, ConnectionIsolationUnsupported

    engine = migrated_database.execution_options(isolation_level="REPEATABLE READ")
    with Session(engine) as db:
        db.scalar(text("SELECT 1"))
        with pytest.raises(ConnectionIsolationUnsupported):
            lock_connection_scope(db, tenant_id="anytoolai", region="ru", provider_origin="https://lbx-client.test")


def test_first_customer_and_first_publication_share_one_scope(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    entered, release = Event(), Event()
    original = customer_scope.connection_accounts

    def pause(db: Session, origin: str) -> set[str]:
        value = original(db, origin)
        entered.set()
        assert release.wait(5)
        return value

    monkeypatch.setattr(customer_scope, "connection_accounts", pause)
    attempted, pids = observed_lock(monkeypatch, links)

    def publish_first() -> links.LinkPublicationResult:
        return links.publish_product_link(
            factory,
            evaluation=link_document(),
            expected_previous_revision=0,
            deadline=time.monotonic() + 5,
            lock_timeout_seconds=1,
            provider_origin=config.lbx_provider_origin,
            legacy_account_id=config.lbx_legacy_credential_scope,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        opening = pool.submit(customers.reserve_customer, factory, config, TOKEN)
        try:
            assert entered.wait(5)
            publication = pool.submit(publish_first)
            assert attempted.wait(5)
            wait_for_advisory_wait(migrated_database, pids[0])
        finally:
            release.set()
        slot = opening.result(5)
        assert publication.result(5).inserted
    with factory() as db:
        assert (
            db.get(ExternalBillingCustomer, slot.customer_id).external_billing_account_id
            == config.lbx_external_billing_account_id
        )
        assert (
            db.scalar(select(CommercialProductHead)).external_billing_account_id
            == config.lbx_external_billing_account_id
        )
        assert original(db, config.lbx_provider_origin) == {config.lbx_external_billing_account_id}


def test_connection_lock_identity_survives_credentials_rotation() -> None:
    from app.infrastructure.persistence.billing_connections import connection_lock_key

    first = step1_settings()
    rotated = step1_settings(lbx_server_username="rotated-user", lbx_server_password="rotated-password")

    def key(config: Settings) -> int:
        return connection_lock_key(config.instance_tenant_id, config.instance_region, config.lbx_provider_origin)

    assert first.lbx_legacy_credential_scope != rotated.lbx_legacy_credential_scope
    assert key(first) == key(rotated)
    assert key(first) != connection_lock_key(first.instance_tenant_id, first.instance_region, "https://other.test")


def test_purchase_acquires_origin_before_product(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    head(factory, config, legacy=True, proven=False)
    publish_existing(factory, config)
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))
    transport = PurchaseTransport()

    async def review() -> tuple[links.StoredProductLink, CurrentOffer, tuple[LegalEvidence, ...]]:
        async with source_resources(
            config,
            kernel_transport=httpx.MockTransport(transport.kernel),
            lbx_transport=httpx.MockTransport(transport.respond),
        ) as sources:
            return await review_purchase(sources, config, factory=factory, token=TOKEN, product_id="proposal_ai")

    link, offer, documents = asyncio.run(review())
    meaning = PurchaseMeaning(
        product_id="proposal_ai",
        revision_id=link.mapping_revision_id,
        expected_fingerprint=offer.fingerprint,
        documents=tuple(
            LegalSelection(document_version_id=d.document_version_id, acceptance_text_hash=d.acceptance_text_hash)
            for d in documents
        ),
    )
    attempted, pids = observed_lock(monkeypatch, customer_scope)
    from app.infrastructure.persistence.billing_connections import lock_connection_scope

    with factory() as publisher:
        lock_connection_scope(
            publisher,
            tenant_id=config.instance_tenant_id,
            region=config.instance_region,
            provider_origin=config.lbx_provider_origin,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                service.pin_purchase, factory, config, TOKEN, "protocol-test", meaning, link, offer, documents
            )
            try:
                assert attempted.wait(5)
                wait_for_advisory_wait(migrated_database, pids[0])
                # If purchase took product first, publication would block here.
                from app.infrastructure.persistence.commercial_mappings import mapping_lock_key

                assert publisher.scalar(
                    text("SELECT pg_try_advisory_xact_lock(:key)"),
                    {"key": mapping_lock_key(config.lbx_legacy_credential_scope, "product-head:v2:proposal_ai")},
                )
                publisher.commit()
            finally:
                publisher.rollback()
            accepted = future.result(5)
    assert accepted.id
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PurchaseIntent)) == 1
        assert customer_scope.connection_accounts(db, config.lbx_provider_origin) == {
            config.lbx_legacy_credential_scope
        }
