from __future__ import annotations

from app.models._shared import (
    Base,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Mapped,
    String,
    Text,
    UniqueConstraint,
    datetime,
    func,
    ip_type,
    json_type,
    mapped_column,
    text,
    uuid,
    uuid_type,
)


class EntrypointSession(Base):
    __tablename__ = "entrypoint_sessions"
    __table_args__ = (
        Index(
            "ix_entrypoint_sessions_resolved_region_created_at",
            "resolved_region",
            "created_at",
        ),
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
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    acquisition_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(ip_type, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", json_type, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
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
    entrypoint_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("entrypoint_sessions.id"), nullable=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
