"""entrypoints, checkout, orders, payments, refunds, and webhook inbox

Revision ID: 20260707_0003
Revises: 20260707_0002
Create Date: 2026-07-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260707_0003"
down_revision = "20260707_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = sa.Uuid()
    ip_type = postgresql.INET()

    op.create_table(
        "entrypoint_sessions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=sa.text("'anytoolai'")),
        sa.Column("route_region", sa.Text(), nullable=False),
        sa.Column("resolved_region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("ip_country", sa.String(length=2), nullable=True),
        sa.Column("declared_country", sa.String(length=2), nullable=True),
        sa.Column("browser_language", sa.Text(), nullable=True),
        sa.Column("region_mismatch_status", sa.Text(), nullable=False, server_default=sa.text("'none'")),
        sa.Column("entrypoint_type", sa.Text(), nullable=False),
        sa.Column("entrypoint_value", sa.Text(), nullable=False),
        sa.Column("product_id", uuid_type, sa.ForeignKey("products.id"), nullable=True),
        sa.Column("bundle_id", uuid_type, sa.ForeignKey("bundles.id"), nullable=True),
        sa.Column("frontend_id", sa.Text(), nullable=True),
        sa.Column("platform_guest_id", sa.Text(), nullable=True),
        sa.Column("platform_user_id", sa.Text(), nullable=True),
        sa.Column("scenario_session_id", sa.Text(), nullable=True),
        sa.Column("artifact_id", sa.Text(), nullable=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("acquisition_source", sa.Text(), nullable=True),
        sa.Column("ip", ip_type, nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_entrypoint_sessions_resolved_region_created_at", "entrypoint_sessions", ["resolved_region", "created_at"])
    op.create_index("ix_entrypoint_sessions_user_id_created_at", "entrypoint_sessions", ["user_id", "created_at"])
    op.create_index("ix_entrypoint_sessions_type_value", "entrypoint_sessions", ["entrypoint_type", "entrypoint_value"])
    op.create_index("ix_entrypoint_sessions_frontend_id_created_at", "entrypoint_sessions", ["frontend_id", "created_at"])
    op.create_index("ix_entrypoint_sessions_scenario_session_id", "entrypoint_sessions", ["scenario_session_id"])

    op.create_table(
        "checkout_sessions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=sa.text("'anytoolai'")),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("entrypoint_session_id", uuid_type, sa.ForeignKey("entrypoint_sessions.id"), nullable=True),
        sa.Column("plan_id", uuid_type, sa.ForeignKey("plans.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'created'")),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_checkout_sessions_user_id_created_at", "checkout_sessions", ["user_id", "created_at"])
    op.create_index("ix_checkout_sessions_status_expires_at", "checkout_sessions", ["status", "expires_at"])

    op.create_table(
        "orders",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=sa.text("'anytoolai'")),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("order_number", sa.Text(), nullable=False),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("checkout_session_id", uuid_type, sa.ForeignKey("checkout_sessions.id"), nullable=True),
        sa.Column("entrypoint_session_id", uuid_type, sa.ForeignKey("entrypoint_sessions.id"), nullable=True),
        sa.Column("plan_id", uuid_type, sa.ForeignKey("plans.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'created'")),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("tax_amount_minor", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("discount_amount_minor", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_account_id", uuid_type, sa.ForeignKey("payment_provider_accounts.id"), nullable=False),
        sa.Column("merchant_order_id", sa.Text(), nullable=False),
        sa.Column("provider_invoice_id", sa.Text(), nullable=True),
        sa.Column("billing_country", sa.String(length=2), nullable=True),
        sa.Column("region_mismatch_status", sa.Text(), nullable=False, server_default=sa.text("'none'")),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "region", "order_number", name="uq_orders_tenant_region_order_number"),
        sa.UniqueConstraint("provider_account_id", "merchant_order_id", name="uq_orders_provider_account_merchant_order"),
    )
    op.create_index("ix_orders_user_id_created_at", "orders", ["user_id", "created_at"])
    op.create_index("ix_orders_region_status_created_at", "orders", ["region", "status", "created_at"])
    op.create_index("ix_orders_provider_invoice_id", "orders", ["provider", "provider_invoice_id"])
    op.create_index("ix_orders_entrypoint_session_id", "orders", ["entrypoint_session_id"])

    op.create_table(
        "order_items",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("order_id", uuid_type, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("item_type", sa.Text(), nullable=False),
        sa.Column("product_id", uuid_type, sa.ForeignKey("products.id"), nullable=True),
        sa.Column("bundle_id", uuid_type, sa.ForeignKey("bundles.id"), nullable=True),
        sa.Column("plan_id", uuid_type, sa.ForeignKey("plans.id"), nullable=True),
        sa.Column("product_code_snapshot", sa.Text(), nullable=True),
        sa.Column("plan_code_snapshot", sa.Text(), nullable=True),
        sa.Column("title_snapshot", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("list_amount_minor", sa.Integer(), nullable=False),
        sa.Column("discount_amount_minor", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("unit_amount_minor", sa.Integer(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("trial_days_snapshot", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("pricing_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_index("ix_order_items_product_id", "order_items", ["product_id"])
    op.create_index("ix_order_items_bundle_id", "order_items", ["bundle_id"])

    op.create_table(
        "payments",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=sa.text("'anytoolai'")),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("order_id", uuid_type, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("provider_account_id", uuid_type, sa.ForeignKey("payment_provider_accounts.id"), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_payment_id", sa.Text(), nullable=True),
        sa.Column("provider_invoice_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'created'")),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("payment_method_type", sa.Text(), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_amount_minor", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("failure_message_safe", sa.Text(), nullable=True),
        sa.Column("raw_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "uq_payments_provider_account_payment_id",
        "payments",
        ["provider_account_id", "provider_payment_id"],
        unique=True,
        postgresql_where=sa.text("provider_payment_id IS NOT NULL"),
    )
    op.create_index("ix_payments_order_id", "payments", ["order_id"])
    op.create_index("ix_payments_region_status_created_at", "payments", ["region", "status", "created_at"])

    op.create_table(
        "refunds",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=sa.text("'anytoolai'")),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("order_id", uuid_type, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("payment_id", uuid_type, sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("provider_account_id", uuid_type, sa.ForeignKey("payment_provider_accounts.id"), nullable=False),
        sa.Column("provider_refund_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'requested'")),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_refunds_order_id", "refunds", ["order_id"])
    op.create_index("ix_refunds_payment_id", "refunds", ["payment_id"])
    op.create_index(
        "uq_refunds_provider_account_refund_id",
        "refunds",
        ["provider_account_id", "provider_refund_id"],
        unique=True,
        postgresql_where=sa.text("provider_refund_id IS NOT NULL"),
    )

    op.create_table(
        "payment_webhook_events",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=sa.text("'anytoolai'")),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("provider_account_id", uuid_type, sa.ForeignKey("payment_provider_accounts.id"), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False, server_default=sa.text("'cloudpayments'")),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=True),
        sa.Column("provider_event_id", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("invoice_id", sa.Text(), nullable=True),
        sa.Column("transaction_id", sa.Text(), nullable=True),
        sa.Column("account_id", sa.Text(), nullable=True),
        sa.Column("order_id", uuid_type, sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("payment_id", uuid_type, sa.ForeignKey("payments.id"), nullable=True),
        sa.Column("amount_minor", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'received'")),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_payment_webhook_events_region_provider_received_at", "payment_webhook_events", ["region", "provider", "received_at"])
    op.create_index("ix_payment_webhook_events_provider_endpoint_event_type", "payment_webhook_events", ["provider", "endpoint", "event_type"])
    op.create_index("ix_payment_webhook_events_provider_event_id", "payment_webhook_events", ["provider_account_id", "provider_event_id"])
    op.create_index("ix_payment_webhook_events_order_id", "payment_webhook_events", ["order_id"])
    op.create_index("ix_payment_webhook_events_payment_id", "payment_webhook_events", ["payment_id"])
    op.create_index("ix_payment_webhook_events_idempotency_lookup", "payment_webhook_events", ["provider_account_id", "idempotency_key"])

    op.create_table(
        "product_access_states",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("product_code", sa.String(length=64), nullable=False),
        sa.Column("plan_code", sa.String(length=128), nullable=True),
        sa.Column("last_invoice_id", sa.String(length=128), nullable=True),
        sa.Column("last_transaction_id", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'inactive'"),
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", "product_code", name="uq_user_product"),
    )
    op.create_index(
        "ix_product_access_states_user_id",
        "product_access_states",
        ["user_id"],
    )
    op.create_index(
        "ix_product_access_states_product_code",
        "product_access_states",
        ["product_code"],
    )
    op.create_index(
        "ix_product_access_states_last_invoice_id",
        "product_access_states",
        ["last_invoice_id"],
    )




def downgrade() -> None:
    op.drop_index(
        "ix_product_access_states_last_invoice_id",
        table_name="product_access_states",
    )
    op.drop_index("ix_product_access_states_product_code", table_name="product_access_states")
    op.drop_index("ix_product_access_states_user_id", table_name="product_access_states")
    op.drop_table("product_access_states")

    op.drop_index("ix_payment_webhook_events_idempotency_lookup", table_name="payment_webhook_events")
    op.drop_index("ix_payment_webhook_events_payment_id", table_name="payment_webhook_events")
    op.drop_index("ix_payment_webhook_events_order_id", table_name="payment_webhook_events")
    op.drop_index("ix_payment_webhook_events_provider_event_id", table_name="payment_webhook_events")
    op.drop_index("ix_payment_webhook_events_provider_endpoint_event_type", table_name="payment_webhook_events")
    op.drop_index("ix_payment_webhook_events_region_provider_received_at", table_name="payment_webhook_events")
    op.drop_table("payment_webhook_events")

    op.drop_index("uq_refunds_provider_account_refund_id", table_name="refunds")
    op.drop_index("ix_refunds_payment_id", table_name="refunds")
    op.drop_index("ix_refunds_order_id", table_name="refunds")
    op.drop_table("refunds")

    op.drop_index("ix_payments_region_status_created_at", table_name="payments")
    op.drop_index("ix_payments_order_id", table_name="payments")
    op.drop_index("uq_payments_provider_account_payment_id", table_name="payments")
    op.drop_table("payments")

    op.drop_index("ix_order_items_bundle_id", table_name="order_items")
    op.drop_index("ix_order_items_product_id", table_name="order_items")
    op.drop_index("ix_order_items_order_id", table_name="order_items")
    op.drop_table("order_items")

    op.drop_index("ix_orders_entrypoint_session_id", table_name="orders")
    op.drop_index("ix_orders_provider_invoice_id", table_name="orders")
    op.drop_index("ix_orders_region_status_created_at", table_name="orders")
    op.drop_index("ix_orders_user_id_created_at", table_name="orders")
    op.drop_table("orders")

    op.drop_index("ix_checkout_sessions_status_expires_at", table_name="checkout_sessions")
    op.drop_index("ix_checkout_sessions_user_id_created_at", table_name="checkout_sessions")
    op.drop_table("checkout_sessions")

    op.drop_index("ix_entrypoint_sessions_scenario_session_id", table_name="entrypoint_sessions")
    op.drop_index("ix_entrypoint_sessions_frontend_id_created_at", table_name="entrypoint_sessions")
    op.drop_index("ix_entrypoint_sessions_type_value", table_name="entrypoint_sessions")
    op.drop_index("ix_entrypoint_sessions_user_id_created_at", table_name="entrypoint_sessions")
    op.drop_index("ix_entrypoint_sessions_resolved_region_created_at", table_name="entrypoint_sessions")
    op.drop_table("entrypoint_sessions")

