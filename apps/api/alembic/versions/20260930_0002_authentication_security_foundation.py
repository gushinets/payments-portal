"""Add the authentication security persistence foundation.

Revision ID: 20260930_0002
Revises: 20260924_0001
Create Date: 2026-09-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260930_0002"
down_revision = "20260924_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "authentication_rate_limits",
        sa.Column("rate_limit_key", sa.Text(), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_authentication_rate_limits_expires_at",
        "authentication_rate_limits",
        ["expires_at"],
    )

    op.execute(
        sa.text(
            """
            UPDATE auth_sessions
            SET revoked_at = CURRENT_TIMESTAMP
            WHERE revoked_at IS NULL
              AND EXISTS (
                  SELECT 1
                  FROM users
                  WHERE users.id = auth_sessions.user_id
                    AND users.tenant_id = auth_sessions.tenant_id
                    AND users.region = auth_sessions.region
                    AND users.email_verified_at IS NOT NULL
              )
            """
        )
    )
    op.execute(sa.text("UPDATE users SET email_verified_at = NULL WHERE email_verified_at IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_authentication_rate_limits_expires_at", table_name="authentication_rate_limits")
    op.drop_table("authentication_rate_limits")
