"""Optional registration names; existing users retain NULL.

Revision ID: 20261025_0004
Revises: 20261021_0003
"""

from alembic import op
import sqlalchemy as sa


revision = "20261025_0004"
down_revision = "20261021_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("user_surname", "user_name", "user_patronymic"):
        op.add_column("users", sa.Column(name, sa.String(256), nullable=True))


def downgrade() -> None:
    raise RuntimeError("forward-only: retain optional user profile data")
