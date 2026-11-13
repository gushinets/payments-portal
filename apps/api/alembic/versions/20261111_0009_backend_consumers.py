"""Bind retained delegation state to configured backend consumers.

Revision ID: 20261111_0009
Revises: 20261110_0008
"""

from alembic import op
import sqlalchemy as sa

revision = "20261111_0009"
down_revision = "20261110_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().execute(sa.text(
        "SELECT 1 FROM kernel_session_delegations WHERE audience <> 'platform-kernel' LIMIT 1"
    )).first() is not None:
        raise RuntimeError("Unexpected historical delegation audience; explicit repair is required")
    # Existing valid audience is already platform-kernel; rename without rewriting credentials.
    op.rename_table("kernel_session_delegations", "backend_session_delegations")
    op.alter_column("backend_session_delegations", "audience", new_column_name="consumer_id")
    op.execute("ALTER TABLE backend_session_delegations RENAME CONSTRAINT ck_kernel_delegation_exchange_shape TO ck_backend_delegation_exchange_shape")
    op.execute("ALTER INDEX ix_kernel_session_delegations_auth_session_id RENAME TO ix_backend_session_delegations_auth_session_id")
    op.create_table(
        "backend_consumer_policies",
        sa.Column("consumer_id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), primary_key=True),
        sa.Column("region", sa.Text(), primary_key=True),
        sa.Column("consumer_policy_revision", sa.BigInteger(), nullable=False),
        sa.Column("policy_digest", sa.Text(), nullable=False),
        sa.CheckConstraint("consumer_policy_revision > 0", name="ck_backend_policy_positive"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM backend_consumer_policies)")):
        raise RuntimeError("Consumer policy history downgrade is unsafe; retain the monotonic policy guard")
    if bind.scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM backend_session_delegations WHERE consumer_id <> 'platform-kernel')"
    )):
        raise RuntimeError("Consumer delegation history downgrade is unsafe; the old reader is Kernel-only")
    op.drop_table("backend_consumer_policies")
    op.execute("ALTER TABLE backend_session_delegations RENAME CONSTRAINT ck_backend_delegation_exchange_shape TO ck_kernel_delegation_exchange_shape")
    op.execute("ALTER INDEX ix_backend_session_delegations_auth_session_id RENAME TO ix_kernel_session_delegations_auth_session_id")
    op.alter_column("backend_session_delegations", "consumer_id", new_column_name="audience")
    op.rename_table("backend_session_delegations", "kernel_session_delegations")
