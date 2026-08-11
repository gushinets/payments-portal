from __future__ import annotations

import os
from collections.abc import Iterator
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.orm import Session, sessionmaker


load_dotenv(".env")

DATABASE_TEST_URL = URL.create(
    drivername="postgresql+psycopg",
    username=os.environ["POSTGRES_USER_TEST"],
    password=os.environ["POSTGRES_PASSWORD_TEST"],
    host=os.getenv("POSTGRES_HOST_TEST", "localhost"),
    port=int(os.environ["POSTGRES_PORT_TEST"]),
    database=os.environ["POSTGRES_DB_TEST"],
)
DATABASE_BASE_URL = DATABASE_TEST_URL.set(database="postgres")


def _create_test_database() -> None:
    admin_engine = create_engine(DATABASE_BASE_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            database_name = connection.dialect.identifier_preparer.quote(
                DATABASE_TEST_URL.database
            )
            # Remove leftovers from an interrupted run before creating a clean DB.
            connection.execute(
                text(f"DROP DATABASE IF EXISTS {database_name} WITH (FORCE)")
            )
            connection.execute(text(f"CREATE DATABASE {database_name}"))
    finally:
        admin_engine.dispose()


def _drop_test_database() -> None:
    admin_engine = create_engine(DATABASE_BASE_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            database_name = connection.dialect.identifier_preparer.quote(
                DATABASE_TEST_URL.database
            )
            connection.execute(
                text(f"DROP DATABASE IF EXISTS {database_name} WITH (FORCE)")
            )
    finally:
        admin_engine.dispose()


def _reset_public_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


def _run_migrations() -> None:
    database_url = DATABASE_TEST_URL.render_as_string(hide_password=False)
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    # env.py reads DATABASE_URL first, so force it to the dedicated test DB.
    with patch.dict(os.environ, {"DATABASE_URL": database_url}):
        command.upgrade(config, "head")


@pytest.fixture(scope="session")
def postgres_engine() -> Iterator[Engine]:
    _create_test_database()
    engine = create_engine(DATABASE_TEST_URL, pool_pre_ping=True)

    try:
        yield engine
    finally:
        # Dispose pooled connections before PostgreSQL drops the physical DB.
        engine.dispose()
        _drop_test_database()


@pytest.fixture(scope="session")
def database_test_name() -> str:
    assert DATABASE_TEST_URL.database is not None
    return DATABASE_TEST_URL.database


@pytest.fixture
def migrated_database(postgres_engine: Engine) -> Iterator[Engine]:
    # Every test receives a clean schema built by the production migration chain.
    _reset_public_schema(postgres_engine)
    _run_migrations()
    yield postgres_engine


@pytest.fixture
def db_session(migrated_database: Engine) -> Iterator[Session]:
    session_factory = sessionmaker(
        bind=migrated_database,
        autoflush=False,
        autocommit=False,
    )
    with session_factory() as session:
        try:
            yield session
        finally:
            session.rollback()
