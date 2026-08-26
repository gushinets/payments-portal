"""enforce one live subscription per exact scope

Revision ID: 20260825_0008
Revises: 20260824_0006
Create Date: 2026-08-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260825_0008"
down_revision = "20260824_0006"
branch_labels = None
depends_on = None


LIVE_SUBSCRIPTION_STATUS_PREDICATE = "status IN ('trialing', 'active', 'past_due', 'paused')"


def upgrade() -> None:
    op.create_index(
        "uq_subscriptions_live_product_scope",
        "subscriptions",
        ["tenant_id", "region", "user_id", "product_id"],
        unique=True,
        postgresql_where=sa.text(
            f"scope_type = 'product' AND {LIVE_SUBSCRIPTION_STATUS_PREDICATE}"
        ),
    )
    op.create_index(
        "uq_subscriptions_live_bundle_scope",
        "subscriptions",
        ["tenant_id", "region", "user_id", "bundle_id"],
        unique=True,
        postgresql_where=sa.text(
            f"scope_type = 'bundle' AND {LIVE_SUBSCRIPTION_STATUS_PREDICATE}"
        ),
    )
    op.create_index(
        "uq_subscriptions_live_all_access_scope",
        "subscriptions",
        ["tenant_id", "region", "user_id"],
        unique=True,
        postgresql_where=sa.text(
            f"scope_type = 'all_access' AND {LIVE_SUBSCRIPTION_STATUS_PREDICATE}"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_subscriptions_live_all_access_scope", table_name="subscriptions")
    op.drop_index("uq_subscriptions_live_bundle_scope", table_name="subscriptions")
    op.drop_index("uq_subscriptions_live_product_scope", table_name="subscriptions")
