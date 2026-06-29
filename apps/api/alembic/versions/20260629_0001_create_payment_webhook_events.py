"""create payment webhook events table

Revision ID: 20260629_0001
Revises:
Create Date: 2026-06-29
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260629_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_webhook_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "provider",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'cloudpayments'"),
        ),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=True),
        sa.Column("invoice_id", sa.Text(), nullable=True),
        sa.Column("transaction_id", sa.Text(), nullable=True),
        sa.Column("account_id", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'received'"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_payment_webhook_events_received_at",
        "payment_webhook_events",
        ["received_at"],
    )
    op.create_index(
        "ix_payment_webhook_events_endpoint",
        "payment_webhook_events",
        ["endpoint"],
    )
    op.create_index(
        "ix_payment_webhook_events_transaction_id",
        "payment_webhook_events",
        ["transaction_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payment_webhook_events_transaction_id",
        table_name="payment_webhook_events",
    )
    op.drop_index("ix_payment_webhook_events_endpoint", table_name="payment_webhook_events")
    op.drop_index(
        "ix_payment_webhook_events_received_at",
        table_name="payment_webhook_events",
    )
    op.drop_table("payment_webhook_events")
