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
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import BigInteger, JSON

from app.database import Base


json_type = JSON().with_variant(JSONB(), "postgresql")
id_type = BigInteger().with_variant(Integer, "sqlite")
uuid_type = Uuid(as_uuid=True)
ip_type = String(45).with_variant(INET(), "postgresql")


class PaymentWebhookEvent(Base):
    __tablename__ = "payment_webhook_events"

    id: Mapped[int] = mapped_column(id_type, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String, nullable=False, default="cloudpayments")
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict] = mapped_column(json_type, nullable=False)
    headers: Mapped[dict | None] = mapped_column(json_type, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="received")
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
