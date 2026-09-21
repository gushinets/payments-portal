"""add immutable legal acceptance evidence

Revision ID: 20260921_0007
Revises: 20260921_0006
Create Date: 2026-09-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260921_0007"
down_revision = "20260921_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM document_acceptances
                    WHERE user_id IS NULL
                ) THEN
                    RAISE EXCEPTION
                        'cannot migrate legal acceptance evidence: document_acceptances contains rows without a canonical user';
                END IF;
            END
            $$
            """
        )
    )

    op.create_unique_constraint(
        "uq_legal_entities_id_tenant_region",
        "legal_entities",
        ["id", "tenant_id", "region"],
    )
    op.create_unique_constraint(
        "uq_document_versions_id_tenant_region",
        "document_versions",
        ["id", "tenant_id", "region"],
    )
    op.drop_constraint(
        "document_versions_legal_entity_id_fkey",
        "document_versions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_document_versions_legal_entity_scope",
        "document_versions",
        "legal_entities",
        ["legal_entity_id", "tenant_id", "region"],
        ["id", "tenant_id", "region"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "legal_acceptance_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("external_billing_account_id", sa.Text(), nullable=True),
        sa.Column("billing_offer_id", sa.Text(), nullable=True),
        sa.Column("accepted_commercial_fingerprint", sa.Text(), nullable=True),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "tenant_id", "region"],
            ["users.id", "users.tenant_id", "users.region"],
            name="fk_legal_acceptance_events_user_scope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "(external_billing_account_id IS NULL "
            "AND billing_offer_id IS NULL "
            "AND accepted_commercial_fingerprint IS NULL) "
            "OR (external_billing_account_id IS NOT NULL "
            "AND trim(external_billing_account_id) <> '' "
            "AND billing_offer_id IS NOT NULL "
            "AND trim(billing_offer_id) <> '' "
            "AND accepted_commercial_fingerprint IS NOT NULL "
            "AND trim(accepted_commercial_fingerprint) <> '')",
            name="ck_legal_acceptance_events_commercial_triplet",
        ),
        sa.UniqueConstraint(
            "id",
            "user_id",
            "external_billing_account_id",
            "billing_offer_id",
            "accepted_commercial_fingerprint",
            name="uq_legal_acceptance_events_purchase_binding",
        ),
        sa.UniqueConstraint(
            "id",
            "tenant_id",
            "region",
            "user_id",
            name="uq_legal_acceptance_events_scope",
        ),
    )
    op.create_index(
        "ix_legal_acceptance_events_tenant_id",
        "legal_acceptance_events",
        ["tenant_id"],
    )
    op.create_index(
        "ix_legal_acceptance_events_region",
        "legal_acceptance_events",
        ["region"],
    )
    op.create_index(
        "ix_legal_acceptance_events_user_id",
        "legal_acceptance_events",
        ["user_id"],
    )
    op.create_index(
        "ix_legal_acceptance_events_accepted_at",
        "legal_acceptance_events",
        ["accepted_at"],
    )

    op.add_column(
        "document_acceptances",
        sa.Column("legal_acceptance_event_id", sa.Uuid(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO legal_acceptance_events (
                id,
                tenant_id,
                region,
                user_id,
                external_billing_account_id,
                billing_offer_id,
                accepted_commercial_fingerprint,
                accepted_at,
                ip,
                user_agent,
                created_at
            )
            SELECT
                id,
                tenant_id,
                region,
                user_id,
                NULL,
                NULL,
                NULL,
                accepted_at,
                ip,
                user_agent,
                created_at
            FROM document_acceptances
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE document_acceptances
            SET legal_acceptance_event_id = id
            """
        )
    )
    op.alter_column(
        "document_acceptances",
        "legal_acceptance_event_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.alter_column(
        "document_acceptances",
        "user_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.create_index(
        "ix_document_acceptances_legal_acceptance_event_id",
        "document_acceptances",
        ["legal_acceptance_event_id"],
    )

    op.drop_constraint(
        "document_acceptances_user_id_fkey",
        "document_acceptances",
        type_="foreignkey",
    )
    op.drop_constraint(
        "document_acceptances_document_version_id_fkey",
        "document_acceptances",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_document_acceptances_event_scope",
        "document_acceptances",
        "legal_acceptance_events",
        ["legal_acceptance_event_id", "tenant_id", "region", "user_id"],
        ["id", "tenant_id", "region", "user_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_document_acceptances_document_scope",
        "document_acceptances",
        "document_versions",
        ["document_version_id", "tenant_id", "region"],
        ["id", "tenant_id", "region"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_document_acceptances_event_document",
        "document_acceptances",
        ["legal_acceptance_event_id", "document_version_id"],
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION guard_legal_acceptance_event_evidence()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'legal acceptance events are immutable';
                END IF;

                IF NEW.id IS DISTINCT FROM OLD.id
                    OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                    OR NEW.region IS DISTINCT FROM OLD.region
                    OR NEW.user_id IS DISTINCT FROM OLD.user_id
                    OR NEW.external_billing_account_id IS DISTINCT FROM OLD.external_billing_account_id
                    OR NEW.billing_offer_id IS DISTINCT FROM OLD.billing_offer_id
                    OR NEW.accepted_commercial_fingerprint IS DISTINCT FROM OLD.accepted_commercial_fingerprint
                    OR NEW.accepted_at IS DISTINCT FROM OLD.accepted_at
                    OR NEW.created_at IS DISTINCT FROM OLD.created_at
                THEN
                    RAISE EXCEPTION 'core legal acceptance event evidence is immutable';
                END IF;

                IF (OLD.ip IS NULL AND NEW.ip IS NOT NULL)
                    OR (OLD.ip IS NOT NULL AND NEW.ip IS NOT NULL AND NEW.ip IS DISTINCT FROM OLD.ip)
                    OR (OLD.user_agent IS NULL AND NEW.user_agent IS NOT NULL)
                    OR (
                        OLD.user_agent IS NOT NULL
                        AND NEW.user_agent IS NOT NULL
                        AND NEW.user_agent IS DISTINCT FROM OLD.user_agent
                    )
                THEN
                    RAISE EXCEPTION 'legal acceptance event audit metadata may only be cleared';
                END IF;

                RETURN NEW;
            END
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_guard_legal_acceptance_event_evidence
            BEFORE UPDATE OR DELETE ON legal_acceptance_events
            FOR EACH ROW
            EXECUTE FUNCTION guard_legal_acceptance_event_evidence()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION guard_document_acceptance_evidence()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'document acceptances are append-only';
            END
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_guard_document_acceptance_evidence
            BEFORE UPDATE OR DELETE ON document_acceptances
            FOR EACH ROW
            EXECUTE FUNCTION guard_document_acceptance_evidence()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION guard_document_version_material()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NEW.id IS DISTINCT FROM OLD.id
                    OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                    OR NEW.region IS DISTINCT FROM OLD.region
                    OR NEW.legal_entity_id IS DISTINCT FROM OLD.legal_entity_id
                    OR NEW.doc_type IS DISTINCT FROM OLD.doc_type
                    OR NEW.version IS DISTINCT FROM OLD.version
                    OR NEW.title IS DISTINCT FROM OLD.title
                    OR NEW.url_path IS DISTINCT FROM OLD.url_path
                    OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
                    OR NEW.published_at IS DISTINCT FROM OLD.published_at
                    OR NEW.effective_from IS DISTINCT FROM OLD.effective_from
                    OR NEW.requires_acceptance IS DISTINCT FROM OLD.requires_acceptance
                THEN
                    RAISE EXCEPTION 'published legal document material is immutable';
                END IF;

                RETURN NEW;
            END
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_guard_document_version_material
            BEFORE UPDATE ON document_versions
            FOR EACH ROW
            EXECUTE FUNCTION guard_document_version_material()
            """
        )
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_guard_document_version_material ON document_versions")
    op.execute("DROP FUNCTION guard_document_version_material()")
    op.execute("DROP TRIGGER trg_guard_document_acceptance_evidence ON document_acceptances")
    op.execute("DROP FUNCTION guard_document_acceptance_evidence()")
    op.execute("DROP TRIGGER trg_guard_legal_acceptance_event_evidence ON legal_acceptance_events")
    op.execute("DROP FUNCTION guard_legal_acceptance_event_evidence()")

    op.drop_constraint(
        "uq_document_acceptances_event_document",
        "document_acceptances",
        type_="unique",
    )
    op.drop_constraint(
        "fk_document_acceptances_document_scope",
        "document_acceptances",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_document_acceptances_event_scope",
        "document_acceptances",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "document_acceptances_document_version_id_fkey",
        "document_acceptances",
        "document_versions",
        ["document_version_id"],
        ["id"],
    )
    op.create_foreign_key(
        "document_acceptances_user_id_fkey",
        "document_acceptances",
        "users",
        ["user_id"],
        ["id"],
    )
    op.drop_index(
        "ix_document_acceptances_legal_acceptance_event_id",
        table_name="document_acceptances",
    )
    op.alter_column(
        "document_acceptances",
        "user_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )
    op.drop_column("document_acceptances", "legal_acceptance_event_id")

    op.drop_table("legal_acceptance_events")

    op.drop_constraint(
        "fk_document_versions_legal_entity_scope",
        "document_versions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "document_versions_legal_entity_id_fkey",
        "document_versions",
        "legal_entities",
        ["legal_entity_id"],
        ["id"],
    )
    op.drop_constraint(
        "uq_document_versions_id_tenant_region",
        "document_versions",
        type_="unique",
    )
    op.drop_constraint(
        "uq_legal_entities_id_tenant_region",
        "legal_entities",
        type_="unique",
    )
