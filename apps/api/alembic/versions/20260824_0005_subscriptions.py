"""add subscription persistence model

Revision ID: 20260824_0005
Revises: 20260729_0004
Create Date: 2026-08-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260824_0005"
down_revision = "20260729_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
        sa.Column(
            "provider_account_id",
            sa.Uuid(),
            sa.ForeignKey("payment_provider_accounts.id"),
            nullable=True,
        ),
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
        sa.CheckConstraint(
            "(scope_type = 'product' AND product_id IS NOT NULL AND bundle_id IS NULL)"
            " OR (scope_type = 'bundle' AND product_id IS NULL AND bundle_id IS NOT NULL)"
            " OR (scope_type = 'all_access' AND product_id IS NULL AND bundle_id IS NULL)",
            name="ck_subscriptions_scope_references",
        ),
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
    op.create_index(
        "ix_subscriptions_user_region_status",
        "subscriptions",
        ["user_id", "region", "status"],
    )
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
        postgresql_where=sa.text(
            "provider_account_id IS NOT NULL AND provider_subscription_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
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
