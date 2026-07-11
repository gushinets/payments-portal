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
    legal_published_at = datetime(2026, 7, 11, tzinfo=timezone.utc)

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
                "legal_address": "630091 , Новосибирская область, г. Новосибирск",
                "support_email": "support@any-tool-ai.ru",
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
                "version": "2026-07-11",
                "title": "Политика в отношении обработки персональных данных",
                "url_path": "/ru/privacy",
                "content_hash": (
<<<<<<< HEAD
                    "sha256:3a172efed2d4c2d8ccb68c55ca759d63c6b562dc481c0f620fffea2a90e7155f"
=======
                    "sha256:9ebe8daf5d7a833e32f738f9d60e145f02f1bdaa817df744cf14f22dbba9c50c"
>>>>>>> 8468fa5 (ANY-91 / Visual refinements and document edits)
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
                "version": "2026-07-11",
                "title": "Согласие на обработку персональных данных",
                "url_path": "/ru/consent-personal-data",
                "content_hash": (
<<<<<<< HEAD
                    "sha256:e65ace7d96b88ff995c4459b6ce4fcb1ce5519ca417f1c9c4a8b96e1c9c29f3c"
=======
                    "sha256:52081466de8af8108508710d48523bd873079cd91bfc2ca453ad6416a83a34c3"
>>>>>>> 8468fa5 (ANY-91 / Visual refinements and document edits)
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
                "version": "2026-07-11",
                "title": "Публичная оферта на оказание услуг",
                "url_path": "/ru/offer",
                "content_hash": (
<<<<<<< HEAD
                    "sha256:dba32e30db1fa6f1ab7e5d3fc682f088705a5a5567d8ceeacd9dae7f9c336786"
=======
                    "sha256:81966788e83843a11ab0c1803c8a8368a2db2e5dc2edd965ec1269abf802a64f"
>>>>>>> 8468fa5 (ANY-91 / Visual refinements and document edits)
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
                "version": "2026-07-11",
                "title": "Условия отмены подписки и возврата денежных средств",
                "url_path": "/ru/cancellation",
                "content_hash": (
<<<<<<< HEAD
                    "sha256:744ada9ab5ea53cb06e98ce66e51547d73c86f6263d361d6ac4bc903b4d8a3b1"
=======
                    "sha256:134233cb13bfb4470a1a26909355333eb85432ca230b4df4bb578f3722186504"
>>>>>>> 8468fa5 (ANY-91 / Visual refinements and document edits)
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
                "version": "2026-07-11",
                "title": "Политика использования файлов cookie",
                "url_path": "/ru/cookies",
                "content_hash": (
<<<<<<< HEAD
                    "sha256:e96a31dfee4846d6021c67b3af744d5d2ef906ce3b45b51c4ab542797db7fc97"
=======
                    "sha256:bdc9e4da60fe18fb9ec072a52c07d3d79103bb641aef903cda8db38a6b38b571"
>>>>>>> 8468fa5 (ANY-91 / Visual refinements and document edits)
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
                "version": "2026-07-11",
                "title": "Политика информационной безопасности",
                "url_path": "/ru/security",
                "content_hash": (
<<<<<<< HEAD
                    "sha256:4b47419c7c4940e94caf23f1071bb00cd72bbce03e2e2f28e37248a70ac7d924"
=======
                    "sha256:686c159832728cbe7b0b199e21a68f93e435402746eb667c3a4aee14f949d7ed"
>>>>>>> 8468fa5 (ANY-91 / Visual refinements and document edits)
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
        "payment_provider_accounts",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'anytoolai'"),
        ),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("legal_entity_id", uuid_type, sa.ForeignKey("legal_entities.id"), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("public_identifier", sa.Text(), nullable=True),
        sa.Column("default_currency", sa.String(length=3), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("test_mode", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "tenant_id",
            "region",
            "provider",
            "legal_entity_id",
            name="uq_pay_provider_accounts_tenant_region_provider_entity",
        ),
    )
    op.create_index(
        "ix_payment_provider_accounts_region_enabled",
        "payment_provider_accounts",
        ["region", "enabled"],
    )
    op.create_index(
        "uq_payment_provider_accounts_default",
        "payment_provider_accounts",
        ["tenant_id", "region", "provider"],
        unique=True,
        postgresql_where=sa.text("legal_entity_id IS NULL"),
    )

    op.create_table(
        "entrypoint_sessions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=sa.text("'anytoolai'")),
        sa.Column("route_region", sa.Text(), nullable=False),
        sa.Column("resolved_region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("ip_country", sa.String(length=2), nullable=True),
        sa.Column("declared_country", sa.String(length=2), nullable=True),
        sa.Column("browser_language", sa.Text(), nullable=True),
        sa.Column("region_mismatch_status", sa.Text(), nullable=False, server_default=sa.text("'none'")),
        sa.Column("entrypoint_type", sa.Text(), nullable=False),
        sa.Column("entrypoint_value", sa.Text(), nullable=False),
        sa.Column("product_id", uuid_type, nullable=True),
        sa.Column("bundle_id", uuid_type, nullable=True),
        sa.Column("frontend_id", sa.Text(), nullable=True),
        sa.Column("platform_guest_id", sa.Text(), nullable=True),
        sa.Column("platform_user_id", sa.Text(), nullable=True),
        sa.Column("scenario_session_id", sa.Text(), nullable=True),
        sa.Column("artifact_id", sa.Text(), nullable=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("acquisition_source", sa.Text(), nullable=True),
        sa.Column("ip", ip_type, nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_entrypoint_sessions_resolved_region_created_at", "entrypoint_sessions", ["resolved_region", "created_at"])
    op.create_index("ix_entrypoint_sessions_user_id_created_at", "entrypoint_sessions", ["user_id", "created_at"])
    op.create_index("ix_entrypoint_sessions_type_value", "entrypoint_sessions", ["entrypoint_type", "entrypoint_value"])
    op.create_index("ix_entrypoint_sessions_frontend_id_created_at", "entrypoint_sessions", ["frontend_id", "created_at"])
    op.create_index("ix_entrypoint_sessions_scenario_session_id", "entrypoint_sessions", ["scenario_session_id"])

    op.create_table(
        "checkout_sessions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=sa.text("'anytoolai'")),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("entrypoint_session_id", uuid_type, sa.ForeignKey("entrypoint_sessions.id"), nullable=True),
        sa.Column("plan_id", uuid_type, nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'created'")),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_checkout_sessions_user_id_created_at", "checkout_sessions", ["user_id", "created_at"])
    op.create_index("ix_checkout_sessions_status_expires_at", "checkout_sessions", ["status", "expires_at"])

    op.create_table(
        "orders",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=sa.text("'anytoolai'")),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("order_number", sa.Text(), nullable=False),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("checkout_session_id", uuid_type, sa.ForeignKey("checkout_sessions.id"), nullable=True),
        sa.Column("entrypoint_session_id", uuid_type, sa.ForeignKey("entrypoint_sessions.id"), nullable=True),
        sa.Column("plan_id", uuid_type, nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'created'")),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("tax_amount_minor", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("discount_amount_minor", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_account_id", uuid_type, sa.ForeignKey("payment_provider_accounts.id"), nullable=False),
        sa.Column("merchant_order_id", sa.Text(), nullable=False),
        sa.Column("provider_invoice_id", sa.Text(), nullable=True),
        sa.Column("billing_country", sa.String(length=2), nullable=True),
        sa.Column("region_mismatch_status", sa.Text(), nullable=False, server_default=sa.text("'none'")),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "region", "order_number", name="uq_orders_tenant_region_order_number"),
        sa.UniqueConstraint("provider_account_id", "merchant_order_id", name="uq_orders_provider_account_merchant_order"),
    )
    op.create_index("ix_orders_user_id_created_at", "orders", ["user_id", "created_at"])
    op.create_index("ix_orders_region_status_created_at", "orders", ["region", "status", "created_at"])
    op.create_index("ix_orders_provider_invoice_id", "orders", ["provider", "provider_invoice_id"])
    op.create_index("ix_orders_entrypoint_session_id", "orders", ["entrypoint_session_id"])

    op.create_table(
        "order_items",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("order_id", uuid_type, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("item_type", sa.Text(), nullable=False),
        sa.Column("product_id", uuid_type, nullable=True),
        sa.Column("bundle_id", uuid_type, nullable=True),
        sa.Column("plan_id", uuid_type, nullable=True),
        sa.Column("product_code_snapshot", sa.Text(), nullable=True),
        sa.Column("plan_code_snapshot", sa.Text(), nullable=True),
        sa.Column("title_snapshot", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("list_amount_minor", sa.Integer(), nullable=False),
        sa.Column("discount_amount_minor", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("unit_amount_minor", sa.Integer(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("trial_days_snapshot", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("pricing_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_index("ix_order_items_product_id", "order_items", ["product_id"])
    op.create_index("ix_order_items_bundle_id", "order_items", ["bundle_id"])

    op.create_table(
        "payments",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=sa.text("'anytoolai'")),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("order_id", uuid_type, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("provider_account_id", uuid_type, sa.ForeignKey("payment_provider_accounts.id"), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_payment_id", sa.Text(), nullable=True),
        sa.Column("provider_invoice_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'created'")),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("payment_method_type", sa.Text(), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_amount_minor", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("failure_message_safe", sa.Text(), nullable=True),
        sa.Column("raw_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "uq_payments_provider_account_payment_id",
        "payments",
        ["provider_account_id", "provider_payment_id"],
        unique=True,
        postgresql_where=sa.text("provider_payment_id IS NOT NULL"),
    )
    op.create_index("ix_payments_order_id", "payments", ["order_id"])
    op.create_index("ix_payments_region_status_created_at", "payments", ["region", "status", "created_at"])

    op.create_table(
        "refunds",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=sa.text("'anytoolai'")),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("order_id", uuid_type, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("payment_id", uuid_type, sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("provider_account_id", uuid_type, sa.ForeignKey("payment_provider_accounts.id"), nullable=False),
        sa.Column("provider_refund_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'requested'")),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_refunds_order_id", "refunds", ["order_id"])
    op.create_index("ix_refunds_payment_id", "refunds", ["payment_id"])
    op.create_index(
        "uq_refunds_provider_account_refund_id",
        "refunds",
        ["provider_account_id", "provider_refund_id"],
        unique=True,
        postgresql_where=sa.text("provider_refund_id IS NOT NULL"),
    )

    op.create_table(
        "payment_webhook_events",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=sa.text("'anytoolai'")),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("provider_account_id", uuid_type, sa.ForeignKey("payment_provider_accounts.id"), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False, server_default=sa.text("'cloudpayments'")),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=True),
        sa.Column("provider_event_id", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("invoice_id", sa.Text(), nullable=True),
        sa.Column("transaction_id", sa.Text(), nullable=True),
        sa.Column("account_id", sa.Text(), nullable=True),
        sa.Column("order_id", uuid_type, sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("payment_id", uuid_type, sa.ForeignKey("payments.id"), nullable=True),
        sa.Column("amount_minor", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'received'")),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_payment_webhook_events_region_provider_received_at", "payment_webhook_events", ["region", "provider", "received_at"])
    op.create_index("ix_payment_webhook_events_provider_endpoint_event_type", "payment_webhook_events", ["provider", "endpoint", "event_type"])
    op.create_index("ix_payment_webhook_events_provider_event_id", "payment_webhook_events", ["provider_account_id", "provider_event_id"])
    op.create_index("ix_payment_webhook_events_order_id", "payment_webhook_events", ["order_id"])
    op.create_index("ix_payment_webhook_events_payment_id", "payment_webhook_events", ["payment_id"])
    op.create_index("ix_payment_webhook_events_idempotency_lookup", "payment_webhook_events", ["provider_account_id", "idempotency_key"])

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

    op.drop_index("ix_payment_webhook_events_idempotency_lookup", table_name="payment_webhook_events")
    op.drop_index("ix_payment_webhook_events_payment_id", table_name="payment_webhook_events")
    op.drop_index("ix_payment_webhook_events_order_id", table_name="payment_webhook_events")
    op.drop_index("ix_payment_webhook_events_provider_event_id", table_name="payment_webhook_events")
    op.drop_index("ix_payment_webhook_events_provider_endpoint_event_type", table_name="payment_webhook_events")
    op.drop_index("ix_payment_webhook_events_region_provider_received_at", table_name="payment_webhook_events")
    op.drop_table("payment_webhook_events")

    op.drop_index("uq_refunds_provider_account_refund_id", table_name="refunds")
    op.drop_index("ix_refunds_payment_id", table_name="refunds")
    op.drop_index("ix_refunds_order_id", table_name="refunds")
    op.drop_table("refunds")

    op.drop_index("ix_payments_region_status_created_at", table_name="payments")
    op.drop_index("ix_payments_order_id", table_name="payments")
    op.drop_index("uq_payments_provider_account_payment_id", table_name="payments")
    op.drop_table("payments")

    op.drop_index("ix_order_items_bundle_id", table_name="order_items")
    op.drop_index("ix_order_items_product_id", table_name="order_items")
    op.drop_index("ix_order_items_order_id", table_name="order_items")
    op.drop_table("order_items")

    op.drop_index("ix_orders_entrypoint_session_id", table_name="orders")
    op.drop_index("ix_orders_provider_invoice_id", table_name="orders")
    op.drop_index("ix_orders_region_status_created_at", table_name="orders")
    op.drop_index("ix_orders_user_id_created_at", table_name="orders")
    op.drop_table("orders")

    op.drop_index("ix_checkout_sessions_status_expires_at", table_name="checkout_sessions")
    op.drop_index("ix_checkout_sessions_user_id_created_at", table_name="checkout_sessions")
    op.drop_table("checkout_sessions")

    op.drop_index("ix_entrypoint_sessions_scenario_session_id", table_name="entrypoint_sessions")
    op.drop_index("ix_entrypoint_sessions_frontend_id_created_at", table_name="entrypoint_sessions")
    op.drop_index("ix_entrypoint_sessions_type_value", table_name="entrypoint_sessions")
    op.drop_index("ix_entrypoint_sessions_user_id_created_at", table_name="entrypoint_sessions")
    op.drop_index("ix_entrypoint_sessions_resolved_region_created_at", table_name="entrypoint_sessions")
    op.drop_table("entrypoint_sessions")

    op.drop_index("uq_payment_provider_accounts_default", table_name="payment_provider_accounts")
    op.drop_index("ix_payment_provider_accounts_region_enabled", table_name="payment_provider_accounts")
    op.drop_table("payment_provider_accounts")

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
