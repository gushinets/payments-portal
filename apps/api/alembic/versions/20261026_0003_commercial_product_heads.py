"""Add current product pointers without promoting any historical evidence.

Revision ID: 20261026_0003
Revises: 20261001_0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261026_0003"
down_revision = "20261001_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commercial_product_heads",
        sa.Column("external_billing_account_id", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("mapping_revision_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("external_billing_account_id", "product_id"),
        sa.ForeignKeyConstraint(
            ["mapping_revision_id", "external_billing_account_id"],
            [
                "commercial_mapping_revisions.mapping_revision_id",
                "commercial_mapping_revisions.external_billing_account_id",
            ],
            name="fk_commercial_product_heads_mapping_scope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("revision_number > 0", name="ck_commercial_product_heads_revision_positive"),
        sa.CheckConstraint("trim(product_id) <> ''", name="ck_commercial_product_heads_product_nonempty"),
    )
    # Deliberately no backfill. Legacy multiple offer heads are ambiguous;
    # synthetic v1 evidence is never upgraded into a live link by migration.


def downgrade() -> None:
    op.drop_table("commercial_product_heads")
