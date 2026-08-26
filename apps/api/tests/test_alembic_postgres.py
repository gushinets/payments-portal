from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import IntegrityError

from apps.api.tests.support.postgres import alembic_test_config, reset_public_schema


EXPECTED_REVISION_CHAIN = [
    "20260707_0001",
    "20260707_0002",
    "20260707_0003",
    "20260729_0004",
    "20260824_0005",
    "20260824_0006",
    "20260824_0007",
    "20260825_0008",
    "20260826_0009",
]

pytestmark = pytest.mark.postgres


def public_table_names(postgres_engine: Engine) -> set[str]:
    inspector = inspect(postgres_engine)
    return set(inspector.get_table_names(schema="public"))


def alembic_version_count(postgres_engine: Engine) -> int:
    with postgres_engine.connect() as connection:
        return connection.execute(text("SELECT count(*) FROM alembic_version")).scalar_one()


def current_alembic_revision(postgres_engine: Engine) -> str:
    with postgres_engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def seeded_legal_documents(postgres_engine: Engine) -> list[dict[str, str]]:
    with postgres_engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id::text, doc_type, version, content_hash FROM document_versions ORDER BY id")
        ).mappings()
        return [dict(row) for row in rows]


def seeded_catalog_summary(postgres_engine: Engine) -> dict[str, object]:
    with postgres_engine.connect() as connection:
        products = connection.execute(text("SELECT code FROM products ORDER BY code")).scalars().all()
        plans = (
            connection.execute(
                text(
                    "SELECT code, scope_type, price_amount_minor, currency, "
                    "billing_period, trial_days FROM plans ORDER BY code"
                )
            )
            .mappings()
            .all()
        )
        bundle_products = (
            connection.execute(
                text(
                    "SELECT b.code AS bundle_code, p.code AS product_code "
                    "FROM bundle_products bp "
                    "JOIN bundles b ON b.id = bp.bundle_id "
                    "JOIN products p ON p.id = bp.product_id "
                    "ORDER BY b.code, p.code"
                )
            )
            .mappings()
            .all()
        )
        price_components = (
            connection.execute(
                text(
                    "SELECT p.code AS plan_code, pc.component_code_snapshot, "
                    "pc.list_amount_minor, pc.discount_amount_minor, pc.amount_minor "
                    "FROM plan_price_components pc "
                    "JOIN plans p ON p.id = pc.plan_id "
                    "ORDER BY p.code, pc.position"
                )
            )
            .mappings()
            .all()
        )
        limits = (
            connection.execute(
                text(
                    "SELECT p.code AS plan_code, pl.metric, pl.limit_count, pl.period "
                    "FROM plan_limits pl "
                    "JOIN plans p ON p.id = pl.plan_id "
                    "ORDER BY p.code, pl.metric"
                )
            )
            .mappings()
            .all()
        )
        return {
            "products": list(products),
            "plans": [dict(row) for row in plans],
            "bundle_products": [dict(row) for row in bundle_products],
            "price_components": [dict(row) for row in price_components],
            "limits": [dict(row) for row in limits],
        }


def seeded_catalog_ids(postgres_engine: Engine) -> dict[str, str]:
    with postgres_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT 'product:' || code AS seed_key, id::text AS id FROM products "
                "UNION ALL "
                "SELECT 'bundle:' || code AS seed_key, id::text AS id FROM bundles "
                "UNION ALL "
                "SELECT 'bundle_product:' || b.code || ':' || p.code AS seed_key, "
                "bp.id::text AS id "
                "FROM bundle_products bp "
                "JOIN bundles b ON b.id = bp.bundle_id "
                "JOIN products p ON p.id = bp.product_id "
                "UNION ALL "
                "SELECT 'plan:' || code AS seed_key, id::text AS id FROM plans "
                "UNION ALL "
                "SELECT 'price_component:' || p.code || ':' || pc.position AS seed_key, "
                "pc.id::text AS id "
                "FROM plan_price_components pc "
                "JOIN plans p ON p.id = pc.plan_id "
                "UNION ALL "
                "SELECT 'limit:' || p.code || ':' || pl.metric AS seed_key, pl.id::text AS id "
                "FROM plan_limits pl "
                "JOIN plans p ON p.id = pl.plan_id "
                "ORDER BY seed_key"
            )
        ).mappings()
        return {row["seed_key"]: row["id"] for row in rows}


def assert_postgres_schema_contract(postgres_engine: Engine) -> None:
    inspector = inspect(postgres_engine)
    webhook_columns = {column["name"]: column for column in inspector.get_columns("payment_webhook_events")}
    payment_columns = {column["name"]: column for column in inspector.get_columns("payments")}
    entitlement_columns = {column["name"]: column for column in inspector.get_columns("entitlements")}
    event_columns = {column["name"]: column for column in inspector.get_columns("subscription_events")}
    assert isinstance(webhook_columns["raw_payload"]["type"], JSONB)
    assert isinstance(webhook_columns["headers"]["type"], JSONB)
    assert isinstance(payment_columns["raw_summary"]["type"], JSONB)
    assert isinstance(event_columns["metadata"]["type"], JSONB)
    assert "updated_at" in entitlement_columns
    assert "updated_at" not in event_columns
    plan_check_names = {constraint["name"] for constraint in inspector.get_check_constraints("plans")}
    assert "ck_plans_scope_references" in plan_check_names

    payment_foreign_keys = {
        (
            tuple(foreign_key["constrained_columns"]),
            foreign_key["referred_table"],
            tuple(foreign_key["referred_columns"]),
        )
        for foreign_key in inspector.get_foreign_keys("payments")
    }
    assert (("order_id",), "orders", ("id",)) in payment_foreign_keys
    assert (
        ("provider_account_id",),
        "payment_provider_accounts",
        ("id",),
    ) in payment_foreign_keys

    with postgres_engine.connect() as connection:
        partial_indexes = dict(
            connection.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname = 'public' AND indexdef LIKE '% WHERE %'"
                )
            ).all()
        )

    assert {
        "uq_bundle_products_active_product",
        "uq_document_versions_active_doc",
        "uq_payment_provider_accounts_default",
        "uq_payments_provider_account_payment_id",
        "uq_plans_active_code",
        "uq_refunds_provider_account_refund_id",
        "uq_subscriptions_live_all_access_scope",
        "uq_subscriptions_live_bundle_scope",
        "uq_subscriptions_live_product_scope",
    } <= partial_indexes.keys()
    payment_predicate = " ".join(
        partial_indexes["uq_payments_provider_account_payment_id"].upper().replace("(", " ").replace(")", " ").split()
    )
    assert payment_predicate.endswith("WHERE PROVIDER_PAYMENT_ID IS NOT NULL")
    for index_name, scope_type in (
        ("uq_subscriptions_live_all_access_scope", "ALL_ACCESS"),
        ("uq_subscriptions_live_bundle_scope", "BUNDLE"),
        ("uq_subscriptions_live_product_scope", "PRODUCT"),
    ):
        predicate = " ".join(partial_indexes[index_name].upper().replace("(", " ").replace(")", " ").split())
        assert f"SCOPE_TYPE = '{scope_type}'" in predicate
        for status in ("TRIALING", "ACTIVE", "PAST_DUE", "PAUSED"):
            assert f"'{status}'" in predicate


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


def prepare_legacy_access_source(postgres_engine: Engine, database_test_url: URL) -> None:
    reset_public_schema(postgres_engine)
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "20260824_0006")

    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, tenant_id, region, email, email_normalized, password_hash) "
                "VALUES (:id, 'anytoolai', 'ru', 'legacy@example.com', 'legacy@example.com', 'hash')"
            ),
            {"id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001"},
        )
        connection.execute(
            text(
                "INSERT INTO payment_provider_accounts "
                "(id, tenant_id, region, provider, default_currency) "
                "VALUES (:id, 'anytoolai', 'ru', 'cloudpayments', 'RUB')"
            ),
            {"id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb0001"},
        )
        connection.execute(
            text(
                "INSERT INTO orders "
                "(id, tenant_id, region, order_number, user_id, plan_id, status, amount_minor, currency, "
                "provider, provider_account_id, merchant_order_id, provider_invoice_id) "
                "VALUES (:id, 'anytoolai', 'ru', :order_number, :user_id, :plan_id, 'paid', 99000, 'RUB', "
                "'cloudpayments', :provider_account_id, :merchant_order_id, :provider_invoice_id)"
            ),
            [
                {
                    "id": "cccccccc-cccc-4ccc-8ccc-cccccccc0001",
                    "order_number": "legacy-order-1",
                    "user_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001",
                    "plan_id": "99999999-9999-4999-8999-999999999901",
                    "provider_account_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb0001",
                    "merchant_order_id": "legacy-invoice-1",
                    "provider_invoice_id": "legacy-invoice-1",
                },
                {
                    "id": "cccccccc-cccc-4ccc-8ccc-cccccccc0002",
                    "order_number": "legacy-order-2",
                    "user_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001",
                    "plan_id": "99999999-9999-4999-8999-999999999902",
                    "provider_account_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb0001",
                    "merchant_order_id": "legacy-invoice-2",
                    "provider_invoice_id": "legacy-invoice-2",
                },
            ],
        )


def upgrade_legacy_source_to_head(database_test_url: URL) -> None:
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "head")


def test_legacy_access_backfill_migrates_active_expired_and_skips_pending(
    postgres_engine: Engine,
    database_test_url: URL,
) -> None:
    prepare_legacy_access_source(postgres_engine, database_test_url)
    now = datetime.now(timezone.utc)
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO product_access_states "
                "(id, user_id, product_code, plan_code, last_invoice_id, status, starts_at, expires_at) "
                "VALUES "
                "(1, :user_id, 'document-summary', 'document-summary-pro', 'legacy-invoice-1', 'active', "
                ":active_start, :active_end), "
                "(2, :user_id, 'prompt-optimizer', 'prompt-optimizer-pro', 'legacy-invoice-2', 'active', "
                ":expired_start, :expired_end), "
                "(3, :user_id, 'pending-only', NULL, NULL, 'pending', NULL, NULL)"
            ),
            {
                "user_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001",
                "active_start": now - timedelta(days=2),
                "active_end": now + timedelta(days=28),
                "expired_start": now - timedelta(days=31),
                "expired_end": now - timedelta(days=1),
            },
        )

    upgrade_legacy_source_to_head(database_test_url)

    with postgres_engine.connect() as connection:
        migrated = (
            connection.execute(
                text(
                    "SELECT s.status AS subscription_status, e.status AS entitlement_status, "
                    "e.expired_at IS NOT NULL AS has_expired_evidence, "
                    "se.event_type, se.next_status, se.operation_idempotency_key, "
                    "se.metadata->>'legacy_access_state_id' AS legacy_id "
                    "FROM subscriptions s "
                    "JOIN entitlements e ON e.subscription_id = s.id "
                    "JOIN subscription_events se ON se.subscription_id = s.id "
                    "ORDER BY legacy_id"
                )
            )
            .mappings()
            .all()
        )
        table_exists = connection.execute(text("SELECT to_regclass('public.product_access_states')")).scalar_one()

    assert table_exists is None
    assert migrated == [
        {
            "subscription_status": "active",
            "entitlement_status": "active",
            "has_expired_evidence": False,
            "event_type": "legacy_access_migrated",
            "next_status": "active",
            "operation_idempotency_key": "legacy_access_migrated:1",
            "legacy_id": "1",
        },
        {
            "subscription_status": "expired",
            "entitlement_status": "expired",
            "has_expired_evidence": True,
            "event_type": "legacy_access_migrated",
            "next_status": "expired",
            "operation_idempotency_key": "legacy_access_migrated:2",
            "legacy_id": "2",
        },
    ]


def test_legacy_access_backfill_aborts_before_drop_on_ambiguous_order(
    postgres_engine: Engine,
    database_test_url: URL,
) -> None:
    prepare_legacy_access_source(postgres_engine, database_test_url)
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO orders "
                "(id, tenant_id, region, order_number, user_id, plan_id, status, amount_minor, currency, "
                "provider, provider_account_id, merchant_order_id, provider_invoice_id) "
                "VALUES (:id, 'anytoolai', 'ru', 'legacy-order-duplicate', :user_id, "
                "'99999999-9999-4999-8999-999999999901', 'paid', 99000, 'RUB', 'cloudpayments', "
                ":provider_account_id, 'legacy-invoice-duplicate', 'legacy-invoice-1')"
            ),
            {
                "id": "cccccccc-cccc-4ccc-8ccc-cccccccc0003",
                "user_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001",
                "provider_account_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb0001",
            },
        )
        connection.execute(
            text(
                "INSERT INTO product_access_states "
                "(id, user_id, product_code, plan_code, last_invoice_id, status, starts_at, expires_at) "
                "VALUES (1, :user_id, 'document-summary', 'document-summary-pro', 'legacy-invoice-1', "
                "'active', :starts_at, :expires_at)"
            ),
            {
                "user_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001",
                "starts_at": datetime.now(timezone.utc) - timedelta(days=2),
                "expires_at": datetime.now(timezone.utc) + timedelta(days=28),
            },
        )

    with pytest.raises(RuntimeError, match="order_reference_is_unmappable_or_ambiguous"):
        with alembic_test_config(database_test_url) as config:
            command.upgrade(config, "head")

    with postgres_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM subscriptions")).scalar_one() == 0
        assert connection.execute(text("SELECT to_regclass('public.product_access_states')")).scalar_one()


def test_clean_postgres_alembic_upgrade_and_downgrade(
    postgres_engine: Engine,
    database_test_url: URL,
) -> None:
    reset_public_schema(postgres_engine)
    pytest_logging_handlers = tuple(logging.getLogger().handlers)

    with alembic_test_config(database_test_url) as config:
        script = ScriptDirectory.from_config(config)
        heads = script.get_heads()
        assert heads == [EXPECTED_REVISION_CHAIN[-1]]
        assert script.get_bases() == [EXPECTED_REVISION_CHAIN[0]]
        assert [revision.revision for revision in reversed(list(script.walk_revisions()))] == EXPECTED_REVISION_CHAIN
        command.upgrade(config, "head")

    assert tuple(logging.getLogger().handlers) == pytest_logging_handlers
    tables = public_table_names(postgres_engine)
    assert "alembic_version" in tables
    assert "payment_provider_accounts" in tables
    assert "payment_webhook_events" in tables
    assert "password_reset_rate_limits" in tables
    assert "entitlements" in tables
    assert "subscription_events" in tables
    assert "product_access_states" not in tables
    assert seeded_legal_documents(postgres_engine) == expected_legal_documents()
    assert_postgres_schema_contract(postgres_engine)

    with alembic_test_config(database_test_url) as config:
        command.downgrade(config, "base")

    assert public_table_names(postgres_engine) == {"alembic_version"}
    assert alembic_version_count(postgres_engine) == 0

    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "head")

    tables = public_table_names(postgres_engine)
    assert "alembic_version" in tables
    assert "payment_provider_accounts" in tables
    assert "plans" in tables
    assert "payment_webhook_events" in tables
    assert "password_reset_rate_limits" in tables
    assert "entitlements" in tables
    assert "subscription_events" in tables
    assert "product_access_states" not in tables
    assert alembic_version_count(postgres_engine) == 1
    assert current_alembic_revision(postgres_engine) == EXPECTED_REVISION_CHAIN[-1]
    assert seeded_legal_documents(postgres_engine) == expected_legal_documents()
    assert_postgres_schema_contract(postgres_engine)
    assert seeded_catalog_ids(postgres_engine) == {
        "bundle:core-tools-bundle": "77777777-7777-4777-8777-777777777701",
        "bundle_product:core-tools-bundle:document-summary": ("88888888-8888-4888-8888-888888888801"),
        "bundle_product:core-tools-bundle:prompt-optimizer": ("88888888-8888-4888-8888-888888888802"),
        "limit:all-access-pro-ru:document_summary_runs": ("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb5"),
        "limit:all-access-pro-ru:prompt_optimizations": ("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb6"),
        "limit:core-tools-bundle-pro-ru:document_summary_runs": ("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb3"),
        "limit:core-tools-bundle-pro-ru:prompt_optimizations": ("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb4"),
        "limit:document-summary-pro:document_summary_runs": ("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1"),
        "limit:prompt-optimizer-pro:prompt_optimizations": ("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2"),
        "plan:all-access-pro-ru": "99999999-9999-4999-8999-999999999904",
        "plan:core-tools-bundle-pro-ru": "99999999-9999-4999-8999-999999999903",
        "plan:document-summary-pro": "99999999-9999-4999-8999-999999999901",
        "plan:prompt-optimizer-pro": "99999999-9999-4999-8999-999999999902",
        "price_component:all-access-pro-ru:1": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
        "price_component:all-access-pro-ru:2": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa4",
        "price_component:core-tools-bundle-pro-ru:1": ("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"),
        "price_component:core-tools-bundle-pro-ru:2": ("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2"),
        "product:document-summary": "66666666-6666-4666-8666-666666666601",
        "product:prompt-optimizer": "66666666-6666-4666-8666-666666666602",
    }
    assert seeded_catalog_summary(postgres_engine) == {
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


def test_live_subscription_unique_indexes_are_removed_on_downgrade(
    postgres_engine: Engine,
    database_test_url: URL,
) -> None:
    reset_public_schema(postgres_engine)
    index_names = {
        "uq_subscriptions_live_all_access_scope",
        "uq_subscriptions_live_bundle_scope",
        "uq_subscriptions_live_product_scope",
    }

    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "head")

    with postgres_engine.connect() as connection:
        upgraded_indexes = set(
            connection.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'subscriptions'")
            ).scalars()
        )
    assert index_names <= upgraded_indexes

    with alembic_test_config(database_test_url) as config:
        command.downgrade(config, "20260824_0007")

    with postgres_engine.connect() as connection:
        downgraded_indexes = set(
            connection.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'subscriptions'")
            ).scalars()
        )
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260824_0007"
    assert index_names.isdisjoint(downgraded_indexes)


def test_plan_scope_references_constraint_is_removed_on_downgrade(
    postgres_engine: Engine,
    database_test_url: URL,
) -> None:
    reset_public_schema(postgres_engine)

    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "head")

    with postgres_engine.connect() as connection:
        upgraded_constraints = set(
            connection.execute(
                text("SELECT conname FROM pg_constraint WHERE conrelid = 'plans'::regclass AND contype = 'c'")
            ).scalars()
        )
    assert "ck_plans_scope_references" in upgraded_constraints

    with alembic_test_config(database_test_url) as config:
        command.downgrade(config, "20260825_0008")

    with postgres_engine.connect() as connection:
        downgraded_constraints = set(
            connection.execute(
                text("SELECT conname FROM pg_constraint WHERE conrelid = 'plans'::regclass AND contype = 'c'")
            ).scalars()
        )
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260825_0008"
    assert "ck_plans_scope_references" not in downgraded_constraints


@pytest.mark.parametrize(
    ("scope_type", "has_product", "has_bundle", "is_valid"),
    (
        ("product", True, False, True),
        ("product", False, False, False),
        ("product", True, True, False),
        ("product", False, True, False),
        ("bundle", False, True, True),
        ("bundle", False, False, False),
        ("bundle", True, True, False),
        ("bundle", True, False, False),
        ("all_access", False, False, True),
        ("all_access", True, False, False),
        ("all_access", False, True, False),
        ("all_access", True, True, False),
    ),
)
def test_plan_scope_references_constraint_accepts_only_matching_references(
    postgres_engine: Engine,
    database_test_url: URL,
    scope_type: str,
    has_product: bool,
    has_bundle: bool,
    is_valid: bool,
) -> None:
    reset_public_schema(postgres_engine)

    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "head")

    with postgres_engine.connect() as connection:
        references = (
            connection.execute(
                text(
                    "SELECT "
                    "(SELECT id FROM products ORDER BY code LIMIT 1) AS product_id, "
                    "(SELECT id FROM bundles ORDER BY code LIMIT 1) AS bundle_id"
                )
            )
            .mappings()
            .one()
        )

    insert_plan = text(
        "INSERT INTO plans ("
        "id, tenant_id, region, code, name, scope_type, product_id, bundle_id, "
        "price_amount_minor, currency, billing_period, renewal_mode, trial_days, status, valid_from"
        ") VALUES ("
        ":id, 'anytoolai', 'ru', :code, :name, :scope_type, :product_id, :bundle_id, "
        "100, 'RUB', 'month', 'manual', 0, 'active', :valid_from"
        ")"
    )
    values = {
        "id": str(uuid.uuid4()),
        "code": f"scope-check-{scope_type}-{has_product}-{has_bundle}",
        "name": "Scope check plan",
        "scope_type": scope_type,
        "product_id": references["product_id"] if has_product else None,
        "bundle_id": references["bundle_id"] if has_bundle else None,
        "valid_from": datetime.now(timezone.utc),
    }

    if is_valid:
        with postgres_engine.begin() as connection:
            connection.execute(insert_plan, values)
    else:
        with pytest.raises(IntegrityError):
            with postgres_engine.begin() as connection:
                connection.execute(insert_plan, values)


def test_plan_scope_references_migration_fails_on_existing_invalid_rows(
    postgres_engine: Engine,
    database_test_url: URL,
) -> None:
    reset_public_schema(postgres_engine)

    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "20260825_0008")

    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO plans ("
                "id, tenant_id, region, code, name, scope_type, product_id, bundle_id, "
                "price_amount_minor, currency, billing_period, renewal_mode, trial_days, status, valid_from"
                ") VALUES ("
                "'99999999-9999-4999-8999-999999999905', "
                "'anytoolai', 'ru', 'invalid-plan-scope', 'Invalid Plan Scope', "
                "'product', NULL, NULL, 100, 'RUB', 'month', 'manual', 0, 'active', :valid_from"
                ")"
            ),
            {"valid_from": datetime.now(timezone.utc)},
        )

    with pytest.raises(RuntimeError, match="Cannot add ck_plans_scope_references"):
        with alembic_test_config(database_test_url) as config:
            command.upgrade(config, "head")

    with postgres_engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260825_0008"
        assert (
            connection.execute(text("SELECT count(*) FROM plans WHERE code = 'invalid-plan-scope'")).scalar_one() == 1
        )


def test_active_plan_versions_cannot_overlap(
    postgres_engine: Engine,
    database_test_url: URL,
) -> None:
    reset_public_schema(postgres_engine)

    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "head")

    with postgres_engine.connect() as connection:
        with connection.begin():
            seed_plan = (
                connection.execute(text("SELECT product_id, valid_from FROM plans WHERE code = 'document-summary-pro'"))
                .mappings()
                .one()
            )
            product_id = seed_plan["product_id"]
            valid_from = seed_plan["valid_from"]
            connection.execute(
                text("UPDATE plans SET valid_to = :valid_to WHERE code = 'document-summary-pro'"),
                {"valid_to": valid_from + timedelta(days=1)},
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
                        ":valid_from, :valid_to"
                        ")"
                    ),
                    {
                        "product_id": product_id,
                        "valid_from": valid_from - timedelta(days=1),
                        "valid_to": valid_from + timedelta(days=2),
                    },
                )
