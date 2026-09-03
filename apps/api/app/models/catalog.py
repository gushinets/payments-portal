from __future__ import annotations

from app.models.enums import (
    BillingPeriod,
    BundleProductStatus,
    BundleStatus,
    PlanLimitOveragePolicy,
    PlanLimitResetPolicy,
    PlanPriceComponentType,
    PlanStatus,
    ProductStatus,
    SubscriptionRenewalMode,
    SubscriptionScopeType,
)
from app.models._shared import (
    Base,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Mapped,
    PersistedEnumType,
    String,
    Text,
    UniqueConstraint,
    all_access_scope_sql,
    bundle_scope_sql,
    datetime,
    func,
    json_type,
    mapped_column,
    product_scope_sql,
    text,
    uuid,
    uuid_type,
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
    status: Mapped[ProductStatus] = mapped_column(
        PersistedEnumType(ProductStatus), nullable=False, default=ProductStatus.ACTIVE, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
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
    status: Mapped[BundleStatus] = mapped_column(
        PersistedEnumType(BundleStatus), nullable=False, default=BundleStatus.ACTIVE, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
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
            postgresql_where=text(f"status = '{BundleProductStatus.ACTIVE.value}' AND valid_to IS NULL"),
            sqlite_where=text(f"status = '{BundleProductStatus.ACTIVE.value}' AND valid_to IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    bundle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bundles.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    status: Mapped[BundleProductStatus] = mapped_column(
        PersistedEnumType(BundleProductStatus), nullable=False, default=BundleProductStatus.ACTIVE
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


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
            f"scope_type IN ('{product_scope_sql}', '{bundle_scope_sql}', '{all_access_scope_sql}')",
            name="ck_plans_scope_type",
        ),
        CheckConstraint(
            f"(scope_type = '{product_scope_sql}' AND product_id IS NOT NULL AND bundle_id IS NULL)"
            f" OR (scope_type = '{bundle_scope_sql}' AND product_id IS NULL AND bundle_id IS NOT NULL)"
            f" OR (scope_type = '{all_access_scope_sql}' AND product_id IS NULL AND bundle_id IS NULL)",
            name="ck_plans_scope_references",
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
            postgresql_where=text(f"status = '{PlanStatus.ACTIVE.value}' AND valid_to IS NULL"),
            sqlite_where=text(f"status = '{PlanStatus.ACTIVE.value}' AND valid_to IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    scope_type: Mapped[SubscriptionScopeType] = mapped_column(PersistedEnumType(SubscriptionScopeType), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    bundle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bundles.id"), nullable=True)
    price_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    billing_period: Mapped[BillingPeriod] = mapped_column(PersistedEnumType(BillingPeriod), nullable=False)
    renewal_mode: Mapped[SubscriptionRenewalMode] = mapped_column(
        PersistedEnumType(SubscriptionRenewalMode), nullable=False, default=SubscriptionRenewalMode.MANUAL
    )
    trial_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[PlanStatus] = mapped_column(
        PersistedEnumType(PlanStatus), nullable=False, default=PlanStatus.ACTIVE, index=True
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", json_type, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
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
    component_type: Mapped[PlanPriceComponentType] = mapped_column(
        PersistedEnumType(PlanPriceComponentType), nullable=False
    )
    source_product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    source_bundle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bundles.id"), nullable=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


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
    period: Mapped[BillingPeriod] = mapped_column(PersistedEnumType(BillingPeriod), nullable=False)
    reset_policy: Mapped[PlanLimitResetPolicy] = mapped_column(
        PersistedEnumType(PlanLimitResetPolicy), nullable=False, default=PlanLimitResetPolicy.BILLING_PERIOD
    )
    overage_policy: Mapped[PlanLimitOveragePolicy] = mapped_column(
        PersistedEnumType(PlanLimitOveragePolicy), nullable=False, default=PlanLimitOveragePolicy.DENY
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
