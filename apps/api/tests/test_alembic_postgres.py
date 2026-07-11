from __future__ import annotations

import os
import json
from pathlib import Path
from unittest.mock import patch

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


def seeded_legal_documents() -> list[dict[str, str]]:
    engine = create_engine(TEST_DATABASE_URL, future=True)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT id::text, doc_type, version, content_hash "
                    "FROM document_versions ORDER BY id"
                )
            ).mappings()
            return [dict(row) for row in rows]
    finally:
        engine.dispose()


def expected_legal_documents() -> list[dict[str, str]]:
    repository_root = Path(__file__).resolve().parents[3]
    manifest_path = repository_root / "docs/legal/ru/2026-07-02/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return sorted(
        [
            {
                "id": document["id"],
                "doc_type": document["docType"],
                "version": document["version"],
                "content_hash": document["contentHash"],
            }
            for document in manifest["documents"]
        ],
        key=lambda document: document["id"],
    )


def test_clean_postgres_alembic_upgrade_and_downgrade() -> None:
    reset_public_schema()

    with patch.dict(os.environ, {"DATABASE_URL": TEST_DATABASE_URL}):
        command.upgrade(alembic_config(), "head")

    tables = public_table_names()
    assert "alembic_version" in tables
    assert "payment_provider_accounts" in tables
    assert "payment_webhook_events" in tables
    assert seeded_legal_documents() == expected_legal_documents()

    with patch.dict(os.environ, {"DATABASE_URL": TEST_DATABASE_URL}):
        command.downgrade(alembic_config(), "base")

    assert public_table_names() == {"alembic_version"}
    assert alembic_version_count() == 0

    reset_public_schema()
