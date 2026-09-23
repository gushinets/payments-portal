"""remove identity and legal tenant server defaults

Revision ID: 20260923_0008
Revises: 20260921_0007
Create Date: 2026-09-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260923_0008"
down_revision = "20260921_0007"
branch_labels = None
depends_on = None


TENANT_DEFAULT_TABLES = (
    "users",
    "auth_sessions",
    "magic_link_tokens",
    "legal_entities",
    "document_versions",
    "document_acceptances",
)


def upgrade() -> None:
    for table_name in TENANT_DEFAULT_TABLES:
        op.alter_column(
            table_name,
            "tenant_id",
            existing_type=sa.Text(),
            existing_nullable=False,
            server_default=None,
        )


def downgrade() -> None:
    for table_name in TENANT_DEFAULT_TABLES:
        op.alter_column(
            table_name,
            "tenant_id",
            existing_type=sa.Text(),
            existing_nullable=False,
            server_default=sa.text("'anytoolai'"),
        )
