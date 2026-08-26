"""enforce plan scope references

Revision ID: 20260826_0009
Revises: 20260825_0008
Create Date: 2026-08-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260826_0009"
down_revision = "20260825_0008"
branch_labels = None
depends_on = None


PLAN_SCOPE_REFERENCES_SQL = (
    "(scope_type = 'product' AND product_id IS NOT NULL AND bundle_id IS NULL)"
    " OR (scope_type = 'bundle' AND product_id IS NULL AND bundle_id IS NOT NULL)"
    " OR (scope_type = 'all_access' AND product_id IS NULL AND bundle_id IS NULL)"
)


def upgrade() -> None:
    connection = op.get_bind()
    invalid_rows = (
        connection.execute(
            sa.text(
                "SELECT id::text, code, scope_type, product_id::text, bundle_id::text "
                "FROM plans "
                f"WHERE NOT ({PLAN_SCOPE_REFERENCES_SQL}) "
                "ORDER BY code, id "
                "LIMIT 5"
            )
        )
        .mappings()
        .all()
    )
    if invalid_rows:
        sample = ", ".join(
            (
                f"{row['code']}[{row['id']}]: scope_type={row['scope_type']}, "
                f"product_id={row['product_id']}, bundle_id={row['bundle_id']}"
            )
            for row in invalid_rows
        )
        count = connection.execute(
            sa.text(f"SELECT count(*) FROM plans WHERE NOT ({PLAN_SCOPE_REFERENCES_SQL})")
        ).scalar_one()
        raise RuntimeError(
            "Cannot add ck_plans_scope_references: existing plans contain "
            f"{count} invalid scope reference row(s). Sample: {sample}"
        )

    op.create_check_constraint(
        "ck_plans_scope_references",
        "plans",
        PLAN_SCOPE_REFERENCES_SQL,
    )


def downgrade() -> None:
    op.drop_constraint("ck_plans_scope_references", "plans", type_="check")
