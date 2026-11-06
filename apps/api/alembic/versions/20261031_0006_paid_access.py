"""Internal paid projection, lossless cycle rows and monotonic storage guards.

Revision ID: 20261031_0006
Revises: 20261028_0005
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20261031_0006"
down_revision = "20261028_0005"
branch_labels = None
depends_on = None

SHAPE = """
(cycle_schema_version = 'legacy-utc:v1' AND period_start IS NOT NULL AND period_end IS NOT NULL
 AND cycle_date_start IS NULL AND cycle_date_end IS NULL AND calendar_document IS NULL AND unit IS NULL AND terms_document IS NULL) OR
(cycle_schema_version = 'calendar:v1' AND period_start IS NULL AND period_end IS NULL
 AND cycle_date_start IS NOT NULL AND cycle_date_end IS NOT NULL AND cycle_date_start <= cycle_date_end
 AND provider_cycle_start IS NULL AND provider_cycle_end IS NULL
 AND calendar_document IS NOT NULL AND unit IS NOT NULL AND terms_document IS NOT NULL AND provider_cycle_key IS NOT NULL) OR
(cycle_schema_version = 'timestamp:v1' AND period_start IS NOT NULL AND period_end IS NOT NULL
 AND provider_cycle_start IS NOT NULL AND provider_cycle_end IS NOT NULL
 AND cycle_date_start IS NULL AND cycle_date_end IS NULL
 AND calendar_document IS NOT NULL AND unit IS NOT NULL AND terms_document IS NOT NULL AND provider_cycle_key IS NOT NULL)
"""


def upgrade() -> None:
    # Fail before changing data. Never repair evidence or select winners implicitly.
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM purchased_allowances WHERE provider_cycle_key IS NOT NULL
        GROUP BY subscription_id, source_component_id, metric_key, provider_cycle_key HAVING count(*) > 1)
        OR EXISTS (SELECT 1 FROM paid_access_states WHERE access_revision <= 0)
        OR EXISTS (SELECT 1 FROM billing_state_observations WHERE resulting_access_revision <= 0)
        OR EXISTS (SELECT 1 FROM access_invalidation_outbox WHERE delivered_revision < 0)
      THEN RAISE EXCEPTION 'paid access preflight: incompatible legacy evidence; manual investigation required'; END IF;
    END $$""")
    for name in ("period_start", "period_end"):
        op.alter_column("purchased_allowances", name, nullable=True)
    for column in (
        sa.Column("cycle_schema_version", sa.Text(), nullable=False, server_default="legacy-utc:v1"),
        sa.Column("cycle_date_start", sa.Date(), nullable=True),
        sa.Column("cycle_date_end", sa.Date(), nullable=True),
        sa.Column("calendar_document", JSONB(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("terms_document", JSONB(), nullable=True),
    ):
        op.add_column("purchased_allowances", column)
    op.create_check_constraint("ck_purchased_allowances_cycle_shape", "purchased_allowances", SHAPE)
    op.create_unique_constraint(
        "uq_purchased_allowances_logical_cycle",
        "purchased_allowances",
        ["subscription_id", "source_component_id", "metric_key", "provider_cycle_key"],
    )
    for column in (
        sa.Column("effective_access_document", JSONB(), nullable=True),
        sa.Column("effective_access_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_basis_observation_id", UUID(as_uuid=True), nullable=True),
        sa.Column("primary_retired_at", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column("billing_product_access_scopes", column)
    op.create_foreign_key(
        "fk_access_scope_basis",
        "billing_product_access_scopes",
        "billing_state_observations",
        ["access_basis_observation_id"],
        ["observation_id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_billing_product_access_scopes_effective_access_until",
        "billing_product_access_scopes",
        ["effective_access_until"],
    )
    op.create_check_constraint("ck_paid_access_states_revision_positive", "paid_access_states", "access_revision > 0")
    op.create_check_constraint(
        "ck_billing_observations_revision_positive",
        "billing_state_observations",
        "resulting_access_revision IS NULL OR resulting_access_revision > 0",
    )
    op.create_check_constraint(
        "ck_access_invalidation_outbox_delivered_nonnegative", "access_invalidation_outbox", "delivered_revision >= 0"
    )
    op.execute("""CREATE FUNCTION guard_paid_access_state() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'paid access state cannot be reset'; END IF;
      IF (NEW.paid_access_state_id, NEW.tenant_id, NEW.region, NEW.user_id) IS DISTINCT FROM
         (OLD.paid_access_state_id, OLD.tenant_id, OLD.region, OLD.user_id)
         OR NEW.access_revision < OLD.access_revision
         OR (NEW.access_revision > OLD.access_revision AND NEW.access_revision <> OLD.access_revision + 1)
         OR (NEW.access_revision = OLD.access_revision AND
            (NEW.effective_state_schema_version, NEW.effective_state_document) IS DISTINCT FROM
            (OLD.effective_state_schema_version, OLD.effective_state_document))
      THEN RAISE EXCEPTION 'paid access revision or semantic regression'; END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER trg_guard_paid_access_state BEFORE UPDATE OR DELETE ON paid_access_states FOR EACH ROW EXECUTE FUNCTION guard_paid_access_state()"
    )
    op.execute("""CREATE FUNCTION guard_access_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'access invalidation cannot be deleted'; END IF;
      IF (NEW.outbox_id, NEW.tenant_id, NEW.region, NEW.user_id) IS DISTINCT FROM
         (OLD.outbox_id, OLD.tenant_id, OLD.region, OLD.user_id)
         OR NEW.pending_revision < OLD.pending_revision OR NEW.delivered_revision < OLD.delivered_revision
      THEN RAISE EXCEPTION 'access invalidation revision regression'; END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER trg_guard_access_outbox BEFORE UPDATE OR DELETE ON access_invalidation_outbox FOR EACH ROW EXECUTE FUNCTION guard_access_outbox()"
    )
    op.drop_constraint("ck_billing_state_observations_kind_shape", "billing_state_observations", type_="check")
    op.create_check_constraint(
        "ck_billing_state_observations_kind_shape",
        "billing_state_observations",
        """
      (observation_kind <> 'authoritative_subscription_read' OR subscription_id IS NOT NULL)
      AND (observation_kind <> 'target_product_discovery' OR
           (user_id IS NOT NULL AND product_id IS NOT NULL AND (access_scope_id IS NOT NULL OR
            (evidence_schema_version IN ('target-product-discovery:v2', 'paid-access-cause:v1') AND purchase_intent_id IS NOT NULL))))
      AND (observation_kind <> 'primary_selection' OR (access_scope_id IS NOT NULL AND basis_observation_id IS NOT NULL))
      AND (observation_kind <> 'deterministic_access_boundary' OR (access_scope_id IS NOT NULL AND subscription_id IS NOT NULL AND effective_at IS NOT NULL))
    """,
    )
    # The existing whole-row allowance immutability trigger covers every new field.


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM purchased_allowances WHERE cycle_schema_version <> 'legacy-utc:v1')
         OR EXISTS (SELECT 1 FROM billing_state_observations WHERE observation_kind = 'target_product_discovery' AND access_scope_id IS NULL)
         OR EXISTS (SELECT 1 FROM paid_access_states)
         OR EXISTS (SELECT 1 FROM billing_product_access_scopes WHERE effective_access_document IS NOT NULL OR primary_retired_at IS NOT NULL)
      THEN RAISE EXCEPTION 'paid access downgrade refuses to discard committed calendar/access meaning'; END IF;
    END $$""")
    op.drop_constraint("ck_billing_state_observations_kind_shape", "billing_state_observations", type_="check")
    op.create_check_constraint(
        "ck_billing_state_observations_kind_shape",
        "billing_state_observations",
        """
      (observation_kind <> 'authoritative_subscription_read' OR subscription_id IS NOT NULL)
      AND (observation_kind <> 'target_product_discovery' OR (user_id IS NOT NULL AND product_id IS NOT NULL AND access_scope_id IS NOT NULL))
      AND (observation_kind <> 'primary_selection' OR (access_scope_id IS NOT NULL AND basis_observation_id IS NOT NULL))
      AND (observation_kind <> 'deterministic_access_boundary' OR (access_scope_id IS NOT NULL AND subscription_id IS NOT NULL AND effective_at IS NOT NULL))
    """,
    )
    for table, name, function in (
        ("paid_access_states", "trg_guard_paid_access_state", "guard_paid_access_state"),
        ("access_invalidation_outbox", "trg_guard_access_outbox", "guard_access_outbox"),
    ):
        op.execute(f"DROP TRIGGER {name} ON {table}")
        op.execute(f"DROP FUNCTION {function}()")
    for table, name in (
        ("paid_access_states", "ck_paid_access_states_revision_positive"),
        ("billing_state_observations", "ck_billing_observations_revision_positive"),
        ("access_invalidation_outbox", "ck_access_invalidation_outbox_delivered_nonnegative"),
        ("purchased_allowances", "ck_purchased_allowances_cycle_shape"),
    ):
        op.drop_constraint(name, table, type_="check")
    op.drop_constraint("uq_purchased_allowances_logical_cycle", "purchased_allowances", type_="unique")
    op.drop_index("ix_billing_product_access_scopes_effective_access_until", table_name="billing_product_access_scopes")
    op.drop_constraint("fk_access_scope_basis", "billing_product_access_scopes", type_="foreignkey")
    for name in (
        "effective_access_document",
        "effective_access_until",
        "access_basis_observation_id",
        "primary_retired_at",
    ):
        op.drop_column("billing_product_access_scopes", name)
    for name in (
        "cycle_schema_version",
        "cycle_date_start",
        "cycle_date_end",
        "calendar_document",
        "unit",
        "terms_document",
    ):
        op.drop_column("purchased_allowances", name)
    for name in ("period_start", "period_end"):
        op.alter_column("purchased_allowances", name, nullable=False)
