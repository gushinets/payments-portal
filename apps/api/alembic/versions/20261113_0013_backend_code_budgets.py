"""Bound new code issuance without discarding delegated expiry evidence."""

from alembic import op
import sqlalchemy as sa

revision = "20261113_0013"
down_revision = "20261113_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backend_code_issuance_budgets",
        sa.Column("tenant_id", sa.Text(), primary_key=True),
        sa.Column("region", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("consumer_id", sa.Text(), primary_key=True),
        sa.Column("issued_count", sa.Integer(), nullable=False),
        sa.Column("window_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id", "tenant_id", "region"],
            ["users.id", "users.tenant_id", "users.region"],
            name="fk_backend_code_budget_user_scope",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("issued_count > 0 AND issued_count <= 60", name="ck_backend_code_budget_count"),
    )
    op.create_index(
        "ix_backend_code_issuance_budgets_window_expires_at", "backend_code_issuance_budgets", ["window_expires_at"]
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM backend_code_issuance_budgets)")):
        raise RuntimeError("Code issuance budgets require the new writer; downgrade would reset active limits.")
    op.drop_table("backend_code_issuance_budgets")
