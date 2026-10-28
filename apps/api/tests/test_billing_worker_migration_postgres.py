"""Forward worker migration preserves old work/send leases and enforces identity."""

from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import IntegrityError

from apps.api.tests.support.postgres import alembic_test_config, reset_public_schema

pytestmark = pytest.mark.postgres


def test_billing_worker_migration_preserves_populated_work_and_unique_coalescing(
    postgres_engine: Engine,
    database_test_url: URL,
) -> None:
    reset_public_schema(postgres_engine)
    identity = uuid4()
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "20261029_0003")
        with postgres_engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO billing_work_items
                (work_item_id, work_kind, scope_kind, scope_reference, coalescing_key,
                 payload_schema_version, payload_document, next_attempt_at, work_state, lease_owner, lease_expires_at)
                VALUES (:id, 'external_create_recovery', 'create_operation', 'retained-operation', 'retained-operation',
                        'v1', '{}', now() + interval '2 hours', 'pending', 'customer-send:retained', now() + interval '60 seconds')"""),
                {"id": identity},
            )
            before = connection.execute(text("SELECT to_jsonb(w) FROM billing_work_items w")).scalar_one()
        command.upgrade(config, "20261028_0004")
        with postgres_engine.connect() as connection:
            after = connection.execute(text("SELECT to_jsonb(w) FROM billing_work_items w")).scalar_one()
            assert after == {**before, "enqueue_generation": 0, "last_attempt_started_at": None}
        for kind in (
            "subscription_reconciliation",
            "subscription_trust_expiry",
            "billing_enrollment_sweep",
            "customer_inventory",
            "external_create_deadline",
        ):
            statement = text("""INSERT INTO billing_work_items
                (work_item_id, work_kind, scope_kind, scope_reference, coalescing_key,
                 payload_schema_version, payload_document, next_attempt_at, work_state)
                VALUES (:id, :kind, 'subscription', 'local-subscription', 'account:local-subscription', 'v1', '{}', now(), 'pending')""")
            with postgres_engine.begin() as connection:
                connection.execute(statement, {"id": uuid4(), "kind": kind})
            with pytest.raises(IntegrityError), postgres_engine.begin() as connection:
                connection.execute(statement, {"id": uuid4(), "kind": kind})
        with pytest.raises(IntegrityError), postgres_engine.begin() as connection:
            connection.execute(
                text("UPDATE billing_work_items SET enqueue_generation = -1 WHERE work_item_id=:id"), {"id": identity}
            )
        command.downgrade(config, "20261029_0003")
        assert "enqueue_generation" not in {
            column["name"] for column in inspect(postgres_engine).get_columns("billing_work_items")
        }
        with postgres_engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT to_jsonb(w) FROM billing_work_items w WHERE work_item_id=:id"), {"id": identity}
                ).scalar_one()
                == before
            )
