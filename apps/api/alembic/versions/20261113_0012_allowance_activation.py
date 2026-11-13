"""Retain exact allowance activation facts; existing evidence stays immutable."""

from alembic import op
import sqlalchemy as sa

revision = "20261113_0012"
down_revision = "20261111_0011"
branch_labels = None
depends_on = None

PREVIOUS_KINDS = "'authoritative_subscription_read', 'target_product_discovery', 'primary_selection', 'deterministic_access_boundary'"


def upgrade() -> None:
    op.drop_constraint("ck_billing_state_observations_kind", "billing_state_observations")
    op.create_check_constraint(
        "ck_billing_state_observations_kind",
        "billing_state_observations",
        f"observation_kind IN ({PREVIOUS_KINDS}, 'allowance_activation')",
    )
    op.create_check_constraint(
        "ck_billing_observations_activation_shape",
        "billing_state_observations",
        "observation_kind <> 'allowance_activation' OR "
        "(access_scope_id IS NOT NULL AND subscription_id IS NOT NULL "
        "AND resulting_access_revision IS NOT NULL AND effective_at IS NOT NULL "
        "AND evidence_schema_version = 'allowance-activation:v1')",
    )
    op.create_index(
        "uq_billing_observations_allowance_activation",
        "billing_state_observations",
        [sa.text("(evidence_document ->> 'allowance_id')")],
        unique=True,
        postgresql_where=sa.text("observation_kind = 'allowance_activation'"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM billing_state_observations "
            "WHERE observation_kind = 'allowance_activation' OR evidence_schema_version IN "
            "('subscription-reconciliation:v2', 'primary-selection:v2'))"
        )
    ):
        raise RuntimeError("Activation/V2 evidence requires the new reader; downgrade would lose history semantics.")
    op.drop_index("uq_billing_observations_allowance_activation", table_name="billing_state_observations")
    op.drop_constraint("ck_billing_observations_activation_shape", "billing_state_observations")
    op.drop_constraint("ck_billing_state_observations_kind", "billing_state_observations")
    op.create_check_constraint(
        "ck_billing_state_observations_kind", "billing_state_observations", f"observation_kind IN ({PREVIOUS_KINDS})"
    )
