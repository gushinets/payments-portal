from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL


_TEST_DATABASE_SUFFIXES = ("_test", "_tests")
_SYSTEM_DATABASE_NAMES = frozenset({"postgres", "template0", "template1"})
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def validate_test_database_url(database_url: URL) -> URL:
    """Reject database targets that are unsafe for destructive test fixtures."""
    if database_url.get_backend_name() != "postgresql":
        raise ValueError("PostgreSQL test fixtures require a PostgreSQL URL")

    database_name = database_url.database
    if not database_name:
        raise ValueError("PostgreSQL test URL must include a database name")

    normalized_name = database_name.lower()
    if normalized_name in _SYSTEM_DATABASE_NAMES or not normalized_name.endswith(_TEST_DATABASE_SUFFIXES):
        raise ValueError(
            "Refusing destructive test operations for database "
            f"{database_name!r}; its name must end with '_test' or '_tests'"
        )

    return database_url


def create_test_database(database_test_url: URL, database_admin_url: URL) -> None:
    """Create a fresh physical PostgreSQL database for the test session."""
    validate_test_database_url(database_test_url)
    admin_engine = create_engine(database_admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            database_name = connection.dialect.identifier_preparer.quote(database_test_url.database)
            connection.execute(text(f"DROP DATABASE IF EXISTS {database_name} WITH (FORCE)"))
            connection.execute(text(f"CREATE DATABASE {database_name}"))
    finally:
        admin_engine.dispose()


def drop_test_database(database_test_url: URL, database_admin_url: URL) -> None:
    """Remove the physical PostgreSQL database after the test session."""
    validate_test_database_url(database_test_url)
    admin_engine = create_engine(database_admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            database_name = connection.dialect.identifier_preparer.quote(database_test_url.database)
            connection.execute(text(f"DROP DATABASE IF EXISTS {database_name} WITH (FORCE)"))
    finally:
        admin_engine.dispose()


def reset_public_schema(engine: Engine) -> None:
    """Remove test data and schema objects before applying migrations."""
    validate_test_database_url(engine.url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


@contextmanager
def alembic_test_config(database_test_url: URL) -> Iterator[Config]:
    """Configure Alembic for a test database without replacing pytest logging."""
    validate_test_database_url(database_test_url)
    database_url = database_test_url.render_as_string(hide_password=False)
    config = Config(str(REPOSITORY_ROOT / "apps/api/alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)

    # env.py uses app settings, so force the already-imported singleton and any
    # later settings import to the dedicated test DB.
    # Suppress Alembic's fileConfig call so it cannot replace pytest's logging
    # handlers while migrations run inside the test process.
    env_overrides = {
        "DATABASE_URL": database_url,
        "POSTGRES_DB": database_test_url.database or "",
        "POSTGRES_USER": database_test_url.username or "",
        "POSTGRES_PASSWORD": database_test_url.password or "",
        "POSTGRES_HOST": database_test_url.host or "",
        "POSTGRES_PORT": str(database_test_url.port or 5432),
    }
    with patch.dict(os.environ, env_overrides), patch("logging.config.fileConfig"):
        from app.core.settings import settings

        original_database_url = settings.database_url
        try:
            object.__setattr__(settings, "database_url", database_url)
            yield config
        finally:
            object.__setattr__(settings, "database_url", original_database_url)


def run_migrations(database_test_url: URL) -> None:
    """Upgrade the test database through the production Alembic chain."""
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "head")
