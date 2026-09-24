"""Create the clean first-install Payment Portal schema.

Revision ID: 20260924_0001
Revises:
Create Date: 2026-09-24
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260924_0001"
down_revision = None
branch_labels = None
depends_on = None


UUID_TYPE = sa.Uuid()
JSONB_TYPE = postgresql.JSONB(astext_type=sa.Text())
IP_TYPE = postgresql.INET()


def _create_survivor_tables() -> None:
    op.create_table(
        "regions",
        sa.Column("code", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("residency_zone", sa.Text(), nullable=False),
        sa.Column("default_currency", sa.String(length=3), nullable=False),
        sa.Column("default_locale", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
    )
    op.create_table(
        "country_region_rules",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("market_enabled", sa.Boolean(), nullable=False),
        sa.Column("strict_mismatch", sa.Boolean(), nullable=False),
        sa.Column("default_document_set", sa.Text(), nullable=False),
        sa.UniqueConstraint("country_code", name="uq_country_region_rules_country_code"),
    )
    op.create_index("ix_country_region_rules_country_code", "country_region_rules", ["country_code"])
    op.create_index("ix_country_region_rules_region", "country_region_rules", ["region"])

    op.create_table(
        "users",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("email_normalized", sa.String(length=320), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "tenant_id",
            "region",
            "email_normalized",
            name="uq_users_tenant_region_email_normalized",
        ),
        sa.UniqueConstraint("id", "tenant_id", "region", name="uq_users_id_tenant_region"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_region", "users", ["region"])
    op.create_index("ix_users_email_normalized", "users", ["email_normalized"])
    op.create_index("ix_users_status", "users", ["status"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("user_id", UUID_TYPE, nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", IP_TYPE, nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id", "tenant_id", "region"],
            ["users.id", "users.tenant_id", "users.region"],
            name="fk_auth_sessions_user_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_tenant_id", "auth_sessions", ["tenant_id"])
    op.create_index("ix_auth_sessions_region", "auth_sessions", ["region"])
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"])

    op.create_table(
        "magic_link_tokens",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("user_id", UUID_TYPE, nullable=True),
        sa.Column("email_normalized", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", IP_TYPE, nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id", "tenant_id", "region"],
            ["users.id", "users.tenant_id", "users.region"],
            name="fk_magic_link_tokens_user_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("token_hash", name="uq_magic_link_tokens_token_hash"),
    )
    op.create_index("ix_magic_link_tokens_tenant_id", "magic_link_tokens", ["tenant_id"])
    op.create_index("ix_magic_link_tokens_region", "magic_link_tokens", ["region"])
    op.create_index("ix_magic_link_tokens_user_id", "magic_link_tokens", ["user_id"])
    op.create_index("ix_magic_link_tokens_email_normalized", "magic_link_tokens", ["email_normalized"])
    op.create_index("ix_magic_link_tokens_token_hash", "magic_link_tokens", ["token_hash"])

    op.create_table(
        "password_reset_rate_limits",
        sa.Column("rate_limit_key", sa.Text(), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_password_reset_rate_limits_expires_at", "password_reset_rate_limits", ["expires_at"])

    op.create_table(
        "legal_entities",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("tax_id", sa.Text(), nullable=True),
        sa.Column("registration_id", sa.Text(), nullable=True),
        sa.Column("legal_address", sa.Text(), nullable=False),
        sa.Column("support_email", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("id", "tenant_id", "region", name="uq_legal_entities_id_tenant_region"),
    )
    op.create_index("ix_legal_entities_tenant_id", "legal_entities", ["tenant_id"])
    op.create_index("ix_legal_entities_region", "legal_entities", ["region"])
    op.create_index("ix_legal_entities_status", "legal_entities", ["status"])
    op.create_index(
        "ix_legal_entities_tenant_region_status",
        "legal_entities",
        ["tenant_id", "region", "status"],
    )

    op.create_table(
        "document_versions",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("legal_entity_id", UUID_TYPE, nullable=False),
        sa.Column("doc_type", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url_path", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("requires_acceptance", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["legal_entity_id", "tenant_id", "region"],
            ["legal_entities.id", "legal_entities.tenant_id", "legal_entities.region"],
            name="fk_document_versions_legal_entity_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "region",
            "doc_type",
            "version",
            name="uq_document_versions_tenant_region_doc_type_version",
        ),
        sa.UniqueConstraint("id", "tenant_id", "region", name="uq_document_versions_id_tenant_region"),
    )
    op.create_index("ix_document_versions_tenant_id", "document_versions", ["tenant_id"])
    op.create_index("ix_document_versions_region", "document_versions", ["region"])
    op.create_index("ix_document_versions_legal_entity_id", "document_versions", ["legal_entity_id"])
    op.create_index("ix_document_versions_doc_type", "document_versions", ["doc_type"])
    op.create_index("ix_document_versions_is_active", "document_versions", ["is_active"])
    op.create_index(
        "uq_document_versions_active_doc",
        "document_versions",
        ["tenant_id", "region", "doc_type"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )
    op.create_index(
        "ix_document_versions_region_is_active",
        "document_versions",
        ["region", "is_active"],
    )

    op.create_table(
        "legal_acceptance_events",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("user_id", UUID_TYPE, nullable=False),
        sa.Column("external_billing_account_id", sa.Text(), nullable=True),
        sa.Column("billing_offer_id", sa.Text(), nullable=True),
        sa.Column("accepted_commercial_fingerprint", sa.Text(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("ip", IP_TYPE, nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["user_id", "tenant_id", "region"],
            ["users.id", "users.tenant_id", "users.region"],
            name="fk_legal_acceptance_events_user_scope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "(external_billing_account_id IS NULL AND billing_offer_id IS NULL "
            "AND accepted_commercial_fingerprint IS NULL) OR "
            "(external_billing_account_id IS NOT NULL AND trim(external_billing_account_id) <> '' "
            "AND billing_offer_id IS NOT NULL AND trim(billing_offer_id) <> '' "
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
    op.create_index("ix_legal_acceptance_events_tenant_id", "legal_acceptance_events", ["tenant_id"])
    op.create_index("ix_legal_acceptance_events_region", "legal_acceptance_events", ["region"])
    op.create_index("ix_legal_acceptance_events_user_id", "legal_acceptance_events", ["user_id"])
    op.create_index("ix_legal_acceptance_events_accepted_at", "legal_acceptance_events", ["accepted_at"])

    op.create_table(
        "document_acceptances",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("legal_acceptance_event_id", UUID_TYPE, nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("user_id", UUID_TYPE, nullable=False),
        sa.Column("document_version_id", UUID_TYPE, nullable=False),
        sa.Column("acceptance_kind", sa.Text(), nullable=False),
        sa.Column("acceptance_text_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["legal_acceptance_event_id", "tenant_id", "region", "user_id"],
            [
                "legal_acceptance_events.id",
                "legal_acceptance_events.tenant_id",
                "legal_acceptance_events.region",
                "legal_acceptance_events.user_id",
            ],
            name="fk_document_acceptances_event_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "tenant_id", "region"],
            ["document_versions.id", "document_versions.tenant_id", "document_versions.region"],
            name="fk_document_acceptances_document_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "legal_acceptance_event_id",
            "document_version_id",
            name="uq_document_acceptances_event_document",
        ),
    )
    op.create_index(
        "ix_document_acceptances_legal_acceptance_event_id",
        "document_acceptances",
        ["legal_acceptance_event_id"],
    )
    op.create_index("ix_document_acceptances_tenant_id", "document_acceptances", ["tenant_id"])
    op.create_index("ix_document_acceptances_region", "document_acceptances", ["region"])
    op.create_index("ix_document_acceptances_user_id", "document_acceptances", ["user_id"])
    op.create_index("ix_document_acceptances_document_version_id", "document_acceptances", ["document_version_id"])


def _seed_configured_contour_and_legal_data() -> None:
    legal_published_at = datetime(2026, 7, 11, tzinfo=timezone.utc)
    legal_entity_id = UUID("44444444-4444-4444-8444-444444444444")

    op.bulk_insert(
        sa.table(
            "regions",
            sa.column("code", sa.Text()),
            sa.column("name", sa.Text()),
            sa.column("residency_zone", sa.Text()),
            sa.column("default_currency", sa.String(length=3)),
            sa.column("default_locale", sa.Text()),
            sa.column("status", sa.Text()),
        ),
        [
            {
                "code": "ru",
                "name": "Russia",
                "residency_zone": "russia",
                "default_currency": "RUB",
                "default_locale": "ru-RU",
                "status": "active",
            }
        ],
    )
    op.bulk_insert(
        sa.table(
            "country_region_rules",
            sa.column("id", UUID_TYPE),
            sa.column("country_code", sa.String(length=2)),
            sa.column("region", sa.Text()),
            sa.column("market_enabled", sa.Boolean()),
            sa.column("strict_mismatch", sa.Boolean()),
            sa.column("default_document_set", sa.Text()),
        ),
        [
            {
                "id": UUID("11111111-1111-4111-8111-111111111111"),
                "country_code": "RU",
                "region": "ru",
                "market_enabled": True,
                "strict_mismatch": True,
                "default_document_set": "ru_ip_v1",
            }
        ],
    )
    op.bulk_insert(
        sa.table(
            "legal_entities",
            sa.column("id", UUID_TYPE),
            sa.column("tenant_id", sa.Text()),
            sa.column("region", sa.Text()),
            sa.column("name", sa.Text()),
            sa.column("entity_type", sa.Text()),
            sa.column("tax_id", sa.Text()),
            sa.column("registration_id", sa.Text()),
            sa.column("legal_address", sa.Text()),
            sa.column("support_email", sa.Text()),
            sa.column("status", sa.Text()),
        ),
        [
            {
                "id": legal_entity_id,
                "tenant_id": "anytoolai",
                "region": "ru",
                "name": "ИП Говоров Роман Стальевич",
                "entity_type": "individual_entrepreneur",
                "tax_id": "143509640374",
                "registration_id": "314547633100101",
                "legal_address": "630091 , Новосибирская область, г. Новосибирск",
                "support_email": "support@any-tool-ai.ru",
                "status": "active",
            }
        ],
    )
    document_table = sa.table(
        "document_versions",
        sa.column("id", UUID_TYPE),
        sa.column("tenant_id", sa.Text()),
        sa.column("region", sa.Text()),
        sa.column("legal_entity_id", UUID_TYPE),
        sa.column("doc_type", sa.Text()),
        sa.column("version", sa.Text()),
        sa.column("title", sa.Text()),
        sa.column("url_path", sa.Text()),
        sa.column("content_hash", sa.Text()),
        sa.column("published_at", sa.DateTime(timezone=True)),
        sa.column("effective_from", sa.DateTime(timezone=True)),
        sa.column("is_active", sa.Boolean()),
        sa.column("requires_acceptance", sa.Boolean()),
    )
    documents = [
        {
            "id": UUID("55555555-5555-4555-8555-555555555501"),
            "doc_type": "privacy",
            "version": "2026-07-11",
            "title": "Политика в отношении обработки персональных данных",
            "url_path": "/ru/privacy",
            "content_hash": "sha256:8abfaa129649d2023d05e96bbb26944ccc83866c20bccb24140b946def4186e8",
            "requires_acceptance": True,
        },
        {
            "id": UUID("55555555-5555-4555-8555-555555555502"),
            "doc_type": "pd_consent",
            "version": "2026-07-11",
            "title": "Согласие на обработку персональных данных",
            "url_path": "/ru/consent-personal-data",
            "content_hash": "sha256:331bb599a9ccc06760050f95147b4ebf43daaa418a2480a04108663f44192984",
            "requires_acceptance": True,
        },
        {
            "id": UUID("55555555-5555-4555-8555-555555555503"),
            "doc_type": "offer",
            "version": "2026-07-11",
            "title": "Публичная оферта на оказание услуг",
            "url_path": "/ru/offer",
            "content_hash": "sha256:82c2fc6c92c59f163254e39bd1bb344a99912ad14c81d204d9097c8ad683a749",
            "requires_acceptance": True,
        },
        {
            "id": UUID("55555555-5555-4555-8555-555555555504"),
            "doc_type": "cancellation",
            "version": "2026-07-11",
            "title": "Условия отмены подписки и возврата денежных средств",
            "url_path": "/ru/cancellation",
            "content_hash": "sha256:92345654cf4bbc55be641da0d60c1dc547c60e86f7ecfc01df63a0a10aed0c2a",
            "requires_acceptance": False,
        },
        {
            "id": UUID("55555555-5555-4555-8555-555555555505"),
            "doc_type": "cookies",
            "version": "2026-07-11",
            "title": "Политика использования файлов cookie",
            "url_path": "/ru/cookies",
            "content_hash": "sha256:b571f0c42920a79ce10119ef1cd8bd2ba8710ba4328cff06f65753bf15195115",
            "requires_acceptance": False,
        },
        {
            "id": UUID("55555555-5555-4555-8555-555555555506"),
            "doc_type": "security",
            "version": "2026-07-11",
            "title": "Политика информационной безопасности",
            "url_path": "/ru/security",
            "content_hash": "sha256:9893aff188347b951663be409e827a7cb777fade5af1ceade11ab7f25bb7b8da",
            "requires_acceptance": False,
        },
    ]
    for document in documents:
        document.update(
            {
                "tenant_id": "anytoolai",
                "region": "ru",
                "legal_entity_id": legal_entity_id,
                "published_at": legal_published_at,
                "effective_from": legal_published_at,
                "is_active": True,
            }
        )
    op.bulk_insert(document_table, documents)


def _create_projection_and_purchase_tables() -> None:
    op.create_table(
        "capability_manifest_projections",
        sa.Column("projection_id", UUID_TYPE, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("manifest_version", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_complete_sync_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("manifest_document", JSONB_TYPE, nullable=False),
        sa.UniqueConstraint("tenant_id", "region", name="uq_capability_manifest_projections_scope"),
    )
    op.create_index(
        "ix_capability_manifest_projections_manifest_version",
        "capability_manifest_projections",
        ["manifest_version"],
    )
    op.create_index(
        "ix_capability_manifest_projections_last_sync",
        "capability_manifest_projections",
        ["last_complete_sync_at"],
    )

    op.create_table(
        "external_billing_catalog_projections",
        sa.Column("projection_id", UUID_TYPE, primary_key=True),
        sa.Column("external_billing_account_id", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("catalog_version", sa.Text(), nullable=True),
        sa.Column("catalog_digest", sa.Text(), nullable=False),
        sa.Column("last_complete_sync_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("catalog_document", JSONB_TYPE, nullable=False),
        sa.UniqueConstraint(
            "external_billing_account_id",
            name="uq_external_billing_catalog_projections_account",
        ),
    )
    op.create_index(
        "ix_external_billing_catalog_projections_catalog_version",
        "external_billing_catalog_projections",
        ["catalog_version"],
    )
    op.create_index(
        "ix_external_billing_catalog_projections_catalog_digest",
        "external_billing_catalog_projections",
        ["catalog_digest"],
    )
    op.create_index(
        "ix_external_billing_catalog_projections_last_sync",
        "external_billing_catalog_projections",
        ["last_complete_sync_at"],
    )

    op.create_table(
        "commercial_mapping_revisions",
        sa.Column("mapping_revision_id", UUID_TYPE, primary_key=True),
        sa.Column("external_billing_account_id", sa.Text(), nullable=False),
        sa.Column("billing_offer_id", sa.Text(), nullable=False),
        sa.Column("revision_number", sa.BigInteger(), nullable=False),
        sa.Column("manifest_version", sa.Text(), nullable=False),
        sa.Column("catalog_version", sa.Text(), nullable=True),
        sa.Column("catalog_digest", sa.Text(), nullable=False),
        sa.Column("mapping_schema_version", sa.Text(), nullable=False),
        sa.Column("mapping_document", JSONB_TYPE, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_by_principal", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "mapping_revision_id",
            "external_billing_account_id",
            name="uq_commercial_mapping_revisions_id_account",
        ),
        sa.UniqueConstraint(
            "mapping_revision_id",
            "external_billing_account_id",
            "billing_offer_id",
            name="uq_commercial_mapping_revisions_id_account_offer",
        ),
        sa.UniqueConstraint(
            "external_billing_account_id",
            "billing_offer_id",
            "revision_number",
            name="uq_commercial_mapping_revisions_account_offer_revision",
        ),
        sa.CheckConstraint(
            "revision_number > 0",
            name="ck_commercial_mapping_revisions_revision_positive",
        ),
        sa.CheckConstraint(
            "trim(mapping_schema_version) <> ''",
            name="ck_commercial_mapping_revisions_schema_nonempty",
        ),
    )
    op.create_index(
        "ix_commercial_mapping_revisions_publication",
        "commercial_mapping_revisions",
        ["external_billing_account_id", "billing_offer_id", "published_at"],
    )
    op.create_index(
        "ix_commercial_mapping_revisions_manifest",
        "commercial_mapping_revisions",
        ["external_billing_account_id", "billing_offer_id", "manifest_version"],
    )
    op.create_index(
        "ix_commercial_mapping_revisions_principal",
        "commercial_mapping_revisions",
        ["published_by_principal"],
    )

    op.create_table(
        "external_billing_customers",
        sa.Column("customer_id", UUID_TYPE, primary_key=True),
        sa.Column("external_billing_account_id", sa.Text(), nullable=False),
        sa.Column("user_id", UUID_TYPE, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("billing_customer_key", sa.Text(), nullable=False),
        sa.Column("provider_customer_id", sa.Text(), nullable=True),
        sa.Column("binding_state", sa.Text(), nullable=False),
        sa.Column(
            "binding_updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "customer_id",
            "external_billing_account_id",
            "user_id",
            name="uq_external_billing_customers_id_account_user",
        ),
        sa.UniqueConstraint(
            "external_billing_account_id",
            "user_id",
            name="uq_external_billing_customers_account_user",
        ),
        sa.UniqueConstraint(
            "billing_customer_key",
            name="uq_external_billing_customers_billing_customer_key",
        ),
        sa.CheckConstraint(
            "trim(billing_customer_key) <> ''",
            name="ck_external_billing_customers_key_nonempty",
        ),
        sa.CheckConstraint(
            "binding_state IN ('unbound', 'bound', 'identity_conflict')",
            name="ck_external_billing_customers_binding_state",
        ),
    )
    op.create_index(
        "ix_external_billing_customers_provider_customer_id",
        "external_billing_customers",
        ["provider_customer_id"],
    )
    op.create_index(
        "ix_external_billing_customers_binding_state",
        "external_billing_customers",
        ["binding_state"],
    )

    op.create_table(
        "purchase_intents",
        sa.Column("purchase_intent_id", UUID_TYPE, primary_key=True),
        sa.Column("user_id", UUID_TYPE, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("external_billing_account_id", sa.Text(), nullable=False),
        sa.Column("customer_id", UUID_TYPE, nullable=False),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("billing_offer_id", sa.Text(), nullable=False),
        sa.Column("mapping_revision_id", UUID_TYPE, nullable=False),
        sa.Column("accepted_commercial_fingerprint", sa.Text(), nullable=False),
        sa.Column("client_idempotency_key", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("accepted_snapshot_schema_version", sa.Text(), nullable=False),
        sa.Column("accepted_snapshot", JSONB_TYPE, nullable=False),
        sa.Column("legal_acceptance_event_id", UUID_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "state_updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["customer_id", "external_billing_account_id", "user_id"],
            [
                "external_billing_customers.customer_id",
                "external_billing_customers.external_billing_account_id",
                "external_billing_customers.user_id",
            ],
            name="fk_purchase_intents_customer_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["mapping_revision_id", "external_billing_account_id", "billing_offer_id"],
            [
                "commercial_mapping_revisions.mapping_revision_id",
                "commercial_mapping_revisions.external_billing_account_id",
                "commercial_mapping_revisions.billing_offer_id",
            ],
            name="fk_purchase_intents_mapping_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "legal_acceptance_event_id",
                "user_id",
                "external_billing_account_id",
                "billing_offer_id",
                "accepted_commercial_fingerprint",
            ],
            [
                "legal_acceptance_events.id",
                "legal_acceptance_events.user_id",
                "legal_acceptance_events.external_billing_account_id",
                "legal_acceptance_events.billing_offer_id",
                "legal_acceptance_events.accepted_commercial_fingerprint",
            ],
            name="fk_purchase_intents_legal_evidence",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "external_billing_account_id",
            "user_id",
            "client_idempotency_key",
            name="uq_purchase_intents_client_idempotency",
        ),
        sa.UniqueConstraint(
            "purchase_intent_id",
            "customer_id",
            name="uq_purchase_intents_id_customer",
        ),
        sa.UniqueConstraint(
            "purchase_intent_id",
            "external_billing_account_id",
            "user_id",
            "product_id",
            name="uq_purchase_intents_id_account_user_product",
        ),
        sa.UniqueConstraint(
            "purchase_intent_id",
            "customer_id",
            "external_billing_account_id",
            "user_id",
            "product_id",
            "mapping_revision_id",
            name="uq_purchase_intents_full_scope",
        ),
        sa.CheckConstraint(
            "trim(accepted_commercial_fingerprint) <> ''",
            name="ck_purchase_intents_fingerprint_nonempty",
        ),
        sa.CheckConstraint(
            "trim(client_idempotency_key) <> ''",
            name="ck_purchase_intents_idempotency_nonempty",
        ),
        sa.CheckConstraint(
            "trim(accepted_snapshot_schema_version) <> ''",
            name="ck_purchase_intents_snapshot_schema_nonempty",
        ),
        sa.CheckConstraint(
            "state IN ('created', 'preparing', 'awaiting_external_result', 'linked', "
            "'resolved_no_external_effect', 'failed_before_external_effect', 'manual_review')",
            name="ck_purchase_intents_state",
        ),
    )
    op.create_index("ix_purchase_intents_user_product", "purchase_intents", ["user_id", "product_id"])
    op.create_index(
        "ix_purchase_intents_account_offer",
        "purchase_intents",
        ["external_billing_account_id", "billing_offer_id"],
    )
    op.create_index(
        "ix_purchase_intents_customer_purchase",
        "purchase_intents",
        ["customer_id", "purchase_intent_id"],
    )
    op.create_index("ix_purchase_intents_mapping_revision", "purchase_intents", ["mapping_revision_id"])
    op.create_index(
        "ix_purchase_intents_commercial_fingerprint",
        "purchase_intents",
        ["accepted_commercial_fingerprint"],
    )
    op.create_index("ix_purchase_intents_state", "purchase_intents", ["state"])
    op.create_index("ix_purchase_intents_state_updated_at", "purchase_intents", ["state", "state_updated_at"])

    op.create_table(
        "external_create_operations",
        sa.Column("create_operation_id", UUID_TYPE, primary_key=True),
        sa.Column("operation_kind", sa.Text(), nullable=False),
        sa.Column(
            "customer_id",
            UUID_TYPE,
            sa.ForeignKey("external_billing_customers.customer_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("purchase_intent_id", UUID_TYPE, nullable=True),
        sa.Column("request_correlation_key", sa.Text(), nullable=False),
        sa.Column("operation_state", sa.Text(), nullable=False),
        sa.Column("unknown_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unknown_recovery_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_hint_schema_version", sa.Text(), nullable=True),
        sa.Column("recovery_hint_document", JSONB_TYPE, nullable=True),
        sa.Column("bound_external_object_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["purchase_intent_id", "customer_id"],
            ["purchase_intents.purchase_intent_id", "purchase_intents.customer_id"],
            name="fk_external_create_operations_purchase_customer",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "(operation_kind = 'customer' AND purchase_intent_id IS NULL) OR "
            "(operation_kind IN ('agreement', 'subscription') AND purchase_intent_id IS NOT NULL)",
            name="ck_external_create_operations_purchase_requirement",
        ),
        sa.CheckConstraint(
            "operation_kind IN ('customer', 'agreement', 'subscription')",
            name="ck_external_create_operations_kind",
        ),
        sa.CheckConstraint(
            "trim(request_correlation_key) <> ''",
            name="ck_external_create_operations_correlation_nonempty",
        ),
        sa.CheckConstraint(
            "(unknown_since IS NULL AND unknown_recovery_deadline_at IS NULL) OR "
            "(unknown_since IS NOT NULL AND unknown_recovery_deadline_at IS NOT NULL)",
            name="ck_external_create_operations_unknown_pair",
        ),
        sa.CheckConstraint(
            "unknown_recovery_deadline_at = unknown_since + interval '2 hours'",
            name="ck_external_create_operations_unknown_deadline",
        ),
        sa.CheckConstraint(
            "(recovery_hint_schema_version IS NULL AND recovery_hint_document IS NULL) OR "
            "(recovery_hint_schema_version IS NOT NULL AND recovery_hint_document IS NOT NULL)",
            name="ck_external_create_operations_recovery_hint_pair",
        ),
    )
    op.create_index(
        "uq_external_create_operations_unresolved_customer",
        "external_create_operations",
        ["customer_id"],
        unique=True,
        postgresql_where=sa.text("operation_kind = 'customer' AND resolved_at IS NULL"),
    )
    op.create_index(
        "ix_external_create_operations_customer_state",
        "external_create_operations",
        ["customer_id", "operation_state"],
    )
    op.create_index("ix_external_create_operations_purchase", "external_create_operations", ["purchase_intent_id"])
    op.create_index(
        "ix_external_create_operations_correlation",
        "external_create_operations",
        ["request_correlation_key"],
    )
    op.create_index(
        "ix_external_create_operations_unknown_deadline",
        "external_create_operations",
        ["unknown_recovery_deadline_at"],
    )
    op.create_index(
        "ix_external_create_operations_bound_object",
        "external_create_operations",
        ["bound_external_object_id"],
    )
    op.create_index(
        "ix_external_create_operations_recovery_scan",
        "external_create_operations",
        ["operation_state", "unknown_recovery_deadline_at", "updated_at"],
    )


def _create_reconciliation_tables() -> None:
    op.create_table(
        "billing_work_items",
        sa.Column("work_item_id", UUID_TYPE, primary_key=True),
        sa.Column("work_kind", sa.Text(), nullable=False),
        sa.Column("scope_kind", sa.Text(), nullable=False),
        sa.Column("scope_reference", sa.Text(), nullable=False),
        sa.Column("coalescing_key", sa.Text(), nullable=True),
        sa.Column("payload_schema_version", sa.Text(), nullable=False),
        sa.Column("payload_document", JSONB_TYPE, nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("work_state", sa.Text(), nullable=False),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_classification", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "trim(payload_schema_version) <> ''",
            name="ck_billing_work_items_payload_schema_nonempty",
        ),
        sa.CheckConstraint(
            "(lease_owner IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_billing_work_items_lease_pair",
        ),
    )
    op.create_index(
        "ix_billing_work_items_kind_state_due",
        "billing_work_items",
        ["work_kind", "work_state", "next_attempt_at"],
    )
    op.create_index("ix_billing_work_items_scope", "billing_work_items", ["scope_kind", "scope_reference"])
    op.create_index("ix_billing_work_items_coalescing_key", "billing_work_items", ["coalescing_key"])
    op.create_index(
        "ix_billing_work_items_priority_retry",
        "billing_work_items",
        ["work_state", "priority", "next_attempt_at"],
    )
    op.create_index("ix_billing_work_items_lease_expiry", "billing_work_items", ["lease_expires_at"])
    op.create_index(
        "ix_billing_work_items_claim_scan",
        "billing_work_items",
        ["work_state", "lease_expires_at", "priority", "next_attempt_at"],
    )
    op.create_index("ix_billing_work_items_kind_state", "billing_work_items", ["work_kind", "work_state"])

    op.create_table(
        "billing_product_access_scopes",
        sa.Column("access_scope_id", UUID_TYPE, primary_key=True),
        sa.Column("user_id", UUID_TYPE, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("primary_subscription_id", UUID_TYPE, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "access_scope_id",
            "user_id",
            "product_id",
            name="uq_billing_product_access_scopes_id_user_product",
        ),
        sa.UniqueConstraint(
            "user_id",
            "product_id",
            name="uq_billing_product_access_scopes_user_product",
        ),
    )
    op.create_index(
        "ix_billing_product_access_scopes_primary_subscription",
        "billing_product_access_scopes",
        ["primary_subscription_id"],
    )

    op.create_table(
        "external_subscriptions",
        sa.Column("subscription_id", UUID_TYPE, primary_key=True),
        sa.Column("external_billing_account_id", sa.Text(), nullable=False),
        sa.Column("customer_id", UUID_TYPE, nullable=False),
        sa.Column("user_id", UUID_TYPE, nullable=False),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("purchase_intent_id", UUID_TYPE, nullable=True),
        sa.Column("mapping_revision_id", UUID_TYPE, nullable=True),
        sa.Column("external_subscription_id", sa.Text(), nullable=True),
        sa.Column("external_agreement_id", sa.Text(), nullable=True),
        sa.Column("lifecycle_status", sa.Text(), nullable=False),
        sa.Column("financial_access_status", sa.Text(), nullable=False),
        sa.Column("commercial_access_status", sa.Text(), nullable=False),
        sa.Column("last_authoritative_read_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("projection_valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reconciliation_lease_owner", sa.Text(), nullable=True),
        sa.Column("reconciliation_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciliation_fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("latest_observation_id", UUID_TYPE, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "subscription_id",
            "product_id",
            name="uq_external_subscriptions_id_product",
        ),
        sa.UniqueConstraint(
            "subscription_id",
            "user_id",
            "product_id",
            name="uq_external_subscriptions_id_user_product",
        ),
        sa.UniqueConstraint(
            "subscription_id",
            "external_billing_account_id",
            "user_id",
            "product_id",
            name="uq_external_subscriptions_id_account_user_product",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id", "external_billing_account_id", "user_id"],
            [
                "external_billing_customers.customer_id",
                "external_billing_customers.external_billing_account_id",
                "external_billing_customers.user_id",
            ],
            name="fk_external_subscriptions_customer_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "purchase_intent_id",
                "customer_id",
                "external_billing_account_id",
                "user_id",
                "product_id",
                "mapping_revision_id",
            ],
            [
                "purchase_intents.purchase_intent_id",
                "purchase_intents.customer_id",
                "purchase_intents.external_billing_account_id",
                "purchase_intents.user_id",
                "purchase_intents.product_id",
                "purchase_intents.mapping_revision_id",
            ],
            name="fk_external_subscriptions_purchase_provenance",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["mapping_revision_id", "external_billing_account_id"],
            [
                "commercial_mapping_revisions.mapping_revision_id",
                "commercial_mapping_revisions.external_billing_account_id",
            ],
            name="fk_external_subscriptions_mapping_scope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "purchase_intent_id IS NULL OR mapping_revision_id IS NOT NULL",
            name="ck_external_subscriptions_purchase_mapping",
        ),
        sa.CheckConstraint(
            "lifecycle_status IN ('active', 'inactive', 'ended')",
            name="ck_external_subscriptions_lifecycle_status",
        ),
        sa.CheckConstraint(
            "financial_access_status IN ('allowed', 'blocked')",
            name="ck_external_subscriptions_financial_access_status",
        ),
        sa.CheckConstraint(
            "commercial_access_status IN ('eligible', 'ineligible')",
            name="ck_external_subscriptions_commercial_access_status",
        ),
        sa.CheckConstraint(
            "(reconciliation_lease_owner IS NULL AND reconciliation_lease_expires_at IS NULL) OR "
            "(reconciliation_lease_owner IS NOT NULL AND reconciliation_lease_expires_at IS NOT NULL)",
            name="ck_external_subscriptions_reconciliation_lease_pair",
        ),
        sa.CheckConstraint(
            "reconciliation_fencing_token >= 0",
            name="ck_external_subscriptions_fencing_token_nonnegative",
        ),
    )
    op.create_index(
        "uq_external_subscriptions_purchase_intent",
        "external_subscriptions",
        ["purchase_intent_id"],
        unique=True,
        postgresql_where=sa.text("purchase_intent_id IS NOT NULL"),
    )
    op.create_index(
        "ix_external_subscriptions_account_customer",
        "external_subscriptions",
        ["external_billing_account_id", "customer_id"],
    )
    op.create_index(
        "ix_external_subscriptions_user_product_status",
        "external_subscriptions",
        ["user_id", "product_id", "lifecycle_status"],
    )
    op.create_index(
        "ix_external_subscriptions_customer_product_status",
        "external_subscriptions",
        ["customer_id", "product_id", "lifecycle_status"],
    )
    op.create_index(
        "ix_external_subscriptions_purchase_provenance",
        "external_subscriptions",
        ["purchase_intent_id", "customer_id", "mapping_revision_id"],
    )
    op.create_index(
        "ix_external_subscriptions_mapping_provenance",
        "external_subscriptions",
        ["mapping_revision_id", "external_billing_account_id"],
    )
    op.create_index("ix_external_subscriptions_external_id", "external_subscriptions", ["external_subscription_id"])
    op.create_index("ix_external_subscriptions_agreement_id", "external_subscriptions", ["external_agreement_id"])
    op.create_index("ix_external_subscriptions_lifecycle_status", "external_subscriptions", ["lifecycle_status"])
    op.create_index(
        "ix_external_subscriptions_financial_status",
        "external_subscriptions",
        ["financial_access_status"],
    )
    op.create_index(
        "ix_external_subscriptions_commercial_status",
        "external_subscriptions",
        ["commercial_access_status"],
    )
    op.create_index("ix_external_subscriptions_last_read", "external_subscriptions", ["last_authoritative_read_at"])
    op.create_index("ix_external_subscriptions_valid_until", "external_subscriptions", ["projection_valid_until"])
    op.create_index(
        "ix_external_subscriptions_lease_expiry",
        "external_subscriptions",
        ["reconciliation_lease_expires_at"],
    )
    op.create_index(
        "ix_external_subscriptions_reconciliation_claim",
        "external_subscriptions",
        ["projection_valid_until", "reconciliation_lease_expires_at"],
    )
    op.create_index(
        "ix_external_subscriptions_latest_observation",
        "external_subscriptions",
        ["latest_observation_id"],
    )

    op.create_table(
        "billing_state_observations",
        sa.Column("observation_id", UUID_TYPE, primary_key=True),
        sa.Column("observation_kind", sa.Text(), nullable=False),
        sa.Column("external_billing_account_id", sa.Text(), nullable=False),
        sa.Column("user_id", UUID_TYPE, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("product_id", sa.Text(), nullable=True),
        sa.Column("access_scope_id", UUID_TYPE, nullable=True),
        sa.Column("subscription_id", UUID_TYPE, nullable=True),
        sa.Column("purchase_intent_id", UUID_TYPE, nullable=True),
        sa.Column(
            "work_item_id",
            UUID_TYPE,
            sa.ForeignKey("billing_work_items.work_item_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("basis_observation_id", UUID_TYPE, nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_schema_version", sa.Text(), nullable=False),
        sa.Column("evidence_document", JSONB_TYPE, nullable=False),
        sa.Column("completeness_classification", sa.Text(), nullable=False),
        sa.Column("result_classification", sa.Text(), nullable=False),
        sa.Column("resulting_access_revision", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "observation_id",
            "access_scope_id",
            name="uq_billing_state_observations_id_scope",
        ),
        sa.UniqueConstraint(
            "observation_id",
            "subscription_id",
            name="uq_billing_state_observations_id_subscription",
        ),
        sa.ForeignKeyConstraint(
            ["access_scope_id", "user_id", "product_id"],
            [
                "billing_product_access_scopes.access_scope_id",
                "billing_product_access_scopes.user_id",
                "billing_product_access_scopes.product_id",
            ],
            name="fk_billing_state_observations_access_scope",
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
            name="fk_billing_state_observations_subscription_scope",
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
            name="fk_billing_state_observations_purchase_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["basis_observation_id", "access_scope_id"],
            [
                "billing_state_observations.observation_id",
                "billing_state_observations.access_scope_id",
            ],
            name="fk_billing_state_observations_basis_scope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "subscription_id IS NULL OR purchase_intent_id IS NULL",
            name="ck_billing_state_observations_provenance_exclusive",
        ),
        sa.CheckConstraint(
            "(access_scope_id IS NULL AND subscription_id IS NULL AND purchase_intent_id IS NULL) OR "
            "(user_id IS NOT NULL AND product_id IS NOT NULL)",
            name="ck_billing_state_observations_subject_shape",
        ),
        sa.CheckConstraint(
            "observation_kind IN ('authoritative_subscription_read', 'target_product_discovery', "
            "'primary_selection', 'deterministic_access_boundary')",
            name="ck_billing_state_observations_kind",
        ),
        sa.CheckConstraint(
            "(observation_kind <> 'authoritative_subscription_read' OR subscription_id IS NOT NULL) "
            "AND (observation_kind <> 'target_product_discovery' OR "
            "(user_id IS NOT NULL AND product_id IS NOT NULL AND access_scope_id IS NOT NULL)) "
            "AND (observation_kind <> 'primary_selection' OR "
            "(access_scope_id IS NOT NULL AND basis_observation_id IS NOT NULL)) "
            "AND (observation_kind <> 'deterministic_access_boundary' OR "
            "(access_scope_id IS NOT NULL AND subscription_id IS NOT NULL AND effective_at IS NOT NULL))",
            name="ck_billing_state_observations_kind_shape",
        ),
        sa.CheckConstraint(
            "trim(evidence_schema_version) <> ''",
            name="ck_billing_state_observations_evidence_schema_nonempty",
        ),
    )
    op.create_index(
        "ix_billing_state_observations_kind_time",
        "billing_state_observations",
        ["observation_kind", "observed_at"],
    )
    op.create_index(
        "ix_billing_state_observations_account_kind_time",
        "billing_state_observations",
        ["external_billing_account_id", "observation_kind", "observed_at"],
    )
    op.create_index(
        "ix_billing_state_observations_user_product_time",
        "billing_state_observations",
        ["user_id", "product_id", "observed_at"],
    )
    op.create_index(
        "ix_billing_state_observations_scope_time",
        "billing_state_observations",
        ["access_scope_id", "observed_at"],
    )
    op.create_index(
        "ix_billing_state_observations_subscription_time",
        "billing_state_observations",
        ["subscription_id", "observed_at"],
    )
    op.create_index(
        "ix_billing_state_observations_purchase_time",
        "billing_state_observations",
        ["purchase_intent_id", "observed_at"],
    )
    op.create_index("ix_billing_state_observations_work_item", "billing_state_observations", ["work_item_id"])
    op.create_index("ix_billing_state_observations_basis", "billing_state_observations", ["basis_observation_id"])
    op.create_index("ix_billing_state_observations_effective_at", "billing_state_observations", ["effective_at"])
    op.create_index(
        "ix_billing_state_observations_completeness",
        "billing_state_observations",
        ["completeness_classification"],
    )
    op.create_index("ix_billing_state_observations_result", "billing_state_observations", ["result_classification"])
    op.create_index(
        "ix_billing_state_observations_scope_revision",
        "billing_state_observations",
        ["access_scope_id", "resulting_access_revision"],
    )

    op.create_foreign_key(
        "fk_billing_product_access_scopes_primary_subscription",
        "billing_product_access_scopes",
        "external_subscriptions",
        ["primary_subscription_id", "user_id", "product_id"],
        ["subscription_id", "user_id", "product_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_external_subscriptions_latest_observation",
        "external_subscriptions",
        "billing_state_observations",
        ["latest_observation_id", "subscription_id"],
        ["observation_id", "subscription_id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "purchased_allowances",
        sa.Column("allowance_id", UUID_TYPE, primary_key=True),
        sa.Column("subscription_id", UUID_TYPE, nullable=False),
        sa.Column("source_component_id", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("metric_key", sa.Text(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("provider_cycle_key", sa.Text(), nullable=True),
        sa.Column("provider_cycle_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_cycle_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["subscription_id", "product_id"],
            ["external_subscriptions.subscription_id", "external_subscriptions.product_id"],
            name="fk_purchased_allowances_subscription_product",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_purchased_allowances_quantity_nonnegative"),
        sa.CheckConstraint(
            "(provider_cycle_start IS NULL AND provider_cycle_end IS NULL) OR "
            "(provider_cycle_start IS NOT NULL AND provider_cycle_end IS NOT NULL)",
            name="ck_purchased_allowances_provider_cycle_pair",
        ),
        sa.CheckConstraint("period_start < period_end", name="ck_purchased_allowances_period_order"),
    )
    op.create_index("ix_purchased_allowances_provider_cycle_key", "purchased_allowances", ["provider_cycle_key"])
    op.create_index(
        "ix_purchased_allowances_subscription_cycle",
        "purchased_allowances",
        ["subscription_id", "provider_cycle_key"],
    )
    op.create_index(
        "ix_purchased_allowances_subscription_component_cycle",
        "purchased_allowances",
        ["subscription_id", "source_component_id", "provider_cycle_key"],
    )
    op.create_index(
        "ix_purchased_allowances_product_metric",
        "purchased_allowances",
        ["product_id", "metric_key"],
    )


def _create_delivery_review_and_access_tables() -> None:
    op.create_table(
        "external_billing_webhook_deliveries",
        sa.Column("delivery_id", UUID_TYPE, primary_key=True),
        sa.Column("external_billing_account_id", sa.Text(), nullable=False),
        sa.Column("provider_event_id", sa.Text(), nullable=True),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("correlation_schema_version", sa.Text(), nullable=False),
        sa.Column("correlation_document", JSONB_TYPE, nullable=False),
        sa.Column("evidence_schema_version", sa.Text(), nullable=False),
        sa.Column("evidence_document", JSONB_TYPE, nullable=False),
        sa.Column("processing_state", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_classification", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "trim(payload_hash) <> ''",
            name="ck_external_billing_webhook_deliveries_hash_nonempty",
        ),
        sa.CheckConstraint(
            "trim(correlation_schema_version) <> ''",
            name="ck_external_billing_webhook_deliveries_corr_schema_nonempty",
        ),
        sa.CheckConstraint(
            "trim(evidence_schema_version) <> ''",
            name="ck_external_billing_webhook_deliveries_evidence_schema_nonempty",
        ),
    )
    op.create_index(
        "ix_external_billing_webhook_deliveries_account_received",
        "external_billing_webhook_deliveries",
        ["external_billing_account_id", "received_at"],
    )
    op.create_index(
        "ix_external_billing_webhook_deliveries_processing_received",
        "external_billing_webhook_deliveries",
        ["processing_state", "received_at"],
    )
    op.create_index(
        "ix_external_billing_webhook_deliveries_received_at",
        "external_billing_webhook_deliveries",
        ["received_at"],
    )
    op.create_index(
        "ix_external_billing_webhook_deliveries_provider_event",
        "external_billing_webhook_deliveries",
        ["provider_event_id"],
    )
    op.create_index(
        "ix_external_billing_webhook_deliveries_payload_hash",
        "external_billing_webhook_deliveries",
        ["payload_hash"],
    )

    op.create_table(
        "manual_review_cases",
        sa.Column("review_case_id", UUID_TYPE, primary_key=True),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("scope_kind", sa.Text(), nullable=False),
        sa.Column("scope_reference", sa.Text(), nullable=False),
        sa.Column("evidence_schema_version", sa.Text(), nullable=False),
        sa.Column("evidence_document", JSONB_TYPE, nullable=False),
        sa.Column("case_state", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_principal", sa.Text(), nullable=True),
        sa.Column("resolution_schema_version", sa.Text(), nullable=True),
        sa.Column("resolution_document", JSONB_TYPE, nullable=True),
        sa.CheckConstraint(
            "trim(evidence_schema_version) <> ''",
            name="ck_manual_review_cases_evidence_schema_nonempty",
        ),
    )
    op.create_index("ix_manual_review_cases_reason_state", "manual_review_cases", ["reason_code", "case_state"])
    op.create_index("ix_manual_review_cases_scope", "manual_review_cases", ["scope_kind", "scope_reference"])
    op.create_index("ix_manual_review_cases_state", "manual_review_cases", ["case_state"])
    op.create_index("ix_manual_review_cases_state_created", "manual_review_cases", ["case_state", "created_at"])
    op.create_index("ix_manual_review_cases_resolved_by", "manual_review_cases", ["resolved_by_principal"])

    op.create_table(
        "paid_access_states",
        sa.Column("paid_access_state_id", UUID_TYPE, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column("user_id", UUID_TYPE, nullable=False),
        sa.Column("access_revision", sa.BigInteger(), nullable=False),
        sa.Column("effective_state_schema_version", sa.Text(), nullable=False),
        sa.Column("effective_state_document", JSONB_TYPE, nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id", "tenant_id", "region"],
            ["users.id", "users.tenant_id", "users.region"],
            name="fk_paid_access_states_user_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "region",
            "user_id",
            name="uq_paid_access_states_tenant_region_user",
        ),
    )

    op.create_table(
        "access_invalidation_outbox",
        sa.Column("outbox_id", UUID_TYPE, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column("user_id", UUID_TYPE, nullable=False),
        sa.Column("pending_revision", sa.BigInteger(), nullable=False),
        sa.Column("delivered_revision", sa.BigInteger(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error_classification", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["user_id", "tenant_id", "region"],
            ["users.id", "users.tenant_id", "users.region"],
            name="fk_access_invalidation_outbox_user_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "region",
            "user_id",
            name="uq_access_invalidation_outbox_tenant_region_user",
        ),
        sa.CheckConstraint(
            "pending_revision > 0",
            name="ck_access_invalidation_outbox_pending_revision_positive",
        ),
        sa.CheckConstraint(
            "pending_revision >= delivered_revision",
            name="ck_access_invalidation_outbox_revision_order",
        ),
    )
    op.create_index(
        "ix_access_invalidation_outbox_next_attempt_at",
        "access_invalidation_outbox",
        ["next_attempt_at"],
    )


def _create_immutability_guards() -> None:
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
        "CREATE TRIGGER trg_guard_legal_acceptance_event_evidence "
        "BEFORE UPDATE OR DELETE ON legal_acceptance_events FOR EACH ROW "
        "EXECUTE FUNCTION guard_legal_acceptance_event_evidence()"
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
        "CREATE TRIGGER trg_guard_document_acceptance_evidence "
        "BEFORE UPDATE OR DELETE ON document_acceptances FOR EACH ROW "
        "EXECUTE FUNCTION guard_document_acceptance_evidence()"
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION guard_document_version_material()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'published legal document versions cannot be deleted';
                END IF;

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
        "CREATE TRIGGER trg_guard_document_version_material "
        "BEFORE UPDATE OR DELETE ON document_versions FOR EACH ROW "
        "EXECUTE FUNCTION guard_document_version_material()"
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION guard_external_billing_customer_identity()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'external billing customer slots cannot be deleted';
                END IF;

                IF NEW.customer_id IS DISTINCT FROM OLD.customer_id
                    OR NEW.external_billing_account_id IS DISTINCT FROM OLD.external_billing_account_id
                    OR NEW.user_id IS DISTINCT FROM OLD.user_id
                    OR NEW.billing_customer_key IS DISTINCT FROM OLD.billing_customer_key
                    OR NEW.created_at IS DISTINCT FROM OLD.created_at
                THEN
                    RAISE EXCEPTION 'external billing customer identity is immutable';
                END IF;

                RETURN NEW;
            END
            $$
            """
        )
    )
    op.execute(
        "CREATE TRIGGER trg_guard_external_billing_customer_identity "
        "BEFORE UPDATE OR DELETE ON external_billing_customers FOR EACH ROW "
        "EXECUTE FUNCTION guard_external_billing_customer_identity()"
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION guard_commercial_mapping_revision()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'commercial mapping revisions are immutable';
            END
            $$
            """
        )
    )
    op.execute(
        "CREATE TRIGGER trg_guard_commercial_mapping_revision "
        "BEFORE UPDATE OR DELETE ON commercial_mapping_revisions FOR EACH ROW "
        "EXECUTE FUNCTION guard_commercial_mapping_revision()"
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION guard_purchase_intent_evidence()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'purchase intents cannot be deleted';
                END IF;

                IF NEW.purchase_intent_id IS DISTINCT FROM OLD.purchase_intent_id
                    OR NEW.user_id IS DISTINCT FROM OLD.user_id
                    OR NEW.external_billing_account_id IS DISTINCT FROM OLD.external_billing_account_id
                    OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
                    OR NEW.product_id IS DISTINCT FROM OLD.product_id
                    OR NEW.billing_offer_id IS DISTINCT FROM OLD.billing_offer_id
                    OR NEW.mapping_revision_id IS DISTINCT FROM OLD.mapping_revision_id
                    OR NEW.accepted_commercial_fingerprint IS DISTINCT FROM OLD.accepted_commercial_fingerprint
                    OR NEW.client_idempotency_key IS DISTINCT FROM OLD.client_idempotency_key
                    OR NEW.accepted_snapshot_schema_version IS DISTINCT FROM OLD.accepted_snapshot_schema_version
                    OR NEW.accepted_snapshot IS DISTINCT FROM OLD.accepted_snapshot
                    OR NEW.legal_acceptance_event_id IS DISTINCT FROM OLD.legal_acceptance_event_id
                    OR NEW.created_at IS DISTINCT FROM OLD.created_at
                THEN
                    RAISE EXCEPTION 'purchase intent accepted evidence is immutable';
                END IF;

                RETURN NEW;
            END
            $$
            """
        )
    )
    op.execute(
        "CREATE TRIGGER trg_guard_purchase_intent_evidence "
        "BEFORE UPDATE OR DELETE ON purchase_intents FOR EACH ROW "
        "EXECUTE FUNCTION guard_purchase_intent_evidence()"
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION guard_billing_state_observation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'billing state observations cannot be deleted';
                END IF;

                IF NEW.observation_id IS DISTINCT FROM OLD.observation_id
                    OR NEW.observation_kind IS DISTINCT FROM OLD.observation_kind
                    OR NEW.external_billing_account_id IS DISTINCT FROM OLD.external_billing_account_id
                    OR NEW.user_id IS DISTINCT FROM OLD.user_id
                    OR NEW.product_id IS DISTINCT FROM OLD.product_id
                    OR NEW.access_scope_id IS DISTINCT FROM OLD.access_scope_id
                    OR NEW.subscription_id IS DISTINCT FROM OLD.subscription_id
                    OR NEW.purchase_intent_id IS DISTINCT FROM OLD.purchase_intent_id
                    OR NEW.work_item_id IS DISTINCT FROM OLD.work_item_id
                    OR NEW.basis_observation_id IS DISTINCT FROM OLD.basis_observation_id
                    OR NEW.observed_at IS DISTINCT FROM OLD.observed_at
                    OR NEW.effective_at IS DISTINCT FROM OLD.effective_at
                    OR NEW.evidence_schema_version IS DISTINCT FROM OLD.evidence_schema_version
                    OR NEW.evidence_document IS DISTINCT FROM OLD.evidence_document
                    OR NEW.completeness_classification IS DISTINCT FROM OLD.completeness_classification
                    OR NEW.result_classification IS DISTINCT FROM OLD.result_classification
                    OR NEW.created_at IS DISTINCT FROM OLD.created_at
                THEN
                    RAISE EXCEPTION 'billing state observation evidence is immutable';
                END IF;

                IF OLD.resulting_access_revision IS NOT NULL
                    AND NEW.resulting_access_revision IS DISTINCT FROM OLD.resulting_access_revision
                THEN
                    RAISE EXCEPTION 'resulting access revision may only be populated once';
                END IF;

                RETURN NEW;
            END
            $$
            """
        )
    )
    op.execute(
        "CREATE TRIGGER trg_guard_billing_state_observation "
        "BEFORE UPDATE OR DELETE ON billing_state_observations FOR EACH ROW "
        "EXECUTE FUNCTION guard_billing_state_observation()"
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION guard_purchased_allowance()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'purchased allowances are immutable';
            END
            $$
            """
        )
    )
    op.execute(
        "CREATE TRIGGER trg_guard_purchased_allowance "
        "BEFORE UPDATE OR DELETE ON purchased_allowances FOR EACH ROW "
        "EXECUTE FUNCTION guard_purchased_allowance()"
    )


def upgrade() -> None:
    _create_survivor_tables()
    _seed_configured_contour_and_legal_data()
    _create_projection_and_purchase_tables()
    _create_reconciliation_tables()
    _create_delivery_review_and_access_tables()
    _create_immutability_guards()


def downgrade() -> None:
    trigger_functions = (
        ("purchased_allowances", "trg_guard_purchased_allowance", "guard_purchased_allowance"),
        (
            "billing_state_observations",
            "trg_guard_billing_state_observation",
            "guard_billing_state_observation",
        ),
        ("purchase_intents", "trg_guard_purchase_intent_evidence", "guard_purchase_intent_evidence"),
        (
            "commercial_mapping_revisions",
            "trg_guard_commercial_mapping_revision",
            "guard_commercial_mapping_revision",
        ),
        (
            "external_billing_customers",
            "trg_guard_external_billing_customer_identity",
            "guard_external_billing_customer_identity",
        ),
        ("document_versions", "trg_guard_document_version_material", "guard_document_version_material"),
        (
            "document_acceptances",
            "trg_guard_document_acceptance_evidence",
            "guard_document_acceptance_evidence",
        ),
        (
            "legal_acceptance_events",
            "trg_guard_legal_acceptance_event_evidence",
            "guard_legal_acceptance_event_evidence",
        ),
    )
    for table_name, trigger_name, function_name in trigger_functions:
        op.execute(f"DROP TRIGGER {trigger_name} ON {table_name}")
        op.execute(f"DROP FUNCTION {function_name}()")

    op.drop_table("access_invalidation_outbox")
    op.drop_table("paid_access_states")
    op.drop_table("manual_review_cases")
    op.drop_table("external_billing_webhook_deliveries")
    op.drop_table("purchased_allowances")
    op.drop_constraint(
        "fk_external_subscriptions_latest_observation",
        "external_subscriptions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_billing_product_access_scopes_primary_subscription",
        "billing_product_access_scopes",
        type_="foreignkey",
    )
    op.drop_table("billing_state_observations")
    op.drop_table("external_subscriptions")
    op.drop_table("billing_product_access_scopes")
    op.drop_table("billing_work_items")
    op.drop_table("external_create_operations")
    op.drop_table("purchase_intents")
    op.drop_table("external_billing_customers")
    op.drop_table("commercial_mapping_revisions")
    op.drop_table("external_billing_catalog_projections")
    op.drop_table("capability_manifest_projections")

    op.drop_table("document_acceptances")
    op.drop_table("legal_acceptance_events")
    op.drop_table("document_versions")
    op.drop_table("legal_entities")
    op.drop_table("password_reset_rate_limits")
    op.drop_table("magic_link_tokens")
    op.drop_table("auth_sessions")
    op.drop_table("users")
    op.drop_table("country_region_rules")
    op.drop_table("regions")
