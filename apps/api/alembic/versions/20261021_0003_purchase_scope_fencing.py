"""Reserve durable purchase scopes and fence external creates.

Revision ID: 20261021_0003
Revises: 20261001_0002

Forward only. Run with purchase writers stopped. PostgreSQL transactional DDL
rolls the entire revision back on duplicate ownership/provider IDs, correlations,
or operation identities; investigate those rows rather than choosing a winner.
Retain the database backup for recovery: downgrade would discard durable fences
and release audit. The frozen first-install revision is deliberately unchanged.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261021_0003"
down_revision = "20261001_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_billing_customers_id_account",
        "external_billing_customers",
        ["customer_id", "external_billing_account_id"],
    )
    for table, name, columns, predicate in (
        (
            "external_billing_customers",
            "uq_billing_customers_account_provider",
            ["external_billing_account_id", "provider_customer_id"],
            "provider_customer_id IS NOT NULL",
        ),
        (
            "external_subscriptions",
            "uq_subscriptions_account_external",
            ["external_billing_account_id", "external_subscription_id"],
            "external_subscription_id IS NOT NULL",
        ),
        (
            "external_subscriptions",
            "uq_subscriptions_account_agreement",
            ["external_billing_account_id", "external_agreement_id"],
            "external_agreement_id IS NOT NULL",
        ),
        ("external_create_operations", "uq_create_operations_customer", ["customer_id"], "operation_kind = 'customer'"),
        (
            "billing_work_items",
            "uq_work_items_create_recovery",
            ["coalescing_key"],
            "work_kind = 'external_create_recovery' AND coalescing_key IS NOT NULL",
        ),
    ):
        op.create_index(name, table, columns, unique=True, postgresql_where=sa.text(predicate))

    op.add_column("external_create_operations", sa.Column("external_billing_account_id", sa.Text(), nullable=True))
    op.add_column(
        "external_create_operations",
        sa.Column("send_fencing_token", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column("external_create_operations", sa.Column("scope_ownership_epoch", sa.BigInteger(), nullable=True))
    op.execute("""
        UPDATE external_create_operations o SET external_billing_account_id = c.external_billing_account_id
        FROM external_billing_customers c WHERE c.customer_id = o.customer_id
    """)
    op.alter_column("external_create_operations", "external_billing_account_id", nullable=False)
    op.create_foreign_key(
        "fk_create_operations_customer_account",
        "external_create_operations",
        "external_billing_customers",
        ["customer_id", "external_billing_account_id"],
        ["customer_id", "external_billing_account_id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_create_operations_correlation", "external_create_operations", ["request_correlation_key"]
    )
    op.create_unique_constraint(
        "uq_create_operations_purchase_kind", "external_create_operations", ["purchase_intent_id", "operation_kind"]
    )
    op.create_index(
        "uq_create_operations_account_kind_bound",
        "external_create_operations",
        ["external_billing_account_id", "operation_kind", "bound_external_object_id"],
        unique=True,
        postgresql_where=sa.text("bound_external_object_id IS NOT NULL"),
    )
    # Legacy free-text states do not prove that no POST was sent. Quarantine them
    # instead of manufacturing permission to send. Preserve existing 2h clocks.
    op.execute("""
        UPDATE external_create_operations SET operation_state = 'manual_review'
        WHERE operation_state NOT IN ('unsent', 'possible_send', 'unknown', 'bound', 'failed_before_send', 'manual_review')
           OR (operation_state = 'bound' AND (bound_external_object_id IS NULL OR resolved_at IS NULL))
    """)
    op.execute("""
        UPDATE external_create_operations SET
            unknown_since = COALESCE(unknown_since, created_at),
            unknown_recovery_deadline_at = COALESCE(unknown_recovery_deadline_at, created_at + interval '2 hours'),
            send_fencing_token = 1
        WHERE operation_state IN ('possible_send', 'unknown', 'manual_review') AND resolved_at IS NULL
    """)
    for name, condition in (
        ("ck_create_operations_fence", "send_fencing_token >= 0"),
        (
            "ck_create_operations_state",
            "operation_state IN ('unsent', 'possible_send', 'unknown', 'bound', 'failed_before_send', 'manual_review')",
        ),
        (
            "ck_create_operations_send_clock",
            "operation_state NOT IN ('possible_send', 'unknown') OR (unknown_since IS NOT NULL AND unknown_recovery_deadline_at IS NOT NULL AND send_fencing_token > 0)",
        ),
        (
            "ck_create_operations_bound",
            "operation_state <> 'bound' OR (bound_external_object_id IS NOT NULL AND resolved_at IS NOT NULL)",
        ),
    ):
        op.create_check_constraint(name, "external_create_operations", condition)

    op.create_table(
        "billing_purchase_scope_holds",
        sa.Column("hold_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column("external_billing_account_id", sa.Text(), nullable=False),
        sa.Column("purchase_intent_id", sa.Uuid(), nullable=True),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("hold_state", sa.Text(), nullable=False, server_default="held"),
        sa.Column("ownership_epoch", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_evidence_schema_version", sa.Text(), nullable=True),
        sa.Column("release_evidence_document", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint("user_id", "product_id", name="uq_purchase_scope_user_product"),
        sa.ForeignKeyConstraint(
            ["user_id", "tenant_id", "region"],
            ["users.id", "users.tenant_id", "users.region"],
            name="fk_purchase_scope_user",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_intent_id", "external_billing_account_id", "user_id", "product_id"],
            [
                "purchase_intents.purchase_intent_id",
                "purchase_intents.external_billing_account_id",
                "purchase_intents.user_id",
                "purchase_intents.product_id",
            ],
            name="fk_purchase_scope_intent",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id", "external_billing_account_id", "user_id", "product_id"],
            [
                "external_subscriptions.subscription_id",
                "external_subscriptions.external_billing_account_id",
                "external_subscriptions.user_id",
                "external_subscriptions.product_id",
            ],
            name="fk_purchase_scope_subscription",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("hold_state IN ('held', 'released')", name="ck_purchase_scope_state"),
        sa.CheckConstraint("ownership_epoch > 0", name="ck_purchase_scope_epoch"),
        sa.CheckConstraint(
            "purchase_intent_id IS NOT NULL OR subscription_id IS NOT NULL", name="ck_purchase_scope_owner"
        ),
        sa.CheckConstraint(
            "(release_evidence_schema_version IS NULL AND release_evidence_document IS NULL) OR (release_evidence_schema_version IS NOT NULL AND release_evidence_schema_version = 'v1' AND release_evidence_document IS NOT NULL)",
            name="ck_purchase_scope_evidence_pair",
        ),
        sa.CheckConstraint(
            "(hold_state = 'held' AND released_at IS NULL) OR (hold_state = 'released' AND released_at IS NOT NULL AND release_evidence_document IS NOT NULL)",
            name="ck_purchase_scope_release",
        ),
    )
    op.execute("""
        CREATE TEMP TABLE purchase_scope_backfill ON COMMIT DROP AS
        SELECT COALESCE(p.user_id, s.user_id) AS user_id,
               COALESCE(p.product_id, s.product_id) AS product_id,
               COALESCE(p.external_billing_account_id, s.external_billing_account_id) AS account_id,
               p.purchase_intent_id, s.subscription_id
        FROM purchase_intents p FULL JOIN external_subscriptions s ON s.purchase_intent_id = p.purchase_intent_id
        WHERE s.lifecycle_status <> 'ended'
               OR (p.state NOT IN ('resolved_no_external_effect', 'failed_before_external_effect')
                   AND (p.state <> 'linked' OR s.lifecycle_status IS DISTINCT FROM 'ended'))
           OR EXISTS (SELECT 1 FROM external_create_operations o
                      WHERE o.purchase_intent_id = p.purchase_intent_id AND o.resolved_at IS NULL)
    """)
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM purchase_scope_backfill GROUP BY user_id, product_id HAVING count(*) > 1) THEN
                RAISE EXCEPTION 'conflicting historical purchase scopes; explicit ownership reconciliation required';
            END IF;
        END $$
    """)
    op.execute("""
        INSERT INTO billing_purchase_scope_holds
            (hold_id, user_id, product_id, tenant_id, region, external_billing_account_id, purchase_intent_id, subscription_id)
        SELECT gen_random_uuid(), b.user_id, b.product_id, u.tenant_id, u.region, b.account_id, b.purchase_intent_id, b.subscription_id
        FROM purchase_scope_backfill b JOIN users u ON u.id = b.user_id
    """)
    op.execute("""
        INSERT INTO billing_work_items (work_item_id, work_kind, scope_kind, scope_reference, coalescing_key,
            payload_schema_version, payload_document, next_attempt_at, work_state)
        SELECT gen_random_uuid(), 'external_create_recovery', 'external_create_operation', create_operation_id::text,
            'external-create:' || create_operation_id::text, 'v1',
            jsonb_build_object('create_operation_id', create_operation_id::text), unknown_recovery_deadline_at, 'pending'
        FROM external_create_operations WHERE resolved_at IS NULL AND unknown_recovery_deadline_at IS NOT NULL
        ON CONFLICT (coalescing_key) WHERE work_kind = 'external_create_recovery' AND coalescing_key IS NOT NULL
        DO NOTHING
    """)
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM external_create_operations o
                WHERE o.resolved_at IS NULL AND o.unknown_recovery_deadline_at IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM billing_work_items w
                      WHERE w.work_kind = 'external_create_recovery'
                        AND w.coalescing_key = 'external-create:' || o.create_operation_id::text
                        AND w.scope_kind = 'external_create_operation'
                        AND w.scope_reference = o.create_operation_id::text
                        AND w.next_attempt_at = o.unknown_recovery_deadline_at
                        AND w.work_state <> 'completed')
            ) THEN RAISE EXCEPTION 'conflicting historical recovery obligation; explicit reconciliation required'; END IF;
        END $$
    """)
    _create_guards()


def _create_guards() -> None:
    op.execute("""
        CREATE FUNCTION guard_create_operation_fence() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'create operation fences are permanent'; END IF;
            IF (NEW.create_operation_id, NEW.customer_id, NEW.purchase_intent_id, NEW.operation_kind,
                NEW.external_billing_account_id, NEW.request_correlation_key)
               IS DISTINCT FROM
               (OLD.create_operation_id, OLD.customer_id, OLD.purchase_intent_id, OLD.operation_kind,
                OLD.external_billing_account_id, OLD.request_correlation_key)
               OR NEW.send_fencing_token < OLD.send_fencing_token
               OR (OLD.unknown_since IS NOT NULL AND
                   (NEW.unknown_since, NEW.unknown_recovery_deadline_at) IS DISTINCT FROM
                   (OLD.unknown_since, OLD.unknown_recovery_deadline_at))
               OR (OLD.bound_external_object_id IS NOT NULL AND
                   NEW.bound_external_object_id IS DISTINCT FROM OLD.bound_external_object_id)
               OR (OLD.operation_state IN ('possible_send', 'unknown', 'bound', 'manual_review') AND NEW.operation_state = 'unsent')
            THEN RAISE EXCEPTION 'create operation identity or send fence is immutable'; END IF;
            RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER trg_create_operation_fence BEFORE UPDATE OR DELETE ON external_create_operations FOR EACH ROW EXECUTE FUNCTION guard_create_operation_fence()"
    )
    op.execute("""
        CREATE FUNCTION require_create_recovery_item() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM external_create_operations o
                       WHERE o.create_operation_id = NEW.create_operation_id
                         AND o.operation_state IN ('possible_send', 'unknown') AND o.resolved_at IS NULL
                         AND NOT EXISTS (SELECT 1 FROM billing_work_items w
                             WHERE w.work_kind = 'external_create_recovery'
                               AND w.coalescing_key = 'external-create:' || o.create_operation_id::text
                               AND w.scope_kind = 'external_create_operation'
                               AND w.scope_reference = o.create_operation_id::text
                               AND w.next_attempt_at = o.unknown_recovery_deadline_at))
            THEN RAISE EXCEPTION 'potential send requires a durable two-hour recovery item'; END IF;
            RETURN NULL;
        END $$
    """)
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_create_recovery_item AFTER INSERT OR UPDATE ON external_create_operations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_create_recovery_item()"
    )
    op.execute("""
        CREATE FUNCTION guard_purchase_scope_hold() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE audit jsonb; last_release jsonb;
        BEGIN
            IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'purchase scope history is permanent'; END IF;
            IF NEW.purchase_intent_id IS NOT NULL AND NEW.subscription_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM external_subscriptions s WHERE s.subscription_id = NEW.subscription_id
                AND s.purchase_intent_id = NEW.purchase_intent_id
            ) THEN RAISE EXCEPTION 'purchase scope owners have different provenance'; END IF;
            IF TG_OP = 'UPDATE' THEN
                IF (NEW.hold_id, NEW.user_id, NEW.product_id, NEW.tenant_id, NEW.region)
                    IS DISTINCT FROM (OLD.hold_id, OLD.user_id, OLD.product_id, OLD.tenant_id, OLD.region)
                    OR NEW.ownership_epoch < OLD.ownership_epoch
                    OR ((NEW.purchase_intent_id, NEW.subscription_id, NEW.external_billing_account_id, NEW.hold_state)
                        IS DISTINCT FROM (OLD.purchase_intent_id, OLD.subscription_id, OLD.external_billing_account_id, OLD.hold_state)
                        AND NEW.ownership_epoch <= OLD.ownership_epoch)
                THEN RAISE EXCEPTION 'purchase scope ownership requires a new epoch'; END IF;
                IF OLD.release_evidence_document IS NOT NULL THEN
                    IF jsonb_typeof(NEW.release_evidence_document->'releases') IS DISTINCT FROM 'array' THEN
                        RAISE EXCEPTION 'purchase release audit is append only';
                    END IF;
                    IF EXISTS (SELECT 1 FROM jsonb_array_elements(OLD.release_evidence_document->'releases')
                               WITH ORDINALITY AS prior_entry(value, ordinal)
                               WHERE NEW.release_evidence_document->'releases'->(prior_entry.ordinal::int - 1)
                                     IS DISTINCT FROM prior_entry.value)
                    THEN RAISE EXCEPTION 'purchase release audit is append only'; END IF;
                END IF;
                IF OLD.hold_state = 'held' AND NEW.hold_state = 'held' AND
                    ((NEW.purchase_intent_id, NEW.external_billing_account_id) IS DISTINCT FROM
                     (OLD.purchase_intent_id, OLD.external_billing_account_id)
                     OR (OLD.subscription_id IS NOT NULL AND NEW.subscription_id IS DISTINCT FROM OLD.subscription_id))
                THEN RAISE EXCEPTION 'held purchase scope must be released before reassignment'; END IF;
                IF OLD.hold_state = 'held' AND NEW.hold_state = 'released' AND
                    (NEW.purchase_intent_id, NEW.subscription_id, NEW.external_billing_account_id)
                    IS DISTINCT FROM (OLD.purchase_intent_id, OLD.subscription_id, OLD.external_billing_account_id)
                THEN RAISE EXCEPTION 'release must retain original purchase owners'; END IF;
            END IF;
            IF NEW.hold_state = 'released' THEN
                audit := NEW.release_evidence_document->'releases';
                last_release := audit->-1;
                IF jsonb_typeof(audit) IS DISTINCT FROM 'array' OR jsonb_array_length(audit) = 0
                   OR COALESCE(last_release->>'kind', '') NOT IN ('authoritative_no_effect', 'verified_terminal', 'audited_support')
                   OR trim(COALESCE(last_release->>'proof_reference', '')) = ''
                   OR trim(COALESCE(last_release->>'principal', '')) = ''
                THEN RAISE EXCEPTION 'typed purchase release proof is required'; END IF;
                IF TG_OP = 'INSERT' THEN RAISE EXCEPTION 'new purchase scope must be held'; END IF;
                IF OLD.hold_state = 'held' AND (last_release->>'ownership_epoch')::bigint IS DISTINCT FROM OLD.ownership_epoch
                THEN RAISE EXCEPTION 'purchase release proof has stale ownership epoch'; END IF;
                IF last_release->>'kind' <> 'audited_support' THEN
                    IF EXISTS (SELECT 1 FROM external_subscriptions s WHERE s.user_id = NEW.user_id
                               AND s.product_id = NEW.product_id AND s.lifecycle_status <> 'ended')
                       OR EXISTS (SELECT 1 FROM external_create_operations o
                           JOIN external_billing_customers c ON c.customer_id = o.customer_id
                           LEFT JOIN purchase_intents p ON p.purchase_intent_id = o.purchase_intent_id
                           WHERE c.user_id = NEW.user_id AND o.resolved_at IS NULL
                             AND (p.product_id = NEW.product_id OR o.purchase_intent_id IS NULL))
                    THEN RAISE EXCEPTION 'unresolved external effect retains purchase hold'; END IF;
                    IF last_release->>'kind' = 'verified_terminal' AND NOT EXISTS (
                        SELECT 1 FROM external_subscriptions s WHERE s.subscription_id = NEW.subscription_id
                        AND s.lifecycle_status = 'ended'
                    ) THEN RAISE EXCEPTION 'verified terminal release requires ended subscription'; END IF;
                END IF;
            END IF;
            NEW.updated_at := now();
            RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER trg_purchase_scope_hold BEFORE INSERT OR UPDATE OR DELETE ON billing_purchase_scope_holds FOR EACH ROW EXECUTE FUNCTION guard_purchase_scope_hold()"
    )


def downgrade() -> None:
    raise RuntimeError("Purchase scope fencing is forward-only; restore an audited pre-migration backup instead")
