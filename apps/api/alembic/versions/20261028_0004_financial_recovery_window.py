"""Separate the active financial recovery window from immutable send history.

Revision ID: 20261028_0004
Revises: 20261027_0003
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261028_0004"
down_revision = "20261027_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL on existing work preserves its original deadline. Only a newly
    # fenced, permitted financial send writes a new active deadline.
    op.add_column(
        "billing_work_items", sa.Column("active_recovery_deadline_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("billing_work_items", "active_recovery_deadline_at")
