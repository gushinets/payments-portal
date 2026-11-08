from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from .support.postgres import (
    create_test_database,
    drop_test_database,
    reset_public_schema,
    run_migrations,
    validate_test_database_url,
)
from .support.settings import DEFAULT_API_TEST_ENV

if TYPE_CHECKING:
    from .factories.paid_access import AcceptedSubscription


load_dotenv()
os.environ["SENTRY_DSN"] = ""
os.environ["SENTRY_RELEASE"] = ""
# Never start source work from an inherited developer/stand configuration.
os.environ["BILLING_WORKER_ENABLED"] = "false"
for name, value in DEFAULT_API_TEST_ENV.items():
    os.environ.setdefault(name, value)


_POSTGRES_FIXTURES = frozenset(
    {
        "database_test_url",
        "database_admin_url",
        "postgres_engine",
        "postgres_session_factory",
        "migrated_database",
        "db_session",
    }
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Keep database-backed tests out of the PostgreSQL-independent partition."""
    postgres_marker = pytest.mark.postgres
    for item in items:
        if _POSTGRES_FIXTURES.intersection(item.fixturenames):
            item.add_marker(postgres_marker)


@pytest.fixture(scope="session")
def database_test_url() -> URL:
    """Resolve the PostgreSQL URL for tests that explicitly require a real DB.

    Use this fixture in PostgreSQL compatibility or integration fixtures. Tests
    without PostgreSQL requirements should not depend on it and remain portable.
    """
    if configured_url := os.getenv("TEST_POSTGRES_DATABASE_URL"):
        # Temporary CI compatibility: CI currently uses an application database
        # plus a separately named disposable database. Remove this branch once
        # local and CI tests share one canonical test database name.
        database_url = make_url(configured_url)
    else:
        required_names = (
            "POSTGRES_USER_TEST",
            "POSTGRES_PASSWORD_TEST",
            "POSTGRES_PORT_TEST",
            "POSTGRES_DB_TEST",
        )
        missing_names = [name for name in required_names if not os.getenv(name)]
        if missing_names:
            pytest.skip("PostgreSQL test configuration is unavailable; missing: " + ", ".join(missing_names))

        database_url = URL.create(
            drivername="postgresql+psycopg",
            username=os.environ["POSTGRES_USER_TEST"],
            password=os.environ["POSTGRES_PASSWORD_TEST"],
            host=os.getenv("POSTGRES_HOST_TEST", "localhost"),
            port=int(os.environ["POSTGRES_PORT_TEST"]),
            database=os.environ["POSTGRES_DB_TEST"],
        )

    return validate_test_database_url(database_url)


@pytest.fixture(scope="session")
def database_admin_url(database_test_url: URL) -> URL:
    """Provide the admin URL used only to create and drop the physical test DB.

    Database lifecycle fixtures should use this URL. Application-level tests
    must use ``database_test_url`` instead.
    """
    return database_test_url.set(database="postgres")


@pytest.fixture(scope="session")
def postgres_engine(
    database_test_url: URL,
    database_admin_url: URL,
) -> Iterator[Engine]:
    """Own one PostgreSQL database and SQLAlchemy engine for the test session.

    Request this fixture indirectly through ``migrated_database`` or
    ``db_session``. It creates the database once and always removes it at teardown.
    """
    create_test_database(database_test_url, database_admin_url)
    engine = create_engine(database_test_url, pool_pre_ping=True)

    try:
        yield engine
    finally:
        # Dispose pooled connections before PostgreSQL drops the physical DB.
        engine.dispose()
        drop_test_database(database_test_url, database_admin_url)


@pytest.fixture(scope="session")
def postgres_session_factory(postgres_engine: Engine) -> sessionmaker[Session]:
    """Create sessions against the test database owned by ``postgres_engine``."""
    return sessionmaker(
        bind=postgres_engine,
        autoflush=False,
        autocommit=False,
    )


@pytest.fixture
def migrated_database(
    postgres_engine: Engine,
    database_test_url: URL,
) -> Iterator[Engine]:
    """Provide a clean PostgreSQL schema upgraded through Alembic for one test.

    Use this fixture for ORM, migration-sensitive, concurrency, and PostgreSQL
    dialect tests. The schema is rebuilt before every requesting test.
    """
    reset_public_schema(postgres_engine)
    run_migrations(database_test_url)
    yield postgres_engine


@pytest.fixture
def db_session(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> Iterator[Session]:
    """Provide a rollback-safe ORM session backed by the migrated test database.

    Use it for tests that need direct ORM setup or assertions. API tests should
    instead depend on a future client fixture that overrides ``get_db``.
    """
    with postgres_session_factory() as session:
        try:
            yield session
        finally:
            session.rollback()


@pytest.fixture
def mapping_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep recorded-offer publications independent of the machine's date."""
    from apps.api.tests.support import v1_mapping_operator as mapping_operator
    from app.domains.catalog import publication

    ticks = count()

    def now() -> datetime:
        return datetime(2026, 10, 16, 12, tzinfo=UTC) + timedelta(microseconds=next(ticks))

    monkeypatch.setattr(mapping_operator, "utc_now", now)
    monkeypatch.setattr(publication, "utc_now", now)


@pytest.fixture
async def paid_terms_scenario(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> AcceptedSubscription:
    import time

    import httpx
    from sqlalchemy import event, select

    from app.composition.purchases import advance_purchase, confirm_purchase, review_purchase
    from app.composition.sources import source_resources
    from app.domains.catalog.link_publication import publish_product_link
    from app.models import ExternalSubscription, PurchaseIntent
    from apps.api.tests.factories.paid_access import AcceptedSubscription
    from apps.api.tests.factories.purchase_terms import reviewed_meaning
    from apps.api.tests.support.any709_step1 import link_document, link_selection, step1_settings
    from apps.api.tests.test_any709_step3_postgres import TOKEN, setup_purchase

    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    mode = getattr(request, "param", "legacy")
    product = "brief_decoder" if mode == "brief_decoder" else "proposal_ai"
    config = step1_settings(purchase_test_terms_enabled=mode != "legacy")
    if product == "brief_decoder":
        for selection, previous in ((link_selection(tariff_id=702), 1), (link_selection(product_id=product), 0)):
            publish_product_link(
                factory,
                evaluation=link_document(selection=selection),
                expected_previous_revision=previous,
                deadline=time.monotonic() + 5,
                lock_timeout_seconds=1,
                provider_origin=config.lbx_provider_origin,
            )

    def historical_insert(db: Session, flush_context: object, instances: object) -> None:
        for row in db.new:
            if isinstance(row, PurchaseIntent):
                row.accepted_snapshot["schema_version"] = "accepted-purchase:v1"
                row.accepted_snapshot.pop("technical_terms")
                row.accepted_snapshot["meaning"].pop("expected_technical_terms_digest")
                row.accepted_snapshot_schema_version = "accepted-purchase:v1"

    if mode == "legacy":
        event.listen(Session, "before_flush", historical_insert)
    try:
        async with source_resources(
            config,
            kernel_transport=httpx.MockTransport(transport.kernel),
            lbx_transport=httpx.MockTransport(transport.respond),
        ) as sources:
            link, offer, documents, terms = await review_purchase(
                sources, config, factory=factory, token=TOKEN, product_id=product
            )
            purchase = await confirm_purchase(
                sources,
                config,
                factory=factory,
                token=TOKEN,
                key="allowance-test",
                meaning=reviewed_meaning(product, link.mapping_revision_id, offer.fingerprint, documents, terms),
            )
            await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
    finally:
        if mode == "legacy":
            event.remove(Session, "before_flush", historical_insert)
    with factory() as db:
        subscription_id = db.scalar(select(ExternalSubscription.subscription_id))
        assert subscription_id is not None
    return AcceptedSubscription(subscription_id, purchase.user_id, purchase.accepted)
