from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.pool import QueuePool


_TEST_DATABASE_SUFFIXES = ("_test", "_tests")
_SYSTEM_DATABASE_NAMES = frozenset({"postgres", "template0", "template1"})
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def validate_test_database_url(database_url: URL) -> URL:
    """Reject database targets that are unsafe for destructive test fixtures."""
    if database_url.get_backend_name() != "postgresql":
        raise ValueError("PostgreSQL test fixtures require a PostgreSQL URL")
    if "dbname" in database_url.query:
        raise ValueError("PostgreSQL test URL query must not override 'dbname'")

    database_name = database_url.database
    if not database_name:
        raise ValueError("PostgreSQL test URL must include a database name")
    if len(database_name.encode("utf-8")) > 63:
        raise ValueError("PostgreSQL test database names must not exceed 63 bytes")

    normalized_name = database_name.lower()
    if normalized_name in _SYSTEM_DATABASE_NAMES or not normalized_name.endswith(_TEST_DATABASE_SUFFIXES):
        raise ValueError(
            "Refusing destructive test operations for database "
            f"{database_name!r}; its name must end with '_test' or '_tests'"
        )

    return database_url


def session_test_database_url(configured_url: URL) -> URL:
    """Use explicit configuration for routing, never as a shared physical name."""
    validate_test_database_url(configured_url)
    return configured_url.set(database=f"portal_{uuid4().hex}_tests")


def _validate_admin_url(database_test_url: URL, database_admin_url: URL) -> None:
    validate_test_database_url(database_test_url)
    if database_admin_url != database_test_url.set(database="postgres"):
        raise ValueError("Test database admin URL must use the same server and credentials, with database 'postgres'")


def create_test_database(database_test_url: URL, database_admin_url: URL, *, template_url: URL | None = None) -> None:
    """Create a database without removing an existing target on collision."""
    _validate_admin_url(database_test_url, database_admin_url)
    if template_url is not None:
        _validate_admin_url(template_url, database_admin_url)
        if template_url.database == database_test_url.database:
            raise ValueError("A test database cannot be its own template")
    admin_engine = create_engine(database_admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            quote = connection.dialect.identifier_preparer.quote
            database_name = quote(database_test_url.database)
            template_clause = f" TEMPLATE {quote(template_url.database)}" if template_url is not None else ""
            connection.execute(text(f"CREATE DATABASE {database_name}{template_clause}"))
    finally:
        admin_engine.dispose()


def drop_test_database(database_test_url: URL, database_admin_url: URL) -> None:
    """Remove the physical PostgreSQL database after the test session."""
    _validate_admin_url(database_test_url, database_admin_url)
    admin_engine = create_engine(database_admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            database_name = connection.dialect.identifier_preparer.quote(database_test_url.database)
            connection.execute(text(f"DROP DATABASE {database_name}"))
    finally:
        admin_engine.dispose()


def dispose_test_engine(engine: Engine) -> None:
    """Close idle connections, preserving leaked connections as visible failures."""
    if isinstance(engine.pool, QueuePool) and (checked_out := engine.pool.checkedout()):
        raise RuntimeError(f"Test database {engine.url.database!r} has {checked_out} checked-out connections")
    engine.dispose()


class PostgresTestDatabase:
    """Own a session's engine and both databases, including partial setup cleanup."""

    def __init__(self, database_url: URL, admin_url: URL) -> None:
        _validate_admin_url(database_url, admin_url)
        name = database_url.database.removesuffix("_tests").removesuffix("_test")
        self.template_url = database_url.set(database=f"{name}_template_tests")
        validate_test_database_url(self.template_url)
        self.database_url = database_url
        self.admin_url = admin_url
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self._database_created = False
        self._template_created = False

    def create(self) -> None:
        create_test_database(self.database_url, self.admin_url)
        self._database_created = True
        create_test_database(self.template_url, self.admin_url)
        self._template_created = True
        run_migrations(self.template_url)

    def restore(self) -> None:
        """Replace only the owned scenario database; migration tests keep their resets."""
        if not self._database_created:
            raise RuntimeError(f"Test database {self.database_url.database!r} is not owned; refusing replacement")
        dispose_test_engine(self.engine)
        drop_test_database(self.database_url, self.admin_url)
        self._database_created = False
        create_test_database(self.database_url, self.admin_url, template_url=self.template_url)
        self._database_created = True

    def close(self) -> None:
        try:
            dispose_test_engine(self.engine)
            if self._database_created:
                drop_test_database(self.database_url, self.admin_url)
                self._database_created = False
        finally:
            if self._template_created:
                drop_test_database(self.template_url, self.admin_url)
                self._template_created = False


@contextmanager
def postgres_test_database(database_url: URL, admin_url: URL) -> Iterator[PostgresTestDatabase]:
    database = PostgresTestDatabase(database_url, admin_url)
    try:
        database.create()
        yield database
    finally:
        database.close()


def reset_public_schema(engine: Engine) -> None:
    """Remove test data and schema objects before applying migrations."""
    validate_test_database_url(engine.url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


@contextmanager
def alembic_test_config(
    database_test_url: URL,
    *,
    instance_tenant_id: str = "anytoolai",
    instance_region: str = "ru",
) -> Iterator[Config]:
    """Configure Alembic for a test database without replacing pytest logging."""
    validate_test_database_url(database_test_url)
    database_url = database_test_url.render_as_string(hide_password=False)
    config = Config(str(REPOSITORY_ROOT / "apps/api/alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

    # env.py uses app settings, so force the already-imported singleton and any
    # later settings import to the dedicated test DB.
    # Suppress Alembic's fileConfig call so it cannot replace pytest's logging
    # handlers while migrations run inside the test process.
    env_overrides = {
        "DATABASE_URL": database_url,
        "INSTANCE_TENANT_ID": instance_tenant_id,
        "INSTANCE_REGION": instance_region,
        "POSTGRES_DB": database_test_url.database or "",
        "POSTGRES_USER": database_test_url.username or "",
        "POSTGRES_PASSWORD": database_test_url.password or "",
        "POSTGRES_HOST": database_test_url.host or "",
        "POSTGRES_PORT": str(database_test_url.port or 5432),
    }
    with patch.dict(os.environ, env_overrides), patch("logging.config.fileConfig"):
        from app.core.settings import settings

        original_values = {
            "database_url": settings.database_url,
            "instance_tenant_id": settings.instance_tenant_id,
            "instance_region": settings.instance_region,
        }
        try:
            object.__setattr__(settings, "database_url", database_url)
            object.__setattr__(settings, "instance_tenant_id", instance_tenant_id)
            object.__setattr__(settings, "instance_region", instance_region)
            yield config
        finally:
            for name, value in original_values.items():
                object.__setattr__(settings, name, value)


def run_migrations(database_test_url: URL) -> None:
    """Upgrade the test database through the production Alembic chain."""
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "head")
