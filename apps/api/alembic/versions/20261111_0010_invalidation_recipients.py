"""Partition retained invalidation state by backend recipient.

APIs and embedded workers must be stopped before this synchronized cutover.
Existing revisions, retry/parking state and row identities remain unchanged.
Only pre-cutover running claims are retired; repair reclaims unresolved work.
"""

from alembic import op
import sqlalchemy as sa

revision = "20261111_0010"
down_revision = "20261111_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("backend_consumer_policies", sa.Column(
        "snapshot_delivery_enabled", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))
    op.alter_column("backend_consumer_policies", "snapshot_delivery_enabled", server_default=None)
    op.add_column("access_invalidation_outbox", sa.Column(
        "recipient_id", sa.Text(), nullable=False, server_default="platform-kernel",
    ))
    op.alter_column("access_invalidation_outbox", "recipient_id", server_default=None)
    op.execute("""CREATE OR REPLACE FUNCTION guard_access_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'access invalidation cannot be deleted'; END IF;
      IF (NEW.outbox_id, NEW.tenant_id, NEW.region, NEW.user_id, NEW.recipient_id) IS DISTINCT FROM
         (OLD.outbox_id, OLD.tenant_id, OLD.region, OLD.user_id, OLD.recipient_id)
         OR NEW.pending_revision < OLD.pending_revision OR NEW.delivered_revision < OLD.delivered_revision
      THEN RAISE EXCEPTION 'access invalidation revision regression'; END IF;
      RETURN NEW;
    END $$""")
    op.drop_constraint("uq_access_invalidation_outbox_tenant_region_user", "access_invalidation_outbox")
    op.create_unique_constraint(
        "uq_access_invalidation_outbox_recipient_user", "access_invalidation_outbox",
        ["tenant_id", "region", "user_id", "recipient_id"],
    )
    op.add_column("billing_work_items", sa.Column("recipient_id", sa.Text(), nullable=True))
    op.execute("""UPDATE billing_work_items SET
        recipient_id = 'platform-kernel',
        coalescing_key = 'platform-kernel:' || scope_reference,
        enqueue_generation = enqueue_generation + CASE WHEN work_state = 'running' THEN 1 ELSE 0 END,
        work_state = CASE WHEN work_state = 'running' THEN 'pending' ELSE work_state END,
        lease_owner = NULL, lease_expires_at = NULL
        WHERE work_kind = 'access_invalidation'""")
    op.create_check_constraint(
        "ck_billing_work_items_recipient", "billing_work_items",
        "(work_kind = 'access_invalidation' AND recipient_id IS NOT NULL) OR "
        "(work_kind <> 'access_invalidation' AND recipient_id IS NULL)",
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("""SELECT 1 FROM access_invalidation_outbox WHERE recipient_id <> 'platform-kernel'
        UNION ALL SELECT 1 FROM billing_work_items
        WHERE work_kind = 'access_invalidation' AND recipient_id <> 'platform-kernel' LIMIT 1""")).first():
        raise RuntimeError("Multiple recipients require the Step 13 reader; downgrade is unsafe")
    op.drop_constraint("ck_billing_work_items_recipient", "billing_work_items")
    op.execute("""UPDATE billing_work_items SET coalescing_key = scope_reference,
        enqueue_generation = enqueue_generation + CASE WHEN work_state = 'running' THEN 1 ELSE 0 END,
        work_state = CASE WHEN work_state = 'running' THEN 'pending' ELSE work_state END,
        lease_owner = NULL, lease_expires_at = NULL WHERE work_kind = 'access_invalidation'""")
    op.drop_column("billing_work_items", "recipient_id")
    op.drop_constraint("uq_access_invalidation_outbox_recipient_user", "access_invalidation_outbox")
    op.create_unique_constraint(
        "uq_access_invalidation_outbox_tenant_region_user", "access_invalidation_outbox",
        ["tenant_id", "region", "user_id"],
    )
    op.execute("""CREATE OR REPLACE FUNCTION guard_access_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'access invalidation cannot be deleted'; END IF;
      IF (NEW.outbox_id, NEW.tenant_id, NEW.region, NEW.user_id) IS DISTINCT FROM
         (OLD.outbox_id, OLD.tenant_id, OLD.region, OLD.user_id)
         OR NEW.pending_revision < OLD.pending_revision OR NEW.delivered_revision < OLD.delivered_revision
      THEN RAISE EXCEPTION 'access invalidation revision regression'; END IF;
      RETURN NEW;
    END $$""")
    op.drop_column("access_invalidation_outbox", "recipient_id")
    op.drop_column("backend_consumer_policies", "snapshot_delivery_enabled")
