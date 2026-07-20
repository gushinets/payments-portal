from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    CheckConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import BigInteger, JSON

from app.core.database import Base


json_type = JSON().with_variant(JSONB(), "postgresql")
id_type = BigInteger().with_variant(Integer, "sqlite")
uuid_type = Uuid(as_uuid=True)
ip_type = String(45).with_variant(INET(), "postgresql")


class PaymentWebhookEvent(Base):
    __tablename__ = "payment_webhook_events"
    __table_args__ = (
        Index("ix_payment_webhook_events_region_provider_received_at", "region", "provider", "received_at"),
        Index("ix_payment_webhook_events_provider_endpoint_event_type", "provider", "endpoint", "event_type"),
        Index("ix_payment_webhook_events_provider_event_id", "provider_account_id", "provider_event_id"),
        Index("ix_payment_webhook_events_order_id", "order_id"),
        Index("ix_payment_webhook_events_payment_id", "payment_id"),
        Index("ix_payment_webhook_events_idempotency_lookup", "provider_account_id", "idempotency_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, default="ru", index=True)
    provider_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payment_provider_accounts.id"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String, nullable=False, default="cloudpayments")
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"), nullable=True)
    amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict] = mapped_column(json_type, nullable=False)
    headers: Mapped[dict | None] = mapped_column(json_type, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="received")
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class Region(Base):
    __tablename__ = "regions"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    residency_zone: Mapped[str] = mapped_column(Text, nullable=False)
    default_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    default_locale: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")


class CountryRegionRule(Base):
    __tablename__ = "country_region_rules"

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    country_code: Mapped[str] = mapped_column(
        String(2), nullable=False, unique=True, index=True
    )
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    market_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_region_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    strict_mismatch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_document_set: Mapped[str] = mapped_column(Text, nullable=False)
    default_payment_provider: Mapped[str] = mapped_column(Text, nullable=False)


class LegalEntity(Base):
    __tablename__ = "legal_entities"
    __table_args__ = (
        Index("ix_legal_entities_tenant_region_status", "tenant_id", "region", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    tax_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    registration_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    legal_address: Mapped[str] = mapped_column(Text, nullable=False)
    support_email: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "region",
            "doc_type",
            "version",
            name="uq_document_versions_tenant_region_doc_type_version",
        ),
        Index(
            "uq_document_versions_active_doc",
            "tenant_id",
            "region",
            "doc_type",
            unique=True,
            postgresql_where=text("is_active = true"),
            sqlite_where=text("is_active = true"),
        ),
        Index("ix_document_versions_region_is_active", "region", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legal_entities.id"), nullable=False, index=True
    )
    doc_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    requires_acceptance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DocumentAcceptance(Base):
    __tablename__ = "document_acceptances"
    __table_args__ = (
        Index(
            "ix_document_acceptances_user_region_doc_accepted_at",
            "user_id",
            "region",
            "doc_type",
            "accepted_at",
        ),
        Index(
            "ix_document_acceptances_entrypoint_session_id",
            "entrypoint_session_id",
        ),
        Index(
            "ix_document_acceptances_region_doc_version",
            "region",
            "doc_type",
            "version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    guest_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    entrypoint_session_id: Mapped[uuid.UUID | None] = mapped_column(uuid_type, nullable=True)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id"), nullable=False, index=True
    )
    doc_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    acceptance_kind: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    ip: Mapped[str | None] = mapped_column(ip_type, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    acceptance_text_hash: Mapped[str] = mapped_column(Text, nullable=False)
    entrypoint_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    entrypoint_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", json_type, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "region",
            "email_normalized",
            name="uq_users_tenant_region_email_normalized",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active", index=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", json_type, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip: Mapped[str | None] = mapped_column(ip_type, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)


class MagicLinkToken(Base):
    __tablename__ = "magic_link_tokens"

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    entrypoint_session_id: Mapped[uuid.UUID | None] = mapped_column(uuid_type, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip: Mapped[str | None] = mapped_column(ip_type, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)


class PaymentProviderAccount(Base):
    __tablename__ = "payment_provider_accounts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "region",
            "provider",
            "legal_entity_id",
            name="uq_pay_provider_accounts_tenant_region_provider_entity",
        ),
        Index("ix_payment_provider_accounts_region_enabled", "region", "enabled"),
        Index(
            "uq_payment_provider_accounts_default",
            "tenant_id",
            "region",
            "provider",
            unique=True,
            postgresql_where=text("legal_entity_id IS NULL"),
            sqlite_where=text("legal_entity_id IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("legal_entities.id"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    public_identifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    test_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict] = mapped_column(json_type, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_products_tenant_code"),
        UniqueConstraint(
            "tenant_id",
            "platform_product_id",
            name="uq_products_tenant_platform_product_id",
        ),
        Index("ix_products_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    platform_product_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Bundle(Base):
    __tablename__ = "bundles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_bundles_tenant_code"),
        Index("ix_bundles_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class BundleProduct(Base):
    __tablename__ = "bundle_products"
    __table_args__ = (
        Index("ix_bundle_products_bundle_status", "bundle_id", "status"),
        Index("ix_bundle_products_product_id", "product_id"),
        Index(
            "uq_bundle_products_active_product",
            "bundle_id",
            "product_id",
            unique=True,
            postgresql_where=text("status = 'active' AND valid_to IS NULL"),
            sqlite_where=text("status = 'active' AND valid_to IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    bundle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bundles.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "region",
            "code",
            "valid_from",
            name="uq_plans_tenant_region_code_valid_from",
        ),
        CheckConstraint(
            "scope_type IN ('product', 'bundle', 'all_access')",
            name="ck_plans_scope_type",
        ),
        CheckConstraint("price_amount_minor >= 0", name="ck_plans_price_non_negative"),
        CheckConstraint("trial_days >= 0", name="ck_plans_trial_days_non_negative"),
        CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_plans_valid_window",
        ),
        Index("ix_plans_region_status", "region", "status"),
        Index("ix_plans_product_id", "product_id"),
        Index("ix_plans_bundle_id", "bundle_id"),
        Index(
            "uq_plans_active_code",
            "tenant_id",
            "region",
            "code",
            unique=True,
            postgresql_where=text("status = 'active' AND valid_to IS NULL"),
            sqlite_where=text("status = 'active' AND valid_to IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    bundle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bundles.id"), nullable=True)
    price_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    billing_period: Mapped[str] = mapped_column(Text, nullable=False)
    renewal_mode: Mapped[str] = mapped_column(Text, nullable=False, default="manual")
    trial_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active", index=True)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", json_type, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PlanPriceComponent(Base):
    __tablename__ = "plan_price_components"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_plan_price_components_quantity_positive"),
        CheckConstraint(
            "list_amount_minor >= 0 AND discount_amount_minor >= 0 AND amount_minor >= 0",
            name="ck_plan_price_components_amounts_non_negative",
        ),
        Index("ix_plan_price_components_plan_position", "plan_id", "position"),
        Index("ix_plan_price_components_source_plan_id", "source_plan_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"), nullable=False)
    component_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id"), nullable=True
    )
    source_bundle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bundles.id"), nullable=True
    )
    source_plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    component_code_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    title_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    list_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    discount_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_: Mapped[dict] = mapped_column("metadata", json_type, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PlanLimit(Base):
    __tablename__ = "plan_limits"
    __table_args__ = (
        UniqueConstraint("plan_id", "metric", name="uq_plan_limits_plan_metric"),
        CheckConstraint("limit_count >= 0", name="ck_plan_limits_limit_count_non_negative"),
        Index("ix_plan_limits_plan_id", "plan_id"),
        Index("ix_plan_limits_metric", "metric"),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    limit_count: Mapped[int] = mapped_column(Integer, nullable=False)
    period: Mapped[str] = mapped_column(Text, nullable=False)
    reset_policy: Mapped[str] = mapped_column(Text, nullable=False, default="billing_period")
    overage_policy: Mapped[str] = mapped_column(Text, nullable=False, default="deny")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class EntrypointSession(Base):
    __tablename__ = "entrypoint_sessions"
    __table_args__ = (
        Index("ix_entrypoint_sessions_resolved_region_created_at", "resolved_region", "created_at"),
        Index("ix_entrypoint_sessions_user_id_created_at", "user_id", "created_at"),
        Index("ix_entrypoint_sessions_type_value", "entrypoint_type", "entrypoint_value"),
        Index("ix_entrypoint_sessions_frontend_id_created_at", "frontend_id", "created_at"),
        Index("ix_entrypoint_sessions_scenario_session_id", "scenario_session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    route_region: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False)
    ip_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    declared_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    browser_language: Mapped[str | None] = mapped_column(Text, nullable=True)
    region_mismatch_status: Mapped[str] = mapped_column(Text, nullable=False, default="none")
    entrypoint_type: Mapped[str] = mapped_column(Text, nullable=False)
    entrypoint_value: Mapped[str] = mapped_column(Text, nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    bundle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bundles.id"), nullable=True)
    frontend_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform_guest_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    scenario_session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    acquisition_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(ip_type, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", json_type, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CheckoutSession(Base):
    __tablename__ = "checkout_sessions"
    __table_args__ = (
        Index("ix_checkout_sessions_user_id_created_at", "user_id", "created_at"),
        Index("ix_checkout_sessions_status_expires_at", "status", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    entrypoint_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("entrypoint_sessions.id"), nullable=True, index=True
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="created")
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", json_type, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "region",
            "order_number",
            name="uq_orders_tenant_region_order_number",
        ),
        UniqueConstraint(
            "provider_account_id",
            "merchant_order_id",
            name="uq_orders_provider_account_merchant_order",
        ),
        Index("ix_orders_user_id_created_at", "user_id", "created_at"),
        Index("ix_orders_region_status_created_at", "region", "status", "created_at"),
        Index("ix_orders_provider_invoice_id", "provider", "provider_invoice_id"),
        Index("ix_orders_entrypoint_session_id", "entrypoint_session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    order_number: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    checkout_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("checkout_sessions.id"), nullable=True, index=True
    )
    entrypoint_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("entrypoint_sessions.id"), nullable=True
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="created", index=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    tax_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discount_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payment_provider_accounts.id"), nullable=False, index=True
    )
    merchant_order_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_invoice_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    billing_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    region_mismatch_status: Mapped[str] = mapped_column(Text, nullable=False, default="none")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", json_type, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        Index("ix_order_items_order_id", "order_id"),
        Index("ix_order_items_product_id", "product_id"),
        Index("ix_order_items_bundle_id", "bundle_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), nullable=False)
    item_type: Mapped[str] = mapped_column(Text, nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    bundle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bundles.id"), nullable=True)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    product_code_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_code_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    title_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    list_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    discount_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    trial_days_snapshot: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pricing_snapshot: Mapped[dict] = mapped_column(json_type, nullable=False, default=dict)
    metadata_: Mapped[dict] = mapped_column("metadata", json_type, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        Index(
            "uq_payments_provider_account_payment_id",
            "provider_account_id",
            "provider_payment_id",
            unique=True,
            postgresql_where=text("provider_payment_id IS NOT NULL"),
            sqlite_where=text("provider_payment_id IS NOT NULL"),
        ),
        Index("ix_payments_order_id", "order_id"),
        Index("ix_payments_region_status_created_at", "region", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), nullable=False)
    provider_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payment_provider_accounts.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_invoice_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="created", index=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    payment_method_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_message_safe: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_summary: Mapped[dict] = mapped_column(json_type, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (
        Index("ix_refunds_order_id", "order_id"),
        Index("ix_refunds_payment_id", "payment_id"),
        Index(
            "uq_refunds_provider_account_refund_id",
            "provider_account_id",
            "provider_refund_id",
            unique=True,
            postgresql_where=text("provider_refund_id IS NOT NULL"),
            sqlite_where=text("provider_refund_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), nullable=False)
    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id"), nullable=False)
    provider_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payment_provider_accounts.id"), nullable=False, index=True
    )
    provider_refund_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="requested")
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", json_type, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProductAccessState(Base):
    __tablename__ = "product_access_states"
    __table_args__ = (UniqueConstraint("user_id", "product_code", name="uq_user_product"),)

    id: Mapped[int] = mapped_column(id_type, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    product_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    plan_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_invoice_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    last_transaction_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="inactive")
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
