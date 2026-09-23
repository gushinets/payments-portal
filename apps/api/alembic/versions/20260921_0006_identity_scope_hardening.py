"""harden identity, session, and password-reset scope

Revision ID: 20260921_0006
Revises: 20260826_0005
Create Date: 2026-09-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260921_0006"
down_revision = "20260826_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_users_id_tenant_region",
        "users",
        ["id", "tenant_id", "region"],
    )

    op.drop_constraint("auth_sessions_user_id_fkey", "auth_sessions", type_="foreignkey")
    op.create_foreign_key(
        "fk_auth_sessions_user_scope",
        "auth_sessions",
        "users",
        ["user_id", "tenant_id", "region"],
        ["id", "tenant_id", "region"],
        ondelete="RESTRICT",
    )

    op.add_column("magic_link_tokens", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_magic_link_tokens_user_id",
        "magic_link_tokens",
        ["user_id"],
    )
    op.execute(
        sa.text(
            """
            WITH unique_user_matches AS (
                SELECT
                    tenant_id,
                    region,
                    email_normalized,
                    min(id::text)::uuid AS user_id
                FROM users
                GROUP BY tenant_id, region, email_normalized
                HAVING count(*) = 1
            )
            UPDATE magic_link_tokens AS token
            SET user_id = matched.user_id
            FROM unique_user_matches AS matched
            WHERE token.tenant_id = matched.tenant_id
              AND token.region = matched.region
              AND token.email_normalized = matched.email_normalized
            """
        )
    )
    op.create_foreign_key(
        "fk_magic_link_tokens_user_scope",
        "magic_link_tokens",
        "users",
        ["user_id", "tenant_id", "region"],
        ["id", "tenant_id", "region"],
        ondelete="RESTRICT",
    )
    op.drop_column("magic_link_tokens", "entrypoint_session_id")


def downgrade() -> None:
    op.add_column(
        "magic_link_tokens",
        sa.Column("entrypoint_session_id", sa.Uuid(), nullable=True),
    )
    op.drop_constraint(
        "fk_magic_link_tokens_user_scope",
        "magic_link_tokens",
        type_="foreignkey",
    )
    op.drop_index("ix_magic_link_tokens_user_id", table_name="magic_link_tokens")
    op.drop_column("magic_link_tokens", "user_id")

    op.drop_constraint(
        "fk_auth_sessions_user_scope",
        "auth_sessions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "auth_sessions_user_id_fkey",
        "auth_sessions",
        "users",
        ["user_id"],
        ["id"],
    )
    op.drop_constraint("uq_users_id_tenant_region", "users", type_="unique")
