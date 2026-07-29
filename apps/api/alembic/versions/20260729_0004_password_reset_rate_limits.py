"""password reset rate limit counters

Revision ID: 20260729_0004
Revises: 20260707_0003
Create Date: 2026-07-29
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260729_0004"
down_revision = "20260707_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "password_reset_rate_limits",
        sa.Column("rate_limit_key", sa.Text(), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_password_reset_rate_limits_expires_at",
        "password_reset_rate_limits",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_password_reset_rate_limits_expires_at",
        table_name="password_reset_rate_limits",
    )
    op.drop_table("password_reset_rate_limits")
