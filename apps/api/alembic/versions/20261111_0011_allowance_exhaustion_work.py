"""Keep exhaustion hints unique after completion without changing recurring work."""

from alembic import op
import sqlalchemy as sa

revision = "20261111_0011"
down_revision = "20261111_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_billing_work_items_recurring", table_name="billing_work_items")
    op.create_index(
        "uq_billing_work_items_recurring", "billing_work_items", ["work_kind", "coalescing_key"], unique=True,
        postgresql_where=sa.text(
            "work_kind IN ('subscription_reconciliation', 'subscription_trust_expiry', "
            "'billing_enrollment_sweep', 'customer_inventory', 'external_create_deadline', "
            "'access_invalidation', 'allowance_exhaustion')"
        ),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM billing_work_items WHERE work_kind = 'allowance_exhaustion')"
    )):
        raise RuntimeError("Exhaustion history downgrade is unsafe; retain the Step 14 reader.")
    op.drop_index("uq_billing_work_items_recurring", table_name="billing_work_items")
    op.create_index(
        "uq_billing_work_items_recurring", "billing_work_items", ["work_kind", "coalescing_key"], unique=True,
        postgresql_where=sa.text(
            "work_kind IN ('subscription_reconciliation', 'subscription_trust_expiry', "
            "'billing_enrollment_sweep', 'customer_inventory', 'external_create_deadline', 'access_invalidation')"
        ),
    )
