"""Extend recurring work identity for coalesced access invalidation delivery."""

from alembic import op
import sqlalchemy as sa

revision = "20261110_0008"
down_revision = "20261110_0007"
branch_labels = None
depends_on = None

BASE_KINDS = "'subscription_reconciliation', 'subscription_trust_expiry', 'billing_enrollment_sweep', 'customer_inventory', 'external_create_deadline'"


def replace_index(kinds: str) -> None:
    op.drop_index("uq_billing_work_items_recurring", table_name="billing_work_items")
    op.create_index(
        "uq_billing_work_items_recurring", "billing_work_items", ["work_kind", "coalescing_key"],
        unique=True, postgresql_where=sa.text(f"work_kind IN ({kinds})"),
    )


def upgrade() -> None:
    replace_index(BASE_KINDS + ", 'access_invalidation'")


def downgrade() -> None:
    replace_index(BASE_KINDS)
