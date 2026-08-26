"""migrate legacy access state into subscriptions and entitlements

Downgrade recreates only the empty product_access_states schema. It does not
restore original product_access_states rows or fields, so operators need a
backup policy before upgrade. This migration is not data-reversible.

Revision ID: 20260824_0007
Revises: 20260824_0006
Create Date: 2026-08-24
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260824_0007"
down_revision = "20260824_0006"
branch_labels = None
depends_on = None


_LEGACY_ACTIVE = "active"
_LEGACY_PENDING = "pending"
_LEGACY_INACTIVE = "inactive"
_ALL_ACCESS_CODE = "all-access"


def _migration_error(row_id: int, reason: str) -> RuntimeError:
    return RuntimeError(f"Cannot migrate legacy access row {row_id}: {reason}")


def _resolve_scope(connection: sa.Connection, row: sa.RowMapping) -> dict[str, object]:
    product_rows = connection.execute(
        sa.text(
            "SELECT id FROM products "
            "WHERE tenant_id = :tenant_id AND code = :code"
        ),
        {"tenant_id": row["tenant_id"], "code": row["product_code"]},
    ).mappings().all()
    bundle_rows = connection.execute(
        sa.text(
            "SELECT id FROM bundles "
            "WHERE tenant_id = :tenant_id AND code = :code"
        ),
        {"tenant_id": row["tenant_id"], "code": row["product_code"]},
    ).mappings().all()

    if row["product_code"] == _ALL_ACCESS_CODE:
        if product_rows or bundle_rows:
            raise _migration_error(row["id"], "all_access_code_is_ambiguous")
        return {"scope_type": "all_access", "product_id": None, "bundle_id": None}

    if len(product_rows) + len(bundle_rows) != 1:
        raise _migration_error(row["id"], "product_code_is_unmappable_or_ambiguous")
    if product_rows:
        return {"scope_type": "product", "product_id": product_rows[0]["id"], "bundle_id": None}
    return {"scope_type": "bundle", "product_id": None, "bundle_id": bundle_rows[0]["id"]}


def _order_ids_for_invoice(connection: sa.Connection, row: sa.RowMapping) -> set[uuid.UUID]:
    if not row["last_invoice_id"]:
        return set()
    return {
        item["id"]
        for item in connection.execute(
            sa.text(
                "SELECT id FROM orders "
                "WHERE tenant_id = :tenant_id AND region = :region AND user_id = :user_id "
                "AND (provider_invoice_id = :invoice_id OR merchant_order_id = :invoice_id)"
            ),
            {
                "tenant_id": row["tenant_id"],
                "region": row["region"],
                "user_id": row["user_id"],
                "invoice_id": row["last_invoice_id"],
            },
        ).mappings()
    }


def _order_ids_for_transaction(connection: sa.Connection, row: sa.RowMapping) -> set[uuid.UUID]:
    if not row["last_transaction_id"]:
        return set()
    return {
        item["order_id"]
        for item in connection.execute(
            sa.text(
                "SELECT p.order_id FROM payments p "
                "JOIN orders o ON o.id = p.order_id "
                "WHERE o.tenant_id = :tenant_id AND o.region = :region AND o.user_id = :user_id "
                "AND p.provider_payment_id = :transaction_id"
            ),
            {
                "tenant_id": row["tenant_id"],
                "region": row["region"],
                "user_id": row["user_id"],
                "transaction_id": row["last_transaction_id"],
            },
        ).mappings()
    }


def _resolve_order_and_payment(
    connection: sa.Connection, row: sa.RowMapping
) -> tuple[sa.RowMapping, uuid.UUID | None]:
    invoice_order_ids = _order_ids_for_invoice(connection, row)
    transaction_order_ids = _order_ids_for_transaction(connection, row)
    if row["last_invoice_id"] and row["last_transaction_id"]:
        order_ids = invoice_order_ids & transaction_order_ids
    else:
        order_ids = invoice_order_ids or transaction_order_ids
    if len(order_ids) != 1:
        raise _migration_error(row["id"], "order_reference_is_unmappable_or_ambiguous")

    order = connection.execute(
        sa.text(
            "SELECT id, tenant_id, region, user_id, plan_id FROM orders WHERE id = :order_id"
        ),
        {"order_id": next(iter(order_ids))},
    ).mappings().one()

    payment_id = None
    if row["last_transaction_id"]:
        payment_rows = connection.execute(
            sa.text(
                "SELECT p.id FROM payments p "
                "WHERE p.order_id = :order_id AND p.provider_payment_id = :transaction_id"
            ),
            {"order_id": order["id"], "transaction_id": row["last_transaction_id"]},
        ).mappings().all()
        if len(payment_rows) != 1:
            raise _migration_error(row["id"], "transaction_reference_is_unmappable_or_ambiguous")
        payment_id = payment_rows[0]["id"]
    return order, payment_id


def _resolve_plan(
    connection: sa.Connection,
    row: sa.RowMapping,
    order: sa.RowMapping,
) -> sa.RowMapping:
    item_plan_rows = connection.execute(
        sa.text(
            "SELECT DISTINCT plan_id FROM order_items "
            "WHERE order_id = :order_id AND plan_id IS NOT NULL"
        ),
        {"order_id": order["id"]},
    ).mappings().all()
    item_plan_ids = {item["plan_id"] for item in item_plan_rows}
    if order["plan_id"] is not None and any(plan_id != order["plan_id"] for plan_id in item_plan_ids):
        raise _migration_error(row["id"], "order_plan_is_ambiguous")

    plan_id = order["plan_id"]
    if plan_id is None and len(item_plan_ids) == 1:
        plan_id = next(iter(item_plan_ids))
    if plan_id is None and len(item_plan_ids) > 1:
        raise _migration_error(row["id"], "order_plan_is_ambiguous")

    if plan_id is not None:
        plan = connection.execute(
            sa.text(
                "SELECT id, tenant_id, region, code, scope_type, product_id, bundle_id "
                "FROM plans WHERE id = :plan_id"
            ),
            {"plan_id": plan_id},
        ).mappings().one_or_none()
        if plan is None:
            raise _migration_error(row["id"], "plan_reference_is_unmappable")
        if row["plan_code"] is not None and plan["code"] != row["plan_code"]:
            raise _migration_error(row["id"], "plan_code_does_not_match_order")
    else:
        if row["plan_code"] is None:
            raise _migration_error(row["id"], "plan_reference_is_missing")
        plans = connection.execute(
            sa.text(
                "SELECT id, tenant_id, region, code, scope_type, product_id, bundle_id "
                "FROM plans WHERE tenant_id = :tenant_id AND region = :region AND code = :code"
            ),
            {
                "tenant_id": row["tenant_id"],
                "region": row["region"],
                "code": row["plan_code"],
            },
        ).mappings().all()
        if len(plans) != 1:
            raise _migration_error(row["id"], "plan_code_is_unmappable_or_ambiguous")
        plan = plans[0]

    if plan["tenant_id"] != row["tenant_id"] or plan["region"] != row["region"]:
        raise _migration_error(row["id"], "plan_scope_does_not_match_user")
    return plan


def _validate_plan_scope(row: sa.RowMapping, scope: dict[str, object], plan: sa.RowMapping) -> None:
    if (
        plan["scope_type"] != scope["scope_type"]
        or plan["product_id"] != scope["product_id"]
        or plan["bundle_id"] != scope["bundle_id"]
    ):
        raise _migration_error(row["id"], "plan_scope_does_not_match_product")


def _prepare_rows(connection: sa.Connection) -> list[dict[str, object]]:
    migration_now = connection.execute(sa.text("SELECT CURRENT_TIMESTAMP")).scalar_one()
    rows = connection.execute(
        sa.text(
            "SELECT pas.id, pas.user_id, pas.product_code, pas.plan_code, "
            "pas.last_invoice_id, pas.last_transaction_id, pas.status, "
            "pas.starts_at, pas.expires_at, u.tenant_id, u.region "
            "FROM product_access_states pas JOIN users u ON u.id = pas.user_id "
            "ORDER BY pas.id"
        )
    ).mappings()
    prepared = []
    for row in rows:
        if row["status"] in {_LEGACY_PENDING, _LEGACY_INACTIVE}:
            continue
        if row["status"] != _LEGACY_ACTIVE:
            raise _migration_error(row["id"], "unknown_legacy_status")
        if row["starts_at"] is None or row["expires_at"] is None:
            raise _migration_error(row["id"], "access_period_is_incomplete")
        if row["expires_at"] <= row["starts_at"] or row["starts_at"] > migration_now:
            raise _migration_error(row["id"], "access_period_is_invalid")

        scope = _resolve_scope(connection, row)
        order, payment_id = _resolve_order_and_payment(connection, row)
        plan = _resolve_plan(connection, row, order)
        _validate_plan_scope(row, scope, plan)
        status = "expired" if row["expires_at"] <= migration_now else "active"
        prepared.append(
            {
                "legacy_id": row["id"],
                "tenant_id": row["tenant_id"],
                "region": row["region"],
                "user_id": row["user_id"],
                "plan_id": plan["id"],
                "scope_type": scope["scope_type"],
                "product_id": scope["product_id"],
                "bundle_id": scope["bundle_id"],
                "status": status,
                "current_period_start": row["starts_at"],
                "current_period_end": row["expires_at"],
                "order_id": order["id"],
                "payment_id": payment_id,
            }
        )
    return prepared


def _backfill(connection: sa.Connection, rows: list[dict[str, object]]) -> None:
    json_type = postgresql.JSONB(astext_type=sa.Text())
    subscriptions = sa.table(
        "subscriptions",
        sa.column("id", sa.Uuid()),
        sa.column("tenant_id", sa.Text()),
        sa.column("region", sa.Text()),
        sa.column("user_id", sa.Uuid()),
        sa.column("plan_id", sa.Uuid()),
        sa.column("scope_type", sa.Text()),
        sa.column("product_id", sa.Uuid()),
        sa.column("bundle_id", sa.Uuid()),
        sa.column("status", sa.Text()),
        sa.column("renewal_mode", sa.Text()),
        sa.column("current_period_start", sa.DateTime(timezone=True)),
        sa.column("current_period_end", sa.DateTime(timezone=True)),
    )
    entitlements = sa.table(
        "entitlements",
        sa.column("id", sa.Uuid()),
        sa.column("tenant_id", sa.Text()),
        sa.column("region", sa.Text()),
        sa.column("user_id", sa.Uuid()),
        sa.column("subscription_id", sa.Uuid()),
        sa.column("plan_id", sa.Uuid()),
        sa.column("scope_type", sa.Text()),
        sa.column("product_id", sa.Uuid()),
        sa.column("bundle_id", sa.Uuid()),
        sa.column("status", sa.Text()),
        sa.column("valid_from", sa.DateTime(timezone=True)),
        sa.column("valid_until", sa.DateTime(timezone=True)),
        sa.column("source", sa.Text()),
        sa.column("order_id", sa.Uuid()),
        sa.column("expired_at", sa.DateTime(timezone=True)),
    )
    events = sa.table(
        "subscription_events",
        sa.column("id", sa.Uuid()),
        sa.column("subscription_id", sa.Uuid()),
        sa.column("event_type", sa.Text()),
        sa.column("next_status", sa.Text()),
        sa.column("operation_idempotency_key", sa.Text()),
        sa.column("order_id", sa.Uuid()),
        sa.column("payment_id", sa.Uuid()),
        sa.column("metadata", json_type),
    )

    for row in rows:
        subscription_id = uuid.uuid4()
        entitlement_id = uuid.uuid4()
        connection.execute(
            subscriptions.insert().values(
                id=subscription_id,
                tenant_id=row["tenant_id"],
                region=row["region"],
                user_id=row["user_id"],
                plan_id=row["plan_id"],
                scope_type=row["scope_type"],
                product_id=row["product_id"],
                bundle_id=row["bundle_id"],
                status=row["status"],
                renewal_mode="manual",
                current_period_start=row["current_period_start"],
                current_period_end=row["current_period_end"],
            )
        )
        connection.execute(
            entitlements.insert().values(
                id=entitlement_id,
                tenant_id=row["tenant_id"],
                region=row["region"],
                user_id=row["user_id"],
                subscription_id=subscription_id,
                plan_id=row["plan_id"],
                scope_type=row["scope_type"],
                product_id=row["product_id"],
                bundle_id=row["bundle_id"],
                status=row["status"],
                valid_from=row["current_period_start"],
                valid_until=row["current_period_end"],
                source="order",
                order_id=row["order_id"],
                expired_at=row["current_period_end"] if row["status"] == "expired" else None,
            )
        )
        connection.execute(
            events.insert().values(
                id=uuid.uuid4(),
                subscription_id=subscription_id,
                event_type="legacy_access_migrated",
                next_status=row["status"],
                operation_idempotency_key=f"legacy_access_migrated:{row['legacy_id']}",
                order_id=row["order_id"],
                payment_id=row["payment_id"],
                metadata={"legacy_access_state_id": row["legacy_id"]},
            )
        )


def _create_legacy_table() -> None:
    uuid_type = sa.Uuid()
    op.create_table(
        "product_access_states",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("product_code", sa.String(length=64), nullable=False),
        sa.Column("plan_code", sa.String(length=128), nullable=True),
        sa.Column("last_invoice_id", sa.String(length=128), nullable=True),
        sa.Column("last_transaction_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'inactive'")),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "product_code", name="uq_user_product"),
    )
    op.create_index("ix_product_access_states_user_id", "product_access_states", ["user_id"])
    op.create_index("ix_product_access_states_product_code", "product_access_states", ["product_code"])
    op.create_index("ix_product_access_states_last_invoice_id", "product_access_states", ["last_invoice_id"])


def upgrade() -> None:
    connection = op.get_bind()
    rows = _prepare_rows(connection)
    _backfill(connection, rows)
    op.drop_table("product_access_states")


def downgrade() -> None:
    _create_legacy_table()
