"""Add an honest terminal outcome for retained external objects."""

from alembic import op
from alembic.util.exc import CommandError
import sqlalchemy as sa

revision = "20261116_821"
down_revision = "20261031_0006"
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
        sa.text("SELECT EXISTS (SELECT 1 FROM purchase_intents WHERE state = 'resolved_external_terminal')")
    ):
        raise CommandError("ANY-821 terminal purchase history requires compatible readers; downgrade refused")
    op.drop_constraint("ck_purchase_intents_state", "purchase_intents", type_="check")
    op.create_check_constraint("ck_purchase_intents_state", "purchase_intents", f"state IN ({OLD_STATES})")
