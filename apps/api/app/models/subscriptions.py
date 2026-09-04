from __future__ import annotations

from app.models.enums import (
    EntitlementSource,
    EntitlementStatus,
    SubscriptionEventType,
    SubscriptionRenewalMode,
    SubscriptionScopeType,
    SubscriptionStatus,
)
from app.models._shared import (
    Base,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Mapped,
    PersistedEnumType,
    Text,
    UniqueConstraint,
    all_access_scope_sql,
    bundle_scope_sql,
    datetime,
    func,
    json_type,
    live_subscription_statuses_sql,
    mapped_column,
    product_scope_sql,
    text,
    uuid,
    uuid_type,
)


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            f"'{SubscriptionStatus.TRIALING.value}', '{SubscriptionStatus.ACTIVE.value}', "
            f"'{SubscriptionStatus.PAST_DUE.value}', '{SubscriptionStatus.CANCELED.value}', "
            f"'{SubscriptionStatus.EXPIRED.value}', '{SubscriptionStatus.REFUNDED.value}', "
            f"'{SubscriptionStatus.PAUSED.value}')",
            name="ck_subscriptions_status",
        ),
        CheckConstraint(
            f"renewal_mode IN ('{SubscriptionRenewalMode.MANUAL.value}', '{SubscriptionRenewalMode.AUTOMATIC.value}')",
            name="ck_subscriptions_renewal_mode",
        ),
        CheckConstraint(
            f"(scope_type = '{product_scope_sql}' AND product_id IS NOT NULL AND bundle_id IS NULL)"
            f" OR (scope_type = '{bundle_scope_sql}' AND product_id IS NULL AND bundle_id IS NOT NULL)"
            f" OR (scope_type = '{all_access_scope_sql}' AND product_id IS NULL AND bundle_id IS NULL)",
            name="ck_subscriptions_scope_references",
        ),
        CheckConstraint(
            "trial_start_at IS NULL OR (trial_end_at IS NOT NULL AND trial_end_at > trial_start_at)",
            name="ck_subscriptions_trial_period",
        ),
        CheckConstraint(
            "current_period_end > current_period_start",
            name="ck_subscriptions_current_period",
        ),
        Index("ix_subscriptions_user_region_status", "user_id", "region", "status"),
        Index(
            "uq_subscriptions_live_product_scope",
            "tenant_id",
            "region",
            "user_id",
            "product_id",
            unique=True,
            postgresql_where=text(f"scope_type = '{product_scope_sql}' AND {live_subscription_statuses_sql}"),
            sqlite_where=text(f"scope_type = '{product_scope_sql}' AND {live_subscription_statuses_sql}"),
        ),
        Index(
            "uq_subscriptions_live_bundle_scope",
            "tenant_id",
            "region",
            "user_id",
            "bundle_id",
            unique=True,
            postgresql_where=text(f"scope_type = '{bundle_scope_sql}' AND {live_subscription_statuses_sql}"),
            sqlite_where=text(f"scope_type = '{bundle_scope_sql}' AND {live_subscription_statuses_sql}"),
        ),
        Index(
            "uq_subscriptions_live_all_access_scope",
            "tenant_id",
            "region",
            "user_id",
            unique=True,
            postgresql_where=text(f"scope_type = '{all_access_scope_sql}' AND {live_subscription_statuses_sql}"),
            sqlite_where=text(f"scope_type = '{all_access_scope_sql}' AND {live_subscription_statuses_sql}"),
        ),
        Index(
            "uq_subscriptions_provider_reference",
            "provider_account_id",
            "provider_subscription_id",
            unique=True,
            postgresql_where=text("provider_account_id IS NOT NULL AND provider_subscription_id IS NOT NULL"),
            sqlite_where=text("provider_account_id IS NOT NULL AND provider_subscription_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"), nullable=False, index=True)
    scope_type: Mapped[SubscriptionScopeType] = mapped_column(PersistedEnumType(SubscriptionScopeType), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    bundle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bundles.id"), nullable=True)
    status: Mapped[SubscriptionStatus] = mapped_column(
        PersistedEnumType(SubscriptionStatus), nullable=False, default=SubscriptionStatus.TRIALING, index=True
    )
    renewal_mode: Mapped[SubscriptionRenewalMode] = mapped_column(
        PersistedEnumType(SubscriptionRenewalMode), nullable=False, default=SubscriptionRenewalMode.MANUAL
    )
    trial_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payment_provider_accounts.id"), nullable=True, index=True
    )
    provider_subscription_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    recurring_consent_acceptance_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_acceptances.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Entitlement(Base):
    __tablename__ = "entitlements"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            f"'{EntitlementStatus.ACTIVE.value}', '{EntitlementStatus.EXPIRED.value}', "
            f"'{EntitlementStatus.REVOKED.value}', '{EntitlementStatus.SUPERSEDED.value}')",
            name="ck_entitlements_status",
        ),
        CheckConstraint(
            f"source IN ('{EntitlementSource.TRIAL.value}', '{EntitlementSource.ORDER.value}')",
            name="ck_entitlements_source",
        ),
        CheckConstraint(
            f"(scope_type = '{product_scope_sql}' AND product_id IS NOT NULL AND bundle_id IS NULL)"
            f" OR (scope_type = '{bundle_scope_sql}' AND product_id IS NULL AND bundle_id IS NOT NULL)"
            f" OR (scope_type = '{all_access_scope_sql}' AND product_id IS NULL AND bundle_id IS NULL)",
            name="ck_entitlements_scope_references",
        ),
        CheckConstraint(
            "valid_until > valid_from",
            name="ck_entitlements_valid_period",
        ),
        CheckConstraint(
            f"(source = '{EntitlementSource.TRIAL.value}' AND order_id IS NULL)"
            f" OR (source = '{EntitlementSource.ORDER.value}' AND order_id IS NOT NULL)",
            name="ck_entitlements_source_order",
        ),
        Index("ix_entitlements_user_region_status", "user_id", "region", "status"),
        Index("ix_entitlements_subscription_id", "subscription_id"),
        Index("ix_entitlements_subscription_status_validity", "subscription_id", "status", "valid_from", "valid_until"),
        Index("ix_entitlements_order_status_validity", "order_id", "status", "valid_from", "valid_until"),
        Index("ix_entitlements_plan_id", "plan_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subscriptions.id"), nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"), nullable=False)
    scope_type: Mapped[SubscriptionScopeType] = mapped_column(PersistedEnumType(SubscriptionScopeType), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    bundle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bundles.id"), nullable=True)
    status: Mapped[EntitlementStatus] = mapped_column(
        PersistedEnumType(EntitlementStatus), nullable=False, default=EntitlementStatus.ACTIVE, index=True
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[EntitlementSource] = mapped_column(PersistedEnumType(EntitlementSource), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"), nullable=True, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_entitlement_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("entitlements.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SubscriptionEvent(Base):
    __tablename__ = "subscription_events"
    __table_args__ = (
        Index("ix_subscription_events_subscription_occurred_at", "subscription_id", "occurred_at"),
        Index("ix_subscription_events_order_id", "order_id"),
        Index("ix_subscription_events_payment_id", "payment_id"),
        Index("ix_subscription_events_refund_id", "refund_id"),
        Index("ix_subscription_events_webhook_event_id", "webhook_event_id"),
        UniqueConstraint("operation_idempotency_key", name="uq_subscription_events_operation_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subscriptions.id"), nullable=False, index=True)
    event_type: Mapped[SubscriptionEventType] = mapped_column(PersistedEnumType(SubscriptionEventType), nullable=False)
    previous_status: Mapped[SubscriptionStatus | None] = mapped_column(
        PersistedEnumType(SubscriptionStatus), nullable=True
    )
    next_status: Mapped[SubscriptionStatus | None] = mapped_column(PersistedEnumType(SubscriptionStatus), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    operation_idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"), nullable=True)
    refund_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("refunds.id"), nullable=True)
    webhook_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payment_webhook_events.id"), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", json_type, nullable=False, default=dict)
