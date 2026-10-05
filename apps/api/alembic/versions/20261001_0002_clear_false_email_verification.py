"""Clear predecessor email verification timestamps.

Revision ID: 20261001_0002
Revises: 20260924_0001
Create Date: 2026-10-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20261001_0002"
down_revision = "20260924_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE users SET email_verified_at = NULL WHERE email_verified_at IS NOT NULL"))


def downgrade() -> None:
    # Predecessor timestamps were registration times, not mailbox evidence, so
    # no trustworthy verification value can be reconstructed on downgrade.
    pass
