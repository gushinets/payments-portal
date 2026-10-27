"""Normal LBX billing: product links, customer identity and purchase preparation.

Revision ID: 20261027_0003
Revises: 20261001_0002

Consolidates the branch-local 0003-0006 revisions without changing their SQL
operations. This is the third revision after the unchanged main baseline.
Already-upgraded local databases require a verified revision-label transition
from the retired 20261027_0006; never replay this DDL over an existing schema.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261027_0003"
down_revision = "20261001_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Current product links; never promote historical mappings.
    op.create_table(
        "commercial_product_heads",
        sa.Column("external_billing_account_id", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("mapping_revision_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("external_billing_account_id", "product_id"),
        sa.ForeignKeyConstraint(
            ["mapping_revision_id", "external_billing_account_id"],
            [
                "commercial_mapping_revisions.mapping_revision_id",
                "commercial_mapping_revisions.external_billing_account_id",
            ],
            name="fk_commercial_product_heads_mapping_scope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("revision_number > 0", name="ck_commercial_product_heads_revision_positive"),
        sa.CheckConstraint("trim(product_id) <> ''", name="ck_commercial_product_heads_product_nonempty"),
    )

    # Provider-origin provenance; never guess a legacy origin.
    op.add_column("commercial_product_heads", sa.Column("provider_origin", sa.Text(), nullable=True))
    op.create_unique_constraint(
        "uq_commercial_product_heads_origin_product", "commercial_product_heads", ["provider_origin", "product_id"]
    )

    # Optional names and permanent customer-create identity.
    for name in ("first_name", "surname", "patronymic"):
        op.add_column("users", sa.Column(name, sa.String(100), nullable=True))
    # No guessed name/origin, provider calls, deletion or legacy promotion.
    op.add_column("external_billing_customers", sa.Column("provider_origin", sa.Text(), nullable=True))
    op.add_column("external_create_operations", sa.Column("send_fence", sa.Uuid(), nullable=True))
    op.create_unique_constraint(
        "uq_billing_customers_provider",
        "external_billing_customers",
        ["external_billing_account_id", "provider_customer_id"],
    )
    op.create_index(
        "uq_external_create_operations_customer_identity",
        "external_create_operations",
        ["customer_id"],
        unique=True,
        postgresql_where=sa.text("operation_kind = 'customer'"),
    )
    op.create_index(
        "uq_billing_work_items_create_recovery",
        "billing_work_items",
        ["coalescing_key"],
        unique=True,
        postgresql_where=sa.text("work_kind = 'external_create_recovery'"),
    )

    # Purchase holds and permanent financial-create evidence.
    op.create_unique_constraint(
        "uq_billing_customers_id_account", "external_billing_customers", ["customer_id", "external_billing_account_id"]
    )
    op.add_column("external_create_operations", sa.Column("external_billing_account_id", sa.Text(), nullable=True))
    op.execute(
        "UPDATE external_create_operations o SET external_billing_account_id = c.external_billing_account_id FROM external_billing_customers c WHERE c.customer_id = o.customer_id"
    )
    op.create_foreign_key(
        "fk_create_operation_account",
        "external_create_operations",
        "external_billing_customers",
        ["customer_id", "external_billing_account_id"],
        ["customer_id", "external_billing_account_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_financial_operation_account",
        "external_create_operations",
        "operation_kind = 'customer' OR external_billing_account_id IS NOT NULL",
    )
    op.create_index(
        "uq_financial_operation_identity",
        "external_create_operations",
        ["purchase_intent_id", "operation_kind"],
        unique=True,
        postgresql_where=sa.text("operation_kind IN ('agreement', 'subscription')"),
    )
    op.create_index(
        "uq_financial_operation_binding",
        "external_create_operations",
        ["external_billing_account_id", "operation_kind", "bound_external_object_id"],
        unique=True,
        postgresql_where=sa.text("operation_kind IN ('agreement', 'subscription')"),
    )
    # Conflicting historical real bindings intentionally fail migration; no arbitrary adoption/deletion.
    op.create_unique_constraint(
        "uq_subscription_provider",
        "external_subscriptions",
        ["external_billing_account_id", "external_subscription_id"],
    )
    op.create_unique_constraint(
        "uq_subscription_agreement", "external_subscriptions", ["external_billing_account_id", "external_agreement_id"]
    )
    op.drop_constraint("ck_external_subscriptions_financial_access_status", "external_subscriptions", type_="check")
    op.create_check_constraint(
        "ck_external_subscriptions_financial_access_status",
        "external_subscriptions",
        "financial_access_status IN ('allowed', 'blocked', 'unverified')",
    )
    op.create_table(
        "billing_purchase_scope_holds",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("product_id", sa.Text(), primary_key=True),
        sa.Column("external_billing_account_id", sa.Text(), nullable=False),
        sa.Column("purchase_intent_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["purchase_intent_id", "external_billing_account_id", "user_id", "product_id"],
            [
                "purchase_intents.purchase_intent_id",
                "purchase_intents.external_billing_account_id",
                "purchase_intents.user_id",
                "purchase_intents.product_id",
            ],
            name="fk_purchase_hold_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("purchase_intent_id", name="uq_purchase_hold_intent"),
    )
    # All nonterminal/linked history keeps its scope. Ambiguity fails closed.
    op.execute(
        "INSERT INTO billing_purchase_scope_holds (user_id, product_id, external_billing_account_id, purchase_intent_id) SELECT user_id, product_id, external_billing_account_id, purchase_intent_id FROM purchase_intents WHERE state NOT IN ('failed_before_external_effect', 'resolved_no_external_effect')"
    )
    op.execute("""
        CREATE FUNCTION guard_financial_create_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.operation_kind = 'customer' THEN
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'financial create identity is permanent'; END IF;
            IF (NEW.create_operation_id, NEW.operation_kind, NEW.customer_id, NEW.purchase_intent_id,
                NEW.external_billing_account_id, NEW.request_correlation_key, NEW.created_at)
                IS DISTINCT FROM
               (OLD.create_operation_id, OLD.operation_kind, OLD.customer_id, OLD.purchase_intent_id,
                OLD.external_billing_account_id, OLD.request_correlation_key, OLD.created_at)
               OR (OLD.unknown_since IS NOT NULL AND
                   (NEW.unknown_since, NEW.unknown_recovery_deadline_at, NEW.recovery_hint_schema_version,
                    NEW.recovery_hint_document) IS DISTINCT FROM
                   (OLD.unknown_since, OLD.unknown_recovery_deadline_at, OLD.recovery_hint_schema_version,
                    OLD.recovery_hint_document))
               OR (OLD.unknown_since IS NOT NULL AND NEW.operation_state = 'pending')
               OR (OLD.bound_external_object_id IS NOT NULL AND
                   NEW.bound_external_object_id IS DISTINCT FROM OLD.bound_external_object_id)
            THEN RAISE EXCEPTION 'financial create evidence is immutable'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER trg_guard_financial_create_evidence BEFORE UPDATE OR DELETE ON external_create_operations
        FOR EACH ROW EXECUTE FUNCTION guard_financial_create_evidence();
    """)


def downgrade() -> None:
    # Purchase holds and permanent financial-create evidence.
    op.execute("DROP TRIGGER trg_guard_financial_create_evidence ON external_create_operations")
    op.execute("DROP FUNCTION guard_financial_create_evidence()")
    op.drop_table("billing_purchase_scope_holds")
    # Do not reinterpret an unverified preparation as a financial denial on downgrade.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM external_subscriptions WHERE financial_access_status = 'unverified') THEN RAISE EXCEPTION 'unverified preparation requires explicit migration decision'; END IF; END $$"
    )
    op.drop_constraint("ck_external_subscriptions_financial_access_status", "external_subscriptions", type_="check")
    op.create_check_constraint(
        "ck_external_subscriptions_financial_access_status",
        "external_subscriptions",
        "financial_access_status IN ('allowed', 'blocked')",
    )
    for name in ("uq_subscription_agreement", "uq_subscription_provider"):
        op.drop_constraint(name, "external_subscriptions", type_="unique")
    for name in ("uq_financial_operation_binding", "uq_financial_operation_identity"):
        op.drop_index(name, table_name="external_create_operations")
    op.drop_constraint("ck_financial_operation_account", "external_create_operations", type_="check")
    op.drop_constraint("fk_create_operation_account", "external_create_operations", type_="foreignkey")
    op.drop_column("external_create_operations", "external_billing_account_id")
    op.drop_constraint("uq_billing_customers_id_account", "external_billing_customers", type_="unique")

    # Optional names and permanent customer-create identity.
    op.drop_index("uq_billing_work_items_create_recovery", table_name="billing_work_items")
    op.drop_index("uq_external_create_operations_customer_identity", table_name="external_create_operations")
    op.drop_constraint("uq_billing_customers_provider", "external_billing_customers", type_="unique")
    op.drop_column("external_create_operations", "send_fence")
    op.drop_column("external_billing_customers", "provider_origin")
    for name in ("patronymic", "surname", "first_name"):
        op.drop_column("users", name)

    # Provider-origin provenance; never guess a legacy origin.
    op.drop_constraint("uq_commercial_product_heads_origin_product", "commercial_product_heads", type_="unique")
    op.drop_column("commercial_product_heads", "provider_origin")

    # Current product links; never promote historical mappings.
    op.drop_table("commercial_product_heads")
