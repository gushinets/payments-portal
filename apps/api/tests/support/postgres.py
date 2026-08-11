from __future__ import annotations

import os
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL


def create_test_database(database_test_url: URL, database_admin_url: URL) -> None:
    """Create a fresh physical PostgreSQL database for the test session."""
    admin_engine = create_engine(database_admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            database_name = connection.dialect.identifier_preparer.quote(
                database_test_url.database
            )
            connection.execute(
                text(f"DROP DATABASE IF EXISTS {database_name} WITH (FORCE)")
            )
            connection.execute(text(f"CREATE DATABASE {database_name}"))
    finally:
        admin_engine.dispose()


def drop_test_database(database_test_url: URL, database_admin_url: URL) -> None:
    """Remove the physical PostgreSQL database after the test session."""
    admin_engine = create_engine(database_admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            database_name = connection.dialect.identifier_preparer.quote(
                database_test_url.database
            )
            connection.execute(
                text(f"DROP DATABASE IF EXISTS {database_name} WITH (FORCE)")
            )
    finally:
        admin_engine.dispose()


def reset_public_schema(engine: Engine) -> None:
    """Remove test data and schema objects before applying migrations."""
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


def run_migrations(database_test_url: URL) -> None:
    """Upgrade the test database through the production Alembic chain."""
    database_url = database_test_url.render_as_string(hide_password=False)
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    # env.py reads DATABASE_URL first, so force it to the dedicated test DB.
    # Suppress Alembic's fileConfig call so it cannot replace pytest's logging
    # handlers while migrations run inside the test process.
    with (
        patch.dict(os.environ, {"DATABASE_URL": database_url}),
        patch("logging.config.fileConfig"),
    ):
        command.upgrade(config, "head")
