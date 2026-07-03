"""add invoice tracking to product access state

Revision ID: 20260703_0003
Revises: 20260703_0002
Create Date: 2026-07-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260703_0003"
down_revision = "20260703_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_access_states",
        sa.Column("last_invoice_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "product_access_states",
        sa.Column("last_transaction_id", sa.String(length=128), nullable=True),
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
    op.drop_column("product_access_states", "last_transaction_id")
    op.drop_column("product_access_states", "last_invoice_id")
