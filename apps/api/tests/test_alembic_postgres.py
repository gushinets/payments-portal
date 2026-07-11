from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


TEST_DATABASE_URL = os.getenv("TEST_POSTGRES_DATABASE_URL")


pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_POSTGRES_DATABASE_URL to run PostgreSQL Alembic integration tests",
)


def alembic_config() -> Config:
    api_root = Path(__file__).resolve().parents[1]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return config


def reset_public_schema() -> None:
    engine = create_engine(TEST_DATABASE_URL, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()


def public_table_names() -> set[str]:
    engine = create_engine(TEST_DATABASE_URL, future=True)
    try:
        inspector = inspect(engine)
        return set(inspector.get_table_names(schema="public"))
    finally:
        engine.dispose()


def alembic_version_count() -> int:
    engine = create_engine(TEST_DATABASE_URL, future=True)
    try:
        with engine.connect() as connection:
            return connection.execute(text("SELECT count(*) FROM alembic_version")).scalar_one()
    finally:
        engine.dispose()


def test_clean_postgres_alembic_upgrade_and_downgrade() -> None:
    reset_public_schema()

    command.upgrade(alembic_config(), "head")

    tables = public_table_names()
    assert "alembic_version" in tables
    assert "payment_provider_accounts" in tables
    assert "payment_webhook_events" in tables

    command.downgrade(alembic_config(), "base")

    assert public_table_names() == {"alembic_version"}
    assert alembic_version_count() == 0

    reset_public_schema()
