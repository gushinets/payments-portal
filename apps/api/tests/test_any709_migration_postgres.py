"""Consolidated ANY-709 upgrades preserve existing data and fail atomically."""

from __future__ import annotations

from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import IntegrityError

from apps.api.tests.support.postgres import alembic_test_config, reset_public_schema
from apps.api.tests.test_target_persistence_postgres import (
    CUSTOMER_ID,
    PURCHASE_ID,
    USER_ID,
    _insert_purchase,
    _seed_subscription_graph,
)

pytestmark = pytest.mark.postgres
PREDECESSOR = "20261001_0002"
HEAD = "20261027_0003"


def _columns(engine: Engine) -> dict[str, list[str]]:
    inspector = inspect(engine)
    return {
        table: [column["name"] for column in inspector.get_columns(table)]
        for table in inspector.get_table_names()
        if table != "alembic_version"
    }


def _rows(engine: Engine, columns: dict[str, list[str]]) -> dict[str, list[str]]:
    quote = engine.dialect.identifier_preparer.quote
    with engine.connect() as connection:
        return {
            table: connection.execute(
                text(
                    "SELECT to_jsonb(retained)::text FROM "
                    f"(SELECT {', '.join(map(quote, names))} FROM {quote(table)}) retained "
                    "ORDER BY to_jsonb(retained)::text"
                )
            )
            .scalars()
            .all()
            for table, names in columns.items()
        }


@pytest.mark.parametrize(
    "state",
    [
        "created",
        "preparing",
        "awaiting_external_result",
        "linked",
        "manual_review",
        "failed_before_external_effect",
        "resolved_no_external_effect",
    ],
)
def test_any709_consolidated_upgrade_preserves_rows_and_backfills_only_scopes(
    postgres_engine: Engine, database_test_url: URL, state: str
) -> None:
    reset_public_schema(postgres_engine)
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, PREDECESSOR)
        with postgres_engine.begin() as connection:
            _seed_subscription_graph(connection)
            connection.execute(text("UPDATE purchase_intents SET state = :state"), {"state": state})
            connection.execute(
                text(
                    "UPDATE external_subscriptions SET external_subscription_id = 'retained-subscription', "
                    "external_agreement_id = 'retained-agreement'"
                )
            )
            for kind in ("customer", "agreement"):
                connection.execute(
                    text(
                        "INSERT INTO external_create_operations "
                        "(create_operation_id, operation_kind, customer_id, purchase_intent_id, "
                        "request_correlation_key, operation_state, unknown_since, unknown_recovery_deadline_at, "
                        "recovery_hint_schema_version, recovery_hint_document) "
                        "VALUES (:id, :kind, :customer, :purchase, :key, 'possible_send', now(), "
                        "now() + interval '2 hours', 'retained-v1', '{\"outer_id\":\"retained\"}')"
                    ),
                    {
                        "id": uuid4(),
                        "kind": kind,
                        "customer": CUSTOMER_ID,
                        "purchase": PURCHASE_ID if kind == "agreement" else None,
                        "key": f"retained-{kind}",
                    },
                )
        columns = _columns(postgres_engine)
        before = _rows(postgres_engine, columns)
        command.upgrade(config, "head")

    assert _rows(postgres_engine, columns) == before
    with postgres_engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == HEAD
        assert connection.execute(text("SELECT count(*) FROM commercial_product_heads")).scalar_one() == 0
        assert connection.execute(
            text("SELECT first_name, surname, patronymic FROM users WHERE id = :id"), {"id": USER_ID}
        ).one() == (None, None, None)
        assert connection.execute(text("SELECT provider_origin FROM external_billing_customers")).scalar_one() is None
        assert connection.execute(
            text(
                "SELECT operation_kind, external_billing_account_id, send_fence FROM external_create_operations "
                "ORDER BY operation_kind"
            )
        ).all() == [("agreement", "account-a", None), ("customer", "account-a", None)]
        holds = connection.execute(
            text(
                "SELECT user_id, product_id, external_billing_account_id, purchase_intent_id "
                "FROM billing_purchase_scope_holds"
            )
        ).all()
        expected = (
            []
            if state in {"failed_before_external_effect", "resolved_no_external_effect"}
            else [(USER_ID, "product-a", "account-a", PURCHASE_ID)]
        )
        assert holds == expected


def test_any709_existing_head_preserves_names_origins_fences_and_all_rows(
    migrated_database: Engine, database_test_url: URL
) -> None:
    with migrated_database.begin() as connection:
        _seed_subscription_graph(connection)
        connection.execute(text("UPDATE users SET first_name = 'Retained', surname = 'Name', patronymic = 'Value'"))
        connection.execute(text("UPDATE external_billing_customers SET provider_origin = 'https://billing.test'"))
        connection.execute(
            text(
                "INSERT INTO external_create_operations "
                "(create_operation_id, operation_kind, customer_id, purchase_intent_id, external_billing_account_id, "
                "request_correlation_key, operation_state, send_fence, unknown_since, unknown_recovery_deadline_at) "
                "VALUES (:id, 'agreement', :customer, :purchase, 'account-a', 'retained-financial-key', "
                "'possible_send', :fence, now(), now() + interval '2 hours')"
            ),
            {"id": uuid4(), "customer": CUSTOMER_ID, "purchase": PURCHASE_ID, "fence": uuid4()},
        )
        connection.execute(
            text(
                "INSERT INTO billing_purchase_scope_holds "
                "(user_id, product_id, external_billing_account_id, purchase_intent_id) "
                "VALUES (:user, 'product-a', 'account-a', :purchase)"
            ),
            {"user": USER_ID, "purchase": PURCHASE_ID},
        )
    columns = _columns(migrated_database)
    before = _rows(migrated_database, columns)
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "head")
    assert _rows(migrated_database, columns) == before


def test_any709_ambiguous_legacy_holds_abort_entire_consolidated_upgrade(
    postgres_engine: Engine, database_test_url: URL
) -> None:
    reset_public_schema(postgres_engine)
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, PREDECESSOR)
        with postgres_engine.begin() as connection:
            _seed_subscription_graph(connection)
            _insert_purchase(connection, purchase_id=uuid4(), idempotency_key="conflicting-purchase")
        columns = _columns(postgres_engine)
        before = _rows(postgres_engine, columns)
        with pytest.raises(IntegrityError) as caught:
            command.upgrade(config, "head")
        assert caught.value.orig.diag.constraint_name == "billing_purchase_scope_holds_pkey"
    assert _columns(postgres_engine) == columns
    assert _rows(postgres_engine, columns) == before
    with postgres_engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PREDECESSOR
