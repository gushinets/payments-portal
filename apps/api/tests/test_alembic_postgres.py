from __future__ import annotations

import os
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


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


def seeded_catalog_summary() -> dict[str, object]:
    engine = create_engine(TEST_DATABASE_URL, future=True)
    try:
        with engine.connect() as connection:
            products = connection.execute(
                text("SELECT code FROM products ORDER BY code")
            ).scalars().all()
            plans = connection.execute(
                text(
                    "SELECT code, scope_type, price_amount_minor, currency, "
                    "billing_period, trial_days FROM plans ORDER BY code"
                )
            ).mappings().all()
            bundle_products = connection.execute(
                text(
                    "SELECT b.code AS bundle_code, p.code AS product_code "
                    "FROM bundle_products bp "
                    "JOIN bundles b ON b.id = bp.bundle_id "
                    "JOIN products p ON p.id = bp.product_id "
                    "ORDER BY b.code, p.code"
                )
            ).mappings().all()
            price_components = connection.execute(
                text(
                    "SELECT p.code AS plan_code, pc.component_code_snapshot, "
                    "pc.list_amount_minor, pc.discount_amount_minor, pc.amount_minor "
                    "FROM plan_price_components pc "
                    "JOIN plans p ON p.id = pc.plan_id "
                    "ORDER BY p.code, pc.position"
                )
            ).mappings().all()
            limits = connection.execute(
                text(
                    "SELECT p.code AS plan_code, pl.metric, pl.limit_count, pl.period "
                    "FROM plan_limits pl "
                    "JOIN plans p ON p.id = pl.plan_id "
                    "ORDER BY p.code, pl.metric"
                )
            ).mappings().all()
            return {
                "products": list(products),
                "plans": [dict(row) for row in plans],
                "bundle_products": [dict(row) for row in bundle_products],
                "price_components": [dict(row) for row in price_components],
                "limits": [dict(row) for row in limits],
            }
    finally:
        engine.dispose()


def expected_legal_documents() -> list[dict[str, str]]:
    repository_root = Path(__file__).resolve().parents[3]
    manifest_path = repository_root / "apps/web/src/generated/legal-manifest.json"
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
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    assert len(heads) == 1, f"expected one Alembic head, found {heads}"

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

    with patch.dict(os.environ, {"DATABASE_URL": TEST_DATABASE_URL}):
        command.upgrade(alembic_config(), "head")

    tables = public_table_names()
    assert "alembic_version" in tables
    assert "payment_provider_accounts" in tables
    assert "payment_webhook_events" in tables
    assert alembic_version_count() == 1
    assert seeded_legal_documents() == expected_legal_documents()
    assert seeded_catalog_summary() == {
        "products": ["document-summary", "prompt-optimizer"],
        "plans": [
            {
                "code": "all-access-pro-ru",
                "scope_type": "all_access",
                "price_amount_minor": 198000,
                "currency": "RUB",
                "billing_period": "month",
                "trial_days": 7,
            },
            {
                "code": "core-tools-bundle-pro-ru",
                "scope_type": "bundle",
                "price_amount_minor": 198000,
                "currency": "RUB",
                "billing_period": "month",
                "trial_days": 7,
            },
            {
                "code": "document-summary-pro",
                "scope_type": "product",
                "price_amount_minor": 99000,
                "currency": "RUB",
                "billing_period": "month",
                "trial_days": 7,
            },
            {
                "code": "prompt-optimizer-pro",
                "scope_type": "product",
                "price_amount_minor": 99000,
                "currency": "RUB",
                "billing_period": "month",
                "trial_days": 7,
            },
        ],
        "bundle_products": [
            {
                "bundle_code": "core-tools-bundle",
                "product_code": "document-summary",
            },
            {
                "bundle_code": "core-tools-bundle",
                "product_code": "prompt-optimizer",
            },
        ],
        "price_components": [
            {
                "plan_code": "all-access-pro-ru",
                "component_code_snapshot": "document-summary-pro",
                "list_amount_minor": 99000,
                "discount_amount_minor": 0,
                "amount_minor": 99000,
            },
            {
                "plan_code": "all-access-pro-ru",
                "component_code_snapshot": "prompt-optimizer-pro",
                "list_amount_minor": 99000,
                "discount_amount_minor": 0,
                "amount_minor": 99000,
            },
            {
                "plan_code": "core-tools-bundle-pro-ru",
                "component_code_snapshot": "document-summary-pro",
                "list_amount_minor": 99000,
                "discount_amount_minor": 0,
                "amount_minor": 99000,
            },
            {
                "plan_code": "core-tools-bundle-pro-ru",
                "component_code_snapshot": "prompt-optimizer-pro",
                "list_amount_minor": 99000,
                "discount_amount_minor": 0,
                "amount_minor": 99000,
            },
        ],
        "limits": [
            {
                "plan_code": "all-access-pro-ru",
                "metric": "document_summary_runs",
                "limit_count": 1000,
                "period": "month",
            },
            {
                "plan_code": "all-access-pro-ru",
                "metric": "prompt_optimizations",
                "limit_count": 1000,
                "period": "month",
            },
            {
                "plan_code": "core-tools-bundle-pro-ru",
                "metric": "document_summary_runs",
                "limit_count": 1000,
                "period": "month",
            },
            {
                "plan_code": "core-tools-bundle-pro-ru",
                "metric": "prompt_optimizations",
                "limit_count": 1000,
                "period": "month",
            },
            {
                "plan_code": "document-summary-pro",
                "metric": "document_summary_runs",
                "limit_count": 1000,
                "period": "month",
            },
            {
                "plan_code": "prompt-optimizer-pro",
                "metric": "prompt_optimizations",
                "limit_count": 1000,
                "period": "month",
            },
        ],
    }


def test_active_plan_versions_cannot_overlap() -> None:
    reset_public_schema()

    with patch.dict(os.environ, {"DATABASE_URL": TEST_DATABASE_URL}):
        command.upgrade(alembic_config(), "head")

    engine = create_engine(TEST_DATABASE_URL, future=True)
    try:
        with engine.connect() as connection:
            with connection.begin():
                product_id = connection.execute(
                    text("SELECT id FROM products WHERE code = 'document-summary'")
                ).scalar_one()
                connection.execute(
                    text(
                        "UPDATE plans SET valid_to = '2026-08-01T00:00:00Z' "
                        "WHERE code = 'document-summary-pro'"
                    )
                )

            with pytest.raises(IntegrityError):
                with connection.begin():
                    connection.execute(
                        text(
                            "INSERT INTO plans ("
                            "id, tenant_id, region, code, name, scope_type, product_id, "
                            "price_amount_minor, currency, billing_period, renewal_mode, "
                            "trial_days, status, valid_from, valid_to"
                            ") VALUES ("
                            "'99999999-9999-4999-8999-999999999905', "
                            "'anytoolai', 'ru', 'document-summary-pro', "
                            "'Document Summary Pro overlap', 'product', :product_id, "
                            "99000, 'RUB', 'month', 'manual', 7, 'active', "
                            "'2026-07-15T00:00:00Z', '2026-08-15T00:00:00Z'"
                            ")"
                        ),
                        {"product_id": product_id},
                    )
    finally:
        engine.dispose()
