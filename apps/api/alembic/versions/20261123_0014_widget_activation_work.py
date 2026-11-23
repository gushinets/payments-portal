"""Keep one durable Widget activation window per account and subscription."""

from alembic import op
import sqlalchemy as sa

revision = "20261123_0014"
down_revision = "20261113_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_billing_work_items_widget_activation_key",
        "billing_work_items",
        "work_kind <> 'widget_activation_check' OR coalescing_key IS NOT NULL",
    )
    op.create_index(
        "uq_billing_work_items_widget_activation",
        "billing_work_items",
        ["coalescing_key"],
        unique=True,
        postgresql_where=sa.text("work_kind = 'widget_activation_check'"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM billing_work_items WHERE work_kind = 'widget_activation_check')")
    ):
        raise RuntimeError("Widget activation windows require the unique queue key; retain the current schema.")
    op.drop_index("uq_billing_work_items_widget_activation", table_name="billing_work_items")
    op.drop_constraint("ck_billing_work_items_widget_activation_key", "billing_work_items", type_="check")
