"""add subscriptions, entitlements, and subscription events

Revision ID: 20260826_0005
Revises: 20260729_0004
Create Date: 2026-08-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260826_0005"
down_revision = "20260729_0004"
branch_labels = None
depends_on = None


LIVE_SUBSCRIPTION_STATUS_PREDICATE = "status IN ('trialing', 'active', 'past_due', 'paused')"
PLAN_SCOPE_REFERENCES_SQL = (
    "(scope_type = 'product' AND product_id IS NOT NULL AND bundle_id IS NULL)"
    " OR (scope_type = 'bundle' AND product_id IS NULL AND bundle_id IS NOT NULL)"
    " OR (scope_type = 'all_access' AND product_id IS NULL AND bundle_id IS NULL)"
)


def _ensure_plan_scope_references_valid() -> None:
    connection = op.get_bind()
    invalid_rows = (
        connection.execute(
            sa.text(
                "SELECT id::text, code, scope_type, product_id::text, bundle_id::text "
                "FROM plans "
                f"WHERE NOT ({PLAN_SCOPE_REFERENCES_SQL}) "
                "ORDER BY code, id "
                "LIMIT 5"
            )
        )
        .mappings()
        .all()
    )
    if not invalid_rows:
        return

    sample = ", ".join(
        (
            f"{row['code']}[{row['id']}]: scope_type={row['scope_type']}, "
            f"product_id={row['product_id']}, bundle_id={row['bundle_id']}"
        )
        for row in invalid_rows
    )
    count = connection.execute(
        sa.text(f"SELECT count(*) FROM plans WHERE NOT ({PLAN_SCOPE_REFERENCES_SQL})")
    ).scalar_one()
    raise RuntimeError(
        "Cannot add ck_plans_scope_references: existing plans contain "
        f"{count} invalid scope reference row(s). Sample: {sample}"
    )


def upgrade() -> None:
    _ensure_plan_scope_references_valid()
    op.create_check_constraint(
        "ck_plans_scope_references",
        "plans",
        PLAN_SCOPE_REFERENCES_SQL,
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=sa.text("'anytoolai'")),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("plan_id", sa.Uuid(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Uuid(), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("bundle_id", sa.Uuid(), sa.ForeignKey("bundles.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'trialing'")),
        sa.Column("renewal_mode", sa.Text(), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("trial_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_account_id", sa.Uuid(), sa.ForeignKey("payment_provider_accounts.id"), nullable=True),
        sa.Column("provider_subscription_id", sa.Text(), nullable=True),
        sa.Column(
            "recurring_consent_acceptance_id",
            sa.Uuid(),
            sa.ForeignKey("document_acceptances.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('trialing', 'active', 'past_due', 'canceled', 'expired', 'refunded', 'paused')",
            name="ck_subscriptions_status",
        ),
        sa.CheckConstraint(
            "renewal_mode IN ('manual', 'automatic')",
            name="ck_subscriptions_renewal_mode",
        ),
        sa.CheckConstraint(PLAN_SCOPE_REFERENCES_SQL, name="ck_subscriptions_scope_references"),
        sa.CheckConstraint(
            "trial_start_at IS NULL OR (trial_end_at IS NOT NULL AND trial_end_at > trial_start_at)",
            name="ck_subscriptions_trial_period",
        ),
        sa.CheckConstraint(
            "current_period_end > current_period_start",
            name="ck_subscriptions_current_period",
        ),
    )
    op.create_index("ix_subscriptions_tenant_id", "subscriptions", ["tenant_id"])
    op.create_index("ix_subscriptions_region", "subscriptions", ["region"])
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    op.create_index("ix_subscriptions_user_region_status", "subscriptions", ["user_id", "region", "status"])
    op.create_index("ix_subscriptions_plan_id", "subscriptions", ["plan_id"])
    op.create_index("ix_subscriptions_status", "subscriptions", ["status"])
    op.create_index("ix_subscriptions_provider_account_id", "subscriptions", ["provider_account_id"])
    op.create_index(
        "ix_subscriptions_recurring_consent_acceptance_id",
        "subscriptions",
        ["recurring_consent_acceptance_id"],
    )
    op.create_index(
        "uq_subscriptions_provider_reference",
        "subscriptions",
        ["provider_account_id", "provider_subscription_id"],
        unique=True,
        postgresql_where=sa.text("provider_account_id IS NOT NULL AND provider_subscription_id IS NOT NULL"),
    )
    op.create_index(
        "uq_subscriptions_live_product_scope",
        "subscriptions",
        ["tenant_id", "region", "user_id", "product_id"],
        unique=True,
        postgresql_where=sa.text(f"scope_type = 'product' AND {LIVE_SUBSCRIPTION_STATUS_PREDICATE}"),
    )
    op.create_index(
        "uq_subscriptions_live_bundle_scope",
        "subscriptions",
        ["tenant_id", "region", "user_id", "bundle_id"],
        unique=True,
        postgresql_where=sa.text(f"scope_type = 'bundle' AND {LIVE_SUBSCRIPTION_STATUS_PREDICATE}"),
    )
    op.create_index(
        "uq_subscriptions_live_all_access_scope",
        "subscriptions",
        ["tenant_id", "region", "user_id"],
        unique=True,
        postgresql_where=sa.text(f"scope_type = 'all_access' AND {LIVE_SUBSCRIPTION_STATUS_PREDICATE}"),
    )

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
        sa.CheckConstraint(PLAN_SCOPE_REFERENCES_SQL, name="ck_entitlements_scope_references"),
        sa.CheckConstraint("valid_until > valid_from", name="ck_entitlements_valid_period"),
        sa.CheckConstraint(
            "(source = 'trial' AND order_id IS NULL) OR (source = 'order' AND order_id IS NOT NULL)",
            name="ck_entitlements_source_order",
        ),
    )
    op.create_index("ix_entitlements_tenant_id", "entitlements", ["tenant_id"])
    op.create_index("ix_entitlements_region", "entitlements", ["region"])
    op.create_index("ix_entitlements_user_id", "entitlements", ["user_id"])
    op.create_index("ix_entitlements_user_region_status", "entitlements", ["user_id", "region", "status"])
    op.create_index("ix_entitlements_subscription_id", "entitlements", ["subscription_id"])
    op.create_index(
        "ix_entitlements_subscription_status_validity",
        "entitlements",
        ["subscription_id", "status", "valid_from", "valid_until"],
    )
    op.create_index(
        "ix_entitlements_order_status_validity",
        "entitlements",
        ["order_id", "status", "valid_from", "valid_until"],
    )
    op.create_index("ix_entitlements_plan_id", "entitlements", ["plan_id"])
    op.create_index("ix_entitlements_status", "entitlements", ["status"])
    op.create_index("ix_entitlements_order_id", "entitlements", ["order_id"])

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
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint("operation_idempotency_key", name="uq_subscription_events_operation_key"),
    )
    op.create_index("ix_subscription_events_subscription_id", "subscription_events", ["subscription_id"])
    op.create_index(
        "ix_subscription_events_subscription_occurred_at",
        "subscription_events",
        ["subscription_id", "occurred_at"],
    )
    op.create_index("ix_subscription_events_order_id", "subscription_events", ["order_id"])
    op.create_index("ix_subscription_events_payment_id", "subscription_events", ["payment_id"])
    op.create_index("ix_subscription_events_refund_id", "subscription_events", ["refund_id"])
    op.create_index("ix_subscription_events_webhook_event_id", "subscription_events", ["webhook_event_id"])

    op.drop_index("ix_product_access_states_last_invoice_id", table_name="product_access_states")
    op.drop_index("ix_product_access_states_product_code", table_name="product_access_states")
    op.drop_index("ix_product_access_states_user_id", table_name="product_access_states")
    op.drop_table("product_access_states")


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
    op.drop_index("ix_entitlements_order_status_validity", table_name="entitlements")
    op.drop_index("ix_entitlements_subscription_status_validity", table_name="entitlements")
    op.drop_index("ix_entitlements_subscription_id", table_name="entitlements")
    op.drop_index("ix_entitlements_user_region_status", table_name="entitlements")
    op.drop_index("ix_entitlements_user_id", table_name="entitlements")
    op.drop_index("ix_entitlements_region", table_name="entitlements")
    op.drop_index("ix_entitlements_tenant_id", table_name="entitlements")
    op.drop_table("entitlements")

    op.drop_index("uq_subscriptions_live_all_access_scope", table_name="subscriptions")
    op.drop_index("uq_subscriptions_live_bundle_scope", table_name="subscriptions")
    op.drop_index("uq_subscriptions_live_product_scope", table_name="subscriptions")
    op.drop_index("uq_subscriptions_provider_reference", table_name="subscriptions")
    op.drop_index("ix_subscriptions_recurring_consent_acceptance_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_provider_account_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_status", table_name="subscriptions")
    op.drop_index("ix_subscriptions_plan_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_user_region_status", table_name="subscriptions")
    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_region", table_name="subscriptions")
    op.drop_index("ix_subscriptions_tenant_id", table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_constraint("ck_plans_scope_references", "plans", type_="check")

    op.create_table(
        "product_access_states",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
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
