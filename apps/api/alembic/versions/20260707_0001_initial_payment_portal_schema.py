"""initial payment portal schema

Revision ID: 20260707_0001
Revises:
Create Date: 2026-07-07
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260707_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = sa.Uuid()
    ip_type = postgresql.INET()
    legal_published_at = datetime(2026, 7, 2, tzinfo=timezone.utc)

    op.create_table(
        "regions",
        sa.Column("code", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("residency_zone", sa.Text(), nullable=False),
        sa.Column("default_currency", sa.String(length=3), nullable=False),
        sa.Column("default_locale", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
    )
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
            },
            {
                "code": "eu",
                "name": "European Union",
                "residency_zone": "eu_eea",
                "default_currency": "EUR",
                "default_locale": "en-EU",
                "status": "active",
            },
        ],
    )

    op.create_table(
        "country_region_rules",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column(
            "market_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "allow_region_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "strict_mismatch",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("default_document_set", sa.Text(), nullable=False),
        sa.Column("default_payment_provider", sa.Text(), nullable=False),
        sa.UniqueConstraint("country_code", name="uq_country_region_rules_country_code"),
    )
    op.create_index(
        "ix_country_region_rules_region_market_enabled",
        "country_region_rules",
        ["region", "market_enabled"],
    )
    op.bulk_insert(
        sa.table(
            "country_region_rules",
            sa.column("id", uuid_type),
            sa.column("country_code", sa.String(length=2)),
            sa.column("region", sa.Text()),
            sa.column("market_enabled", sa.Boolean()),
            sa.column("allow_region_override", sa.Boolean()),
            sa.column("strict_mismatch", sa.Boolean()),
            sa.column("default_document_set", sa.Text()),
            sa.column("default_payment_provider", sa.Text()),
        ),
        [
            {
                "id": UUID("11111111-1111-4111-8111-111111111111"),
                "country_code": "RU",
                "region": "ru",
                "market_enabled": True,
                "allow_region_override": False,
                "strict_mismatch": True,
                "default_document_set": "ru_ip_v1",
                "default_payment_provider": "cloudpayments",
            },
            {
                "id": UUID("22222222-2222-4222-8222-222222222222"),
                "country_code": "DE",
                "region": "eu",
                "market_enabled": True,
                "allow_region_override": True,
                "strict_mismatch": True,
                "default_document_set": "eu_gdpr_v1",
                "default_payment_provider": "paddle",
            },
            {
                "id": UUID("33333333-3333-4333-8333-333333333333"),
                "country_code": "ES",
                "region": "eu",
                "market_enabled": True,
                "allow_region_override": True,
                "strict_mismatch": True,
                "default_document_set": "eu_gdpr_v1",
                "default_payment_provider": "paddle",
            },
        ],
    )

    op.create_table(
        "legal_entities",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'anytoolai'"),
        ),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("tax_id", sa.Text(), nullable=True),
        sa.Column("registration_id", sa.Text(), nullable=True),
        sa.Column("legal_address", sa.Text(), nullable=False),
        sa.Column("support_email", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_legal_entities_tenant_region_status",
        "legal_entities",
        ["tenant_id", "region", "status"],
    )

    op.create_table(
        "document_versions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'anytoolai'"),
        ),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("legal_entity_id", uuid_type, sa.ForeignKey("legal_entities.id"), nullable=False),
        sa.Column("doc_type", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url_path", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "requires_acceptance",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "region",
            "doc_type",
            "version",
            name="uq_document_versions_tenant_region_doc_type_version",
        ),
    )
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
    op.create_index(
        "ix_document_versions_legal_entity_id",
        "document_versions",
        ["legal_entity_id"],
    )
    op.bulk_insert(
        sa.table(
            "legal_entities",
            sa.column("id", uuid_type),
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
                "id": UUID("44444444-4444-4444-8444-444444444444"),
                "tenant_id": "anytoolai",
                "region": "ru",
                "name": "ИП Говоров Роман Стальевич",
                "entity_type": "individual_entrepreneur",
                "tax_id": "143509640374",
                "registration_id": "314547633100101",
                "legal_address": (
                    "630091, Новосибирская область, г. Новосибирск, "
                    "Красный пр-кт, дом 45, кв. 30"
                ),
                "support_email": "info@anytoolai.ru",
                "status": "active",
            },
        ],
    )
    op.bulk_insert(
        sa.table(
            "document_versions",
            sa.column("id", uuid_type),
            sa.column("tenant_id", sa.Text()),
            sa.column("region", sa.Text()),
            sa.column("legal_entity_id", uuid_type),
            sa.column("doc_type", sa.Text()),
            sa.column("version", sa.Text()),
            sa.column("title", sa.Text()),
            sa.column("url_path", sa.Text()),
            sa.column("content_hash", sa.Text()),
            sa.column("published_at", sa.DateTime(timezone=True)),
            sa.column("effective_from", sa.DateTime(timezone=True)),
            sa.column("is_active", sa.Boolean()),
            sa.column("requires_acceptance", sa.Boolean()),
        ),
        [
            {
                "id": UUID("55555555-5555-4555-8555-555555555501"),
                "tenant_id": "anytoolai",
                "region": "ru",
                "legal_entity_id": UUID("44444444-4444-4444-8444-444444444444"),
                "doc_type": "privacy",
                "version": "2026-07-02",
                "title": "Политика в отношении обработки персональных данных",
                "url_path": "/ru/privacy",
                "content_hash": (
                    "sha256:3a859b6704b6e35e41eb97cab1daddc7cde9923540eceffbd7d3a08c0045672c"
                ),
                "published_at": legal_published_at,
                "effective_from": legal_published_at,
                "is_active": True,
                "requires_acceptance": True,
            },
            {
                "id": UUID("55555555-5555-4555-8555-555555555502"),
                "tenant_id": "anytoolai",
                "region": "ru",
                "legal_entity_id": UUID("44444444-4444-4444-8444-444444444444"),
                "doc_type": "pd_consent",
                "version": "2026-07-02",
                "title": "Согласие на обработку персональных данных",
                "url_path": "/ru/consent-personal-data",
                "content_hash": (
                    "sha256:645e250d313273dc1488aa1fb7fbf4fe9ae731bea25d33d0025770eef7efba07"
                ),
                "published_at": legal_published_at,
                "effective_from": legal_published_at,
                "is_active": True,
                "requires_acceptance": True,
            },
            {
                "id": UUID("55555555-5555-4555-8555-555555555503"),
                "tenant_id": "anytoolai",
                "region": "ru",
                "legal_entity_id": UUID("44444444-4444-4444-8444-444444444444"),
                "doc_type": "offer",
                "version": "2026-07-02",
                "title": "Публичная оферта на оказание услуг",
                "url_path": "/ru/offer",
                "content_hash": (
                    "sha256:5926ed6905b47b941dade5418354fc89d2f6efc330771548bdde4c102572d5c2"
                ),
                "published_at": legal_published_at,
                "effective_from": legal_published_at,
                "is_active": True,
                "requires_acceptance": True,
            },
            {
                "id": UUID("55555555-5555-4555-8555-555555555504"),
                "tenant_id": "anytoolai",
                "region": "ru",
                "legal_entity_id": UUID("44444444-4444-4444-8444-444444444444"),
                "doc_type": "cancellation",
                "version": "2026-07-02",
                "title": "Условия отмены подписки и возврата денежных средств",
                "url_path": "/ru/cancellation",
                "content_hash": (
                    "sha256:9790b7cc3a004698a1b0a3d5bea8329450fb78e41bf829fc7d15c40387648c8f"
                ),
                "published_at": legal_published_at,
                "effective_from": legal_published_at,
                "is_active": True,
                "requires_acceptance": False,
            },
            {
                "id": UUID("55555555-5555-4555-8555-555555555505"),
                "tenant_id": "anytoolai",
                "region": "ru",
                "legal_entity_id": UUID("44444444-4444-4444-8444-444444444444"),
                "doc_type": "cookies",
                "version": "2026-07-02",
                "title": "Политика использования файлов cookie",
                "url_path": "/ru/cookies",
                "content_hash": (
                    "sha256:2ab4fd889d543c33bbddaead22c1c54843a88db383444043b114de870ec851b4"
                ),
                "published_at": legal_published_at,
                "effective_from": legal_published_at,
                "is_active": True,
                "requires_acceptance": False,
            },
            {
                "id": UUID("55555555-5555-4555-8555-555555555506"),
                "tenant_id": "anytoolai",
                "region": "ru",
                "legal_entity_id": UUID("44444444-4444-4444-8444-444444444444"),
                "doc_type": "security",
                "version": "2026-07-02",
                "title": "Политика информационной безопасности",
                "url_path": "/ru/security",
                "content_hash": (
                    "sha256:c6730f20a045becb7ad282d453cc7291eec9435a00e6c463d5042f0ca5ec10eb"
                ),
                "published_at": legal_published_at,
                "effective_from": legal_published_at,
                "is_active": True,
                "requires_acceptance": False,
            },
        ],
    )

    op.create_table(
        "users",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'anytoolai'"),
        ),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("email_normalized", sa.String(length=320), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "region",
            "email_normalized",
            name="uq_users_tenant_region_email_normalized",
        ),
    )
    op.create_index("ix_users_email_normalized", "users", ["email_normalized"])
    op.create_index("ix_users_region_status", "users", ["region", "status"])

    op.create_table(
        "document_acceptances",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'anytoolai'"),
        ),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("guest_id", sa.Text(), nullable=True),
        sa.Column("entrypoint_session_id", uuid_type, nullable=True),
        sa.Column(
            "document_version_id",
            uuid_type,
            sa.ForeignKey("document_versions.id"),
            nullable=False,
        ),
        sa.Column("doc_type", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("acceptance_kind", sa.Text(), nullable=False),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ip", ip_type, nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("acceptance_text_hash", sa.Text(), nullable=False),
        sa.Column("entrypoint_type", sa.Text(), nullable=True),
        sa.Column("entrypoint_value", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_document_acceptances_user_region_doc_accepted_at",
        "document_acceptances",
        ["user_id", "region", "doc_type", "accepted_at"],
    )
    op.create_index(
        "ix_document_acceptances_document_version_id",
        "document_acceptances",
        ["document_version_id"],
    )
    op.create_index(
        "ix_document_acceptances_entrypoint_session_id",
        "document_acceptances",
        ["entrypoint_session_id"],
    )
    op.create_index(
        "ix_document_acceptances_region_doc_version",
        "document_acceptances",
        ["region", "doc_type", "version"],
    )
    op.create_index(
        "ix_document_acceptances_guest_id",
        "document_acceptances",
        ["guest_id"],
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'anytoolai'"),
        ),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", ip_type, nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_auth_sessions_user_id_expires_at",
        "auth_sessions",
        ["user_id", "expires_at"],
    )
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)

    op.create_table(
        "magic_link_tokens",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'anytoolai'"),
        ),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("email_normalized", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("entrypoint_session_id", uuid_type, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", ip_type, nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_magic_link_tokens_token_hash",
        "magic_link_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_magic_link_tokens_identity_email_created_at",
        "magic_link_tokens",
        ["tenant_id", "region", "email_normalized", "created_at"],
    )

    op.create_table(
        "payment_webhook_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "provider",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'cloudpayments'"),
        ),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=True),
        sa.Column("invoice_id", sa.Text(), nullable=True),
        sa.Column("transaction_id", sa.Text(), nullable=True),
        sa.Column("account_id", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'received'"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_payment_webhook_events_received_at",
        "payment_webhook_events",
        ["received_at"],
    )
    op.create_index(
        "ix_payment_webhook_events_endpoint",
        "payment_webhook_events",
        ["endpoint"],
    )
    op.create_index(
        "ix_payment_webhook_events_transaction_id",
        "payment_webhook_events",
        ["transaction_id"],
    )

    op.create_table(
        "product_access_states",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("product_code", sa.String(length=64), nullable=False),
        sa.Column("plan_code", sa.String(length=128), nullable=True),
        sa.Column("last_invoice_id", sa.String(length=128), nullable=True),
        sa.Column("last_transaction_id", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'inactive'"),
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", "product_code", name="uq_user_product"),
    )
    op.create_index(
        "ix_product_access_states_user_id",
        "product_access_states",
        ["user_id"],
    )
    op.create_index(
        "ix_product_access_states_product_code",
        "product_access_states",
        ["product_code"],
    )
    op.create_index(
        "ix_product_access_states_last_invoice_id",
        "product_access_states",
        ["last_invoice_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_access_states_last_invoice_id",
        table_name="product_access_states",
    )
    op.drop_index("ix_product_access_states_product_code", table_name="product_access_states")
    op.drop_index("ix_product_access_states_user_id", table_name="product_access_states")
    op.drop_table("product_access_states")

    op.drop_index(
        "ix_payment_webhook_events_transaction_id",
        table_name="payment_webhook_events",
    )
    op.drop_index("ix_payment_webhook_events_endpoint", table_name="payment_webhook_events")
    op.drop_index(
        "ix_payment_webhook_events_received_at",
        table_name="payment_webhook_events",
    )
    op.drop_table("payment_webhook_events")

    op.drop_index(
        "ix_magic_link_tokens_identity_email_created_at",
        table_name="magic_link_tokens",
    )
    op.drop_index("ix_magic_link_tokens_token_hash", table_name="magic_link_tokens")
    op.drop_table("magic_link_tokens")

    op.drop_index("ix_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id_expires_at", table_name="auth_sessions")
    op.drop_table("auth_sessions")

    op.drop_index("ix_users_region_status", table_name="users")
    op.drop_index("ix_users_email_normalized", table_name="users")
    op.drop_index(
        "ix_document_acceptances_guest_id",
        table_name="document_acceptances",
    )
    op.drop_index(
        "ix_document_acceptances_region_doc_version",
        table_name="document_acceptances",
    )
    op.drop_index(
        "ix_document_acceptances_entrypoint_session_id",
        table_name="document_acceptances",
    )
    op.drop_index(
        "ix_document_acceptances_document_version_id",
        table_name="document_acceptances",
    )
    op.drop_index(
        "ix_document_acceptances_user_region_doc_accepted_at",
        table_name="document_acceptances",
    )
    op.drop_table("document_acceptances")
    op.drop_table("users")

    op.drop_index(
        "ix_document_versions_legal_entity_id",
        table_name="document_versions",
    )
    op.drop_index(
        "ix_document_versions_region_is_active",
        table_name="document_versions",
    )
    op.drop_index(
        "uq_document_versions_active_doc",
        table_name="document_versions",
    )
    op.drop_table("document_versions")

    op.drop_index(
        "ix_legal_entities_tenant_region_status",
        table_name="legal_entities",
    )
    op.drop_table("legal_entities")

    op.drop_index(
        "ix_country_region_rules_region_market_enabled",
        table_name="country_region_rules",
    )
    op.drop_table("country_region_rules")
    op.drop_table("regions")
