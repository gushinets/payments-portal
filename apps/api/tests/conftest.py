from __future__ import annotations

import os
from collections.abc import Iterator

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


load_dotenv()
for name, value in DEFAULT_API_TEST_ENV.items():
    os.environ.setdefault(name, value)


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
