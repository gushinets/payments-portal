"""Retain proven provider origins without rewriting immutable mapping scopes.

Revision ID: 20261026_0004
Revises: 20261026_0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261026_0004"
down_revision = "20261026_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("commercial_product_heads", sa.Column("provider_origin", sa.Text(), nullable=True))
    op.create_unique_constraint(
        "uq_commercial_product_heads_origin_product", "commercial_product_heads", ["provider_origin", "product_id"]
    )
    # No guessed origin, scope rewrite, synthetic promotion or automatic adoption.


def downgrade() -> None:
    op.drop_constraint("uq_commercial_product_heads_origin_product", "commercial_product_heads", type_="unique")
    op.drop_column("commercial_product_heads", "provider_origin")
