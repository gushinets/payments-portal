"""The consolidated migration retains recovery evidence and original deadlines."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import select, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.orm import Session

from app.infrastructure.queries import purchases as queries
from app.models import BillingWorkItem, ExternalCreateOperation
from apps.api.tests.support.postgres import alembic_test_config, reset_public_schema
from apps.api.tests.test_any709_migration_postgres import _columns, _rows
from apps.api.tests.test_target_persistence_postgres import CUSTOMER_ID, PURCHASE_ID, USER_ID, _seed_subscription_graph

pytestmark = pytest.mark.postgres


def test_recovery_window_upgrade_preserves_history_and_original_deadline_fallback(
    postgres_engine: Engine, database_test_url: URL
) -> None:
    reset_public_schema(postgres_engine)
    operation_id = uuid4()
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "20261001_0002")
        with postgres_engine.begin() as connection:
            _seed_subscription_graph(connection)
            connection.execute(
                text(
                    "INSERT INTO external_create_operations (create_operation_id, operation_kind, customer_id, "
                    "purchase_intent_id, request_correlation_key, operation_state, "
                    "unknown_since, unknown_recovery_deadline_at, recovery_hint_schema_version, recovery_hint_document) "
                    "VALUES (:id, 'agreement', :customer, :purchase, 'retained-key', 'unknown', "
                    "now(), now() + interval '2 hours', 'financial-create:v1', '{\"request\":{\"create_date\":\"2026-10-27\"}}')"
                ),
                {"id": operation_id, "customer": CUSTOMER_ID, "purchase": PURCHASE_ID},
            )
            connection.execute(
                text(
                    "INSERT INTO billing_work_items (work_item_id, work_kind, scope_kind, scope_reference, "
                    "coalescing_key, payload_schema_version, payload_document, next_attempt_at, attempt_count, work_state) "
                    "VALUES (:id, 'external_create_recovery', 'create_operation', :operation, :operation, "
                    "'financial-recovery:v1', '{\"candidate_id\":\"456\"}', now() + interval '2 hours', 1, 'pending')"
                ),
                {"id": uuid4(), "operation": str(operation_id)},
            )
        columns = _columns(postgres_engine)
        before = _rows(postgres_engine, columns)
        command.upgrade(config, "head")
    assert _rows(postgres_engine, columns) == before
    with Session(postgres_engine) as db:
        operation = db.get(ExternalCreateOperation, operation_id)
        work = db.scalar(select(BillingWorkItem))
        assert work.active_recovery_deadline_at is None
        assert queries.financial_recovery_deadline(operation, work) == operation.unknown_recovery_deadline_at
        assert queries.overdue_financial(db, operation.unknown_recovery_deadline_at - timedelta(seconds=1), 10) == ()
        assert queries.overdue_financial(db, operation.unknown_recovery_deadline_at, 10) == ((USER_ID, PURCHASE_ID),)
