"""Allow an audited terminal outcome with retained external objects."""

import sqlalchemy as sa
from alembic import op
from alembic.util.exc import CommandError

revision = "20261123_0821"
down_revision = "20261123_0014"
branch_labels = None
depends_on = None

OLD_STATES = (
    "'created', 'preparing', 'awaiting_external_result', 'linked', "
    "'resolved_no_external_effect', 'failed_before_external_effect', 'manual_review'"
)


def upgrade() -> None:
    op.drop_constraint("ck_purchase_intents_state", "purchase_intents", type_="check")
    op.create_check_constraint(
        "ck_purchase_intents_state", "purchase_intents", f"state IN ({OLD_STATES}, 'resolved_external_terminal')"
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("""
            SELECT EXISTS (SELECT 1 FROM purchase_intents WHERE state = 'resolved_external_terminal')
                OR EXISTS (
                    SELECT 1 FROM manual_review_cases
                    WHERE scope_kind = 'purchase_intent'
                      AND reason_code = 'purchase_late_external_object'
                      AND (
                        case_state = 'open'
                        OR (
                            case_state = 'resolved'
                            AND resolution_schema_version = 'purchase-late-object-closure:v1'
                            AND resolution_document->'request'->'evidence'->>'outcome' = 'external_terminal'
                            AND resolution_document->'request'->'evidence'->>'external_object_id' IS NOT NULL
                        )
                      )
                )
        """)
    ):
        raise CommandError(
            "ANY-821 downgrade refused because terminal history or an open late-object case requires compatible readers"
        )
    op.drop_constraint("ck_purchase_intents_state", "purchase_intents", type_="check")
    op.create_check_constraint("ck_purchase_intents_state", "purchase_intents", f"state IN ({OLD_STATES})")
