"""add entitlements and subscription events

Revision ID: 20260824_0006
Revises: 20260824_0005
Create Date: 2026-08-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260824_0006"
down_revision = "20260824_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entitlements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=sa.text("'anytoolai'")),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), sa.ForeignKey("subscriptions.id"), nullable=False),
        sa.Column("plan_id", sa.Uuid(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Uuid(), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("bundle_id", sa.Uuid(), sa.ForeignKey("bundles.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_entitlement_id", sa.Uuid(), sa.ForeignKey("entitlements.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('active', 'expired', 'revoked', 'superseded')", name="ck_entitlements_status"),
        sa.CheckConstraint("source IN ('trial', 'order')", name="ck_entitlements_source"),
        sa.CheckConstraint(
            "(scope_type = 'product' AND product_id IS NOT NULL AND bundle_id IS NULL)"
            " OR (scope_type = 'bundle' AND product_id IS NULL AND bundle_id IS NOT NULL)"
            " OR (scope_type = 'all_access' AND product_id IS NULL AND bundle_id IS NULL)",
            name="ck_entitlements_scope_references",
        ),
        sa.CheckConstraint("valid_until > valid_from", name="ck_entitlements_valid_period"),
        sa.CheckConstraint(
            "(source = 'trial' AND order_id IS NULL) OR (source = 'order' AND order_id IS NOT NULL)",
            name="ck_entitlements_source_order",
        ),
    )
    for name, columns in (
        ("ix_entitlements_tenant_id", ["tenant_id"]),
        ("ix_entitlements_region", ["region"]),
        ("ix_entitlements_user_id", ["user_id"]),
        ("ix_entitlements_subscription_id", ["subscription_id"]),
        ("ix_entitlements_plan_id", ["plan_id"]),
        ("ix_entitlements_status", ["status"]),
        ("ix_entitlements_order_id", ["order_id"]),
    ):
        op.create_index(name, "entitlements", columns)

    op.create_table(
        "subscription_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("subscription_id", sa.Uuid(), sa.ForeignKey("subscriptions.id"), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("previous_status", sa.Text(), nullable=True),
        sa.Column("next_status", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("operation_idempotency_key", sa.Text(), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("payment_id", sa.Uuid(), sa.ForeignKey("payments.id"), nullable=True),
        sa.Column("refund_id", sa.Uuid(), sa.ForeignKey("refunds.id"), nullable=True),
        sa.Column("webhook_event_id", sa.Uuid(), sa.ForeignKey("payment_webhook_events.id"), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("operation_idempotency_key", name="uq_subscription_events_operation_key"),
    )
    op.create_index("ix_subscription_events_subscription_id", "subscription_events", ["subscription_id"])
    op.create_index("ix_subscription_events_subscription_occurred_at", "subscription_events", ["subscription_id", "occurred_at"])
    op.create_index("ix_subscription_events_order_id", "subscription_events", ["order_id"])
    op.create_index("ix_subscription_events_payment_id", "subscription_events", ["payment_id"])
    op.create_index("ix_subscription_events_refund_id", "subscription_events", ["refund_id"])
    op.create_index("ix_subscription_events_webhook_event_id", "subscription_events", ["webhook_event_id"])


def downgrade() -> None:
    op.drop_index("ix_subscription_events_webhook_event_id", table_name="subscription_events")
    op.drop_index("ix_subscription_events_refund_id", table_name="subscription_events")
    op.drop_index("ix_subscription_events_payment_id", table_name="subscription_events")
    op.drop_index("ix_subscription_events_order_id", table_name="subscription_events")
    op.drop_index("ix_subscription_events_subscription_occurred_at", table_name="subscription_events")
    op.drop_index("ix_subscription_events_subscription_id", table_name="subscription_events")
    op.drop_table("subscription_events")
    op.drop_index("ix_entitlements_order_id", table_name="entitlements")
    op.drop_index("ix_entitlements_status", table_name="entitlements")
    op.drop_index("ix_entitlements_plan_id", table_name="entitlements")
    op.drop_index("ix_entitlements_subscription_id", table_name="entitlements")
    op.drop_index("ix_entitlements_user_id", table_name="entitlements")
    op.drop_index("ix_entitlements_region", table_name="entitlements")
    op.drop_index("ix_entitlements_tenant_id", table_name="entitlements")
    op.drop_table("entitlements")
