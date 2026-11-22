"""Retain point evidence for audited subscriptions and prepared agreements."""

from alembic import op
from alembic.util.exc import CommandError
import sqlalchemy as sa

revision = "20261122_821_inventory"
down_revision = "20261117_821_merge"
branch_labels = None
depends_on = None

TABLE = "billing_state_observations"
KIND = "ck_billing_state_observations_kind"
KIND_SHAPE = "ck_billing_state_observations_kind_shape"
OLD_KINDS = (
    "'authoritative_subscription_read', 'target_product_discovery', 'primary_selection', "
    "'deterministic_access_boundary', 'allowance_activation'"
)
OLD_DISCOVERY_SCHEMAS = "'target-product-discovery:v2', 'paid-access-cause:v1'"
SHAPE = """
    (observation_kind <> 'authoritative_subscription_read' OR subscription_id IS NOT NULL)
    AND (observation_kind <> 'target_product_discovery' OR
         (user_id IS NOT NULL AND product_id IS NOT NULL AND (access_scope_id IS NOT NULL OR
          (evidence_schema_version IN ({discovery_schemas}) AND purchase_intent_id IS NOT NULL))))
    AND (observation_kind <> 'primary_selection' OR
         (access_scope_id IS NOT NULL AND basis_observation_id IS NOT NULL))
    AND (observation_kind <> 'deterministic_access_boundary' OR
         (access_scope_id IS NOT NULL AND subscription_id IS NOT NULL AND effective_at IS NOT NULL))
"""
AUDITED_READ_SHAPE = """
    AND (observation_kind <> 'audited_subscription_read' OR
         (user_id IS NOT NULL AND product_id IS NULL AND access_scope_id IS NULL AND subscription_id IS NULL
          AND purchase_intent_id IS NULL AND evidence_schema_version = 'audited-subscription-read:v1'))
"""


def _replace_observation_checks(kinds: str, shape: str) -> None:
    op.drop_constraint(KIND, TABLE, type_="check")
    op.drop_constraint(KIND_SHAPE, TABLE, type_="check")
    op.create_check_constraint(KIND, TABLE, f"observation_kind IN ({kinds})")
    op.create_check_constraint(KIND_SHAPE, TABLE, shape)


def upgrade() -> None:
    _replace_observation_checks(
        f"{OLD_KINDS}, 'audited_subscription_read'",
        SHAPE.format(discovery_schemas=f"{OLD_DISCOVERY_SCHEMAS}, 'prepared-agreement:v1'") + AUDITED_READ_SHAPE,
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM billing_state_observations
            WHERE observation_kind = 'audited_subscription_read'
               OR (observation_kind = 'target_product_discovery'
                   AND evidence_schema_version = 'prepared-agreement:v1' AND access_scope_id IS NULL)
        )
    """)
    ):
        raise CommandError("ANY-821 inventory observations require compatible readers; downgrade refused")
    _replace_observation_checks(OLD_KINDS, SHAPE.format(discovery_schemas=OLD_DISCOVERY_SCHEMAS))
