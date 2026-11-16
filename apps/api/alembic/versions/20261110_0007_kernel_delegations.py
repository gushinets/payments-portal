"""Hash-only Portal session delegation to Kernel.

Revision ID: 20261110_0007
Revises: 20261031_0006
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20261110_0007"
down_revision = "20261031_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kernel_session_delegations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("auth_session_id", UUID(as_uuid=True), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("code_challenge", sa.Text(), nullable=False),
        sa.Column("code_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exchanged_at", sa.DateTime(timezone=True)),
        sa.Column("token_hash", sa.Text(), unique=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["auth_session_id"], ["auth_sessions.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "(exchanged_at IS NULL AND token_hash IS NULL AND token_expires_at IS NULL) OR "
            "(exchanged_at IS NOT NULL AND token_hash IS NOT NULL AND token_expires_at IS NOT NULL)",
            name="ck_kernel_delegation_exchange_shape",
        ),
    )
    op.create_index("ix_kernel_session_delegations_auth_session_id", "kernel_session_delegations", ["auth_session_id"])


def downgrade() -> None:
    op.drop_table("kernel_session_delegations")
