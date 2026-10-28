"""Durable billing worker generations and recurring coalescing identities.

Revision ID: 20261028_0004
Revises: 20261029_0003
"""
from alembic import op
import sqlalchemy as sa

revision = "20261028_0004"
down_revision = "20261029_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("billing_work_items", sa.Column("enqueue_generation", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("billing_work_items", sa.Column("last_attempt_started_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint("ck_billing_work_items_generation_nonnegative", "billing_work_items", "enqueue_generation >= 0")
    # Existing create-recovery identity and customer active-send leases are untouched.
    op.create_index("uq_billing_work_items_recurring", "billing_work_items", ["work_kind", "coalescing_key"], unique=True,
                    postgresql_where=sa.text("work_kind IN ('subscription_reconciliation', 'subscription_trust_expiry', 'billing_enrollment_sweep', 'customer_inventory', 'external_create_deadline')"))


def downgrade() -> None:
    op.drop_index("uq_billing_work_items_recurring", table_name="billing_work_items")
    op.drop_constraint("ck_billing_work_items_generation_nonnegative", "billing_work_items", type_="check")
    op.drop_column("billing_work_items", "last_attempt_started_at")
    op.drop_column("billing_work_items", "enqueue_generation")
