from __future__ import annotations

from app.models._shared import (
    Base,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Mapped,
    PersistedEnumType,
    Text,
    UniqueConstraint,
    datetime,
    func,
    mapped_column,
    text,
    uuid,
    uuid_type,
)
from app.models.enums import (
    ExternalSubscriptionCommercialAccessStatus,
    ExternalSubscriptionFinancialAccessStatus,
    ExternalSubscriptionLifecycleStatus,
)


class BillingProductAccessScope(Base):
    __tablename__ = "billing_product_access_scopes"
    __table_args__ = (
        UniqueConstraint(
            "access_scope_id",
            "user_id",
            "product_id",
            name="uq_billing_product_access_scopes_id_user_product",
        ),
        UniqueConstraint(
            "user_id",
            "product_id",
            name="uq_billing_product_access_scopes_user_product",
        ),
        ForeignKeyConstraint(
            ["primary_subscription_id", "user_id", "product_id"],
            [
                "external_subscriptions.subscription_id",
                "external_subscriptions.user_id",
                "external_subscriptions.product_id",
            ],
            name="fk_billing_product_access_scopes_primary_subscription",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_billing_product_access_scopes_primary_subscription",
            "primary_subscription_id",
        ),
    )

    access_scope_id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    product_id: Mapped[str] = mapped_column(Text, nullable=False)
    primary_subscription_id: Mapped[uuid.UUID | None] = mapped_column(uuid_type, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ExternalSubscription(Base):
    __tablename__ = "external_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id",
            "product_id",
            name="uq_external_subscriptions_id_product",
        ),
        UniqueConstraint(
            "subscription_id",
            "user_id",
            "product_id",
            name="uq_external_subscriptions_id_user_product",
        ),
        UniqueConstraint(
            "subscription_id",
            "external_billing_account_id",
            "user_id",
            "product_id",
            name="uq_external_subscriptions_id_account_user_product",
        ),
        ForeignKeyConstraint(
            ["customer_id", "external_billing_account_id", "user_id"],
            [
                "external_billing_customers.customer_id",
                "external_billing_customers.external_billing_account_id",
                "external_billing_customers.user_id",
            ],
            name="fk_external_subscriptions_customer_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
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
        ForeignKeyConstraint(
            ["mapping_revision_id", "external_billing_account_id"],
            [
                "commercial_mapping_revisions.mapping_revision_id",
                "commercial_mapping_revisions.external_billing_account_id",
            ],
            name="fk_external_subscriptions_mapping_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["latest_observation_id", "subscription_id"],
            [
                "billing_state_observations.observation_id",
                "billing_state_observations.subscription_id",
            ],
            name="fk_external_subscriptions_latest_observation",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "purchase_intent_id IS NULL OR mapping_revision_id IS NOT NULL",
            name="ck_external_subscriptions_purchase_mapping",
        ),
        CheckConstraint(
            "lifecycle_status IN ('active', 'inactive', 'ended')",
            name="ck_external_subscriptions_lifecycle_status",
        ),
        CheckConstraint(
            "financial_access_status IN ('allowed', 'blocked')",
            name="ck_external_subscriptions_financial_access_status",
        ),
        CheckConstraint(
            "commercial_access_status IN ('eligible', 'ineligible')",
            name="ck_external_subscriptions_commercial_access_status",
        ),
        CheckConstraint(
            "(reconciliation_lease_owner IS NULL AND reconciliation_lease_expires_at IS NULL) "
            "OR (reconciliation_lease_owner IS NOT NULL AND reconciliation_lease_expires_at IS NOT NULL)",
            name="ck_external_subscriptions_reconciliation_lease_pair",
        ),
        CheckConstraint(
            "reconciliation_fencing_token >= 0",
            name="ck_external_subscriptions_fencing_token_nonnegative",
        ),
        Index(
            "uq_external_subscriptions_purchase_intent",
            "purchase_intent_id",
            unique=True,
            postgresql_where=text("purchase_intent_id IS NOT NULL"),
            sqlite_where=text("purchase_intent_id IS NOT NULL"),
        ),
        Index(
            "ix_external_subscriptions_account_customer",
            "external_billing_account_id",
            "customer_id",
        ),
        Index(
            "ix_external_subscriptions_user_product_status",
            "user_id",
            "product_id",
            "lifecycle_status",
        ),
        Index(
            "ix_external_subscriptions_customer_product_status",
            "customer_id",
            "product_id",
            "lifecycle_status",
        ),
        Index(
            "ix_external_subscriptions_purchase_provenance",
            "purchase_intent_id",
            "customer_id",
            "mapping_revision_id",
        ),
        Index(
            "ix_external_subscriptions_mapping_provenance",
            "mapping_revision_id",
            "external_billing_account_id",
        ),
        Index("ix_external_subscriptions_external_id", "external_subscription_id"),
        Index("ix_external_subscriptions_agreement_id", "external_agreement_id"),
        Index("ix_external_subscriptions_lifecycle_status", "lifecycle_status"),
        Index("ix_external_subscriptions_financial_status", "financial_access_status"),
        Index("ix_external_subscriptions_commercial_status", "commercial_access_status"),
        Index("ix_external_subscriptions_last_read", "last_authoritative_read_at"),
        Index("ix_external_subscriptions_valid_until", "projection_valid_until"),
        Index("ix_external_subscriptions_lease_expiry", "reconciliation_lease_expires_at"),
        Index(
            "ix_external_subscriptions_reconciliation_claim",
            "projection_valid_until",
            "reconciliation_lease_expires_at",
        ),
        Index("ix_external_subscriptions_latest_observation", "latest_observation_id"),
    )

    subscription_id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    external_billing_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(uuid_type, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(uuid_type, nullable=False)
    product_id: Mapped[str] = mapped_column(Text, nullable=False)
    purchase_intent_id: Mapped[uuid.UUID | None] = mapped_column(uuid_type, nullable=True)
    mapping_revision_id: Mapped[uuid.UUID | None] = mapped_column(uuid_type, nullable=True)
    external_subscription_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_agreement_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    lifecycle_status: Mapped[ExternalSubscriptionLifecycleStatus] = mapped_column(
        PersistedEnumType(ExternalSubscriptionLifecycleStatus),
        nullable=False,
    )
    financial_access_status: Mapped[ExternalSubscriptionFinancialAccessStatus] = mapped_column(
        PersistedEnumType(ExternalSubscriptionFinancialAccessStatus),
        nullable=False,
    )
    commercial_access_status: Mapped[ExternalSubscriptionCommercialAccessStatus] = mapped_column(
        PersistedEnumType(ExternalSubscriptionCommercialAccessStatus),
        nullable=False,
    )
    last_authoritative_read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    projection_valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reconciliation_lease_owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    reconciliation_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reconciliation_fencing_token: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    latest_observation_id: Mapped[uuid.UUID | None] = mapped_column(uuid_type, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
