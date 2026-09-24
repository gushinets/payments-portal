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
    json_type,
    mapped_column,
    text,
    uuid,
    uuid_type,
)
from app.models.enums import (
    BillingStateObservationKind,
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
    reconciliation_fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    latest_observation_id: Mapped[uuid.UUID | None] = mapped_column(uuid_type, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class BillingStateObservation(Base):
    __tablename__ = "billing_state_observations"
    __table_args__ = (
        UniqueConstraint(
            "observation_id",
            "access_scope_id",
            name="uq_billing_state_observations_id_scope",
        ),
        UniqueConstraint(
            "observation_id",
            "subscription_id",
            name="uq_billing_state_observations_id_subscription",
        ),
        ForeignKeyConstraint(
            ["access_scope_id", "user_id", "product_id"],
            [
                "billing_product_access_scopes.access_scope_id",
                "billing_product_access_scopes.user_id",
                "billing_product_access_scopes.product_id",
            ],
            name="fk_billing_state_observations_access_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
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
        ForeignKeyConstraint(
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
        ForeignKeyConstraint(
            ["basis_observation_id", "access_scope_id"],
            [
                "billing_state_observations.observation_id",
                "billing_state_observations.access_scope_id",
            ],
            name="fk_billing_state_observations_basis_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "subscription_id IS NULL OR purchase_intent_id IS NULL",
            name="ck_billing_state_observations_provenance_exclusive",
        ),
        CheckConstraint(
            "(access_scope_id IS NULL AND subscription_id IS NULL AND purchase_intent_id IS NULL) "
            "OR (user_id IS NOT NULL AND product_id IS NOT NULL)",
            name="ck_billing_state_observations_subject_shape",
        ),
        CheckConstraint(
            "observation_kind IN ('authoritative_subscription_read', 'target_product_discovery', "
            "'primary_selection', 'deterministic_access_boundary')",
            name="ck_billing_state_observations_kind",
        ),
        CheckConstraint(
            "(observation_kind <> 'authoritative_subscription_read' OR subscription_id IS NOT NULL) "
            "AND (observation_kind <> 'target_product_discovery' OR "
            "(user_id IS NOT NULL AND product_id IS NOT NULL AND access_scope_id IS NOT NULL)) "
            "AND (observation_kind <> 'primary_selection' OR "
            "(access_scope_id IS NOT NULL AND basis_observation_id IS NOT NULL)) "
            "AND (observation_kind <> 'deterministic_access_boundary' OR "
            "(access_scope_id IS NOT NULL AND subscription_id IS NOT NULL AND effective_at IS NOT NULL))",
            name="ck_billing_state_observations_kind_shape",
        ),
        CheckConstraint(
            "trim(evidence_schema_version) <> ''",
            name="ck_billing_state_observations_evidence_schema_nonempty",
        ),
        Index(
            "ix_billing_state_observations_kind_time",
            "observation_kind",
            "observed_at",
        ),
        Index(
            "ix_billing_state_observations_account_kind_time",
            "external_billing_account_id",
            "observation_kind",
            "observed_at",
        ),
        Index(
            "ix_billing_state_observations_user_product_time",
            "user_id",
            "product_id",
            "observed_at",
        ),
        Index(
            "ix_billing_state_observations_scope_time",
            "access_scope_id",
            "observed_at",
        ),
        Index(
            "ix_billing_state_observations_subscription_time",
            "subscription_id",
            "observed_at",
        ),
        Index(
            "ix_billing_state_observations_purchase_time",
            "purchase_intent_id",
            "observed_at",
        ),
        Index("ix_billing_state_observations_work_item", "work_item_id"),
        Index("ix_billing_state_observations_basis", "basis_observation_id"),
        Index("ix_billing_state_observations_effective_at", "effective_at"),
        Index("ix_billing_state_observations_completeness", "completeness_classification"),
        Index("ix_billing_state_observations_result", "result_classification"),
        Index(
            "ix_billing_state_observations_scope_revision",
            "access_scope_id",
            "resulting_access_revision",
        ),
    )

    observation_id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    observation_kind: Mapped[BillingStateObservationKind] = mapped_column(
        PersistedEnumType(BillingStateObservationKind),
        nullable=False,
    )
    external_billing_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    product_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_scope_id: Mapped[uuid.UUID | None] = mapped_column(uuid_type, nullable=True)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(uuid_type, nullable=True)
    purchase_intent_id: Mapped[uuid.UUID | None] = mapped_column(uuid_type, nullable=True)
    work_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("billing_work_items.work_item_id", ondelete="SET NULL"),
        nullable=True,
    )
    basis_observation_id: Mapped[uuid.UUID | None] = mapped_column(uuid_type, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_document: Mapped[dict] = mapped_column(json_type, nullable=False)
    completeness_classification: Mapped[str] = mapped_column(Text, nullable=False)
    result_classification: Mapped[str] = mapped_column(Text, nullable=False)
    resulting_access_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PurchasedAllowance(Base):
    __tablename__ = "purchased_allowances"
    __table_args__ = (
        ForeignKeyConstraint(
            ["subscription_id", "product_id"],
            [
                "external_subscriptions.subscription_id",
                "external_subscriptions.product_id",
            ],
            name="fk_purchased_allowances_subscription_product",
            ondelete="RESTRICT",
        ),
        CheckConstraint("quantity >= 0", name="ck_purchased_allowances_quantity_nonnegative"),
        CheckConstraint(
            "(provider_cycle_start IS NULL AND provider_cycle_end IS NULL) "
            "OR (provider_cycle_start IS NOT NULL AND provider_cycle_end IS NOT NULL)",
            name="ck_purchased_allowances_provider_cycle_pair",
        ),
        CheckConstraint(
            "period_start < period_end",
            name="ck_purchased_allowances_period_order",
        ),
        Index("ix_purchased_allowances_provider_cycle_key", "provider_cycle_key"),
        Index(
            "ix_purchased_allowances_subscription_cycle",
            "subscription_id",
            "provider_cycle_key",
        ),
        Index(
            "ix_purchased_allowances_subscription_component_cycle",
            "subscription_id",
            "source_component_id",
            "provider_cycle_key",
        ),
        Index(
            "ix_purchased_allowances_product_metric",
            "product_id",
            "metric_key",
        ),
    )

    allowance_id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID] = mapped_column(uuid_type, nullable=False)
    source_component_id: Mapped[str] = mapped_column(Text, nullable=False)
    product_id: Mapped[str] = mapped_column(Text, nullable=False)
    metric_key: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider_cycle_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_cycle_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_cycle_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

