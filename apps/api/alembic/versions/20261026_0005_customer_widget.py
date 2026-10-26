"""Optional FIO and permanent customer-create identity/fence.

Revision ID: 20261026_0005
Revises: 20261026_0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261026_0005"
down_revision = "20261026_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("first_name", "surname", "patronymic"):
        op.add_column("users", sa.Column(name, sa.String(100), nullable=True))
    # No guessed name/origin, provider calls, deletion or legacy promotion.
    op.add_column("external_billing_customers", sa.Column("provider_origin", sa.Text(), nullable=True))
    op.add_column("external_create_operations", sa.Column("send_fence", sa.Uuid(), nullable=True))
    op.create_unique_constraint(
        "uq_billing_customers_provider",
        "external_billing_customers",
        ["external_billing_account_id", "provider_customer_id"],
    )
    op.create_index(
        "uq_external_create_operations_customer_identity",
        "external_create_operations",
        ["customer_id"],
        unique=True,
        postgresql_where=sa.text("operation_kind = 'customer'"),
    )
    op.create_index(
        "uq_billing_work_items_create_recovery",
        "billing_work_items",
        ["coalescing_key"],
        unique=True,
        postgresql_where=sa.text("work_kind = 'external_create_recovery'"),
    )


def downgrade() -> None:
    op.drop_index("uq_billing_work_items_create_recovery", table_name="billing_work_items")
    op.drop_index("uq_external_create_operations_customer_identity", table_name="external_create_operations")
    op.drop_constraint("uq_billing_customers_provider", "external_billing_customers", type_="unique")
    op.drop_column("external_create_operations", "send_fence")
    op.drop_column("external_billing_customers", "provider_origin")
    for name in ("patronymic", "surname", "first_name"):
        op.drop_column("users", name)
