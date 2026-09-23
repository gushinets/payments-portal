from __future__ import annotations

from app.models._shared import (
    Base,
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
    ExternalBillingCustomerBindingState,
    ExternalCreateOperationKind,
    PurchaseIntentState,
)


class ExternalBillingCustomer(Base):
    __tablename__ = "external_billing_customers"
    __table_args__ = (
        UniqueConstraint(
            "customer_id",
            "external_billing_account_id",
            "user_id",
            name="uq_external_billing_customers_id_account_user",
        ),
        UniqueConstraint(
            "external_billing_account_id",
            "user_id",
            name="uq_external_billing_customers_account_user",
        ),
        UniqueConstraint(
            "billing_customer_key",
            name="uq_external_billing_customers_billing_customer_key",
        ),
        CheckConstraint(
            "trim(billing_customer_key) <> ''",
            name="ck_external_billing_customers_key_nonempty",
        ),
        CheckConstraint(
            "binding_state IN ('unbound', 'bound', 'identity_conflict')",
            name="ck_external_billing_customers_binding_state",
        ),
        Index(
            "ix_external_billing_customers_provider_customer_id",
            "provider_customer_id",
        ),
        Index("ix_external_billing_customers_binding_state", "binding_state"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    external_billing_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    billing_customer_key: Mapped[str] = mapped_column(Text, nullable=False)
    provider_customer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    binding_state: Mapped[ExternalBillingCustomerBindingState] = mapped_column(
        PersistedEnumType(ExternalBillingCustomerBindingState),
        nullable=False,
        default=ExternalBillingCustomerBindingState.UNBOUND,
    )
    binding_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PurchaseIntent(Base):
    __tablename__ = "purchase_intents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["customer_id", "external_billing_account_id", "user_id"],
            [
                "external_billing_customers.customer_id",
                "external_billing_customers.external_billing_account_id",
                "external_billing_customers.user_id",
            ],
            name="fk_purchase_intents_customer_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["mapping_revision_id", "external_billing_account_id", "billing_offer_id"],
            [
                "commercial_mapping_revisions.mapping_revision_id",
                "commercial_mapping_revisions.external_billing_account_id",
                "commercial_mapping_revisions.billing_offer_id",
            ],
            name="fk_purchase_intents_mapping_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
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
        UniqueConstraint(
            "external_billing_account_id",
            "user_id",
            "client_idempotency_key",
            name="uq_purchase_intents_client_idempotency",
        ),
        UniqueConstraint(
            "purchase_intent_id",
            "customer_id",
            name="uq_purchase_intents_id_customer",
        ),
        UniqueConstraint(
            "purchase_intent_id",
            "external_billing_account_id",
            "user_id",
            "product_id",
            name="uq_purchase_intents_id_account_user_product",
        ),
        UniqueConstraint(
            "purchase_intent_id",
            "customer_id",
            "external_billing_account_id",
            "user_id",
            "product_id",
            "mapping_revision_id",
            name="uq_purchase_intents_full_scope",
        ),
        CheckConstraint(
            "trim(accepted_commercial_fingerprint) <> ''",
            name="ck_purchase_intents_fingerprint_nonempty",
        ),
        CheckConstraint(
            "trim(client_idempotency_key) <> ''",
            name="ck_purchase_intents_idempotency_nonempty",
        ),
        CheckConstraint(
            "trim(accepted_snapshot_schema_version) <> ''",
            name="ck_purchase_intents_snapshot_schema_nonempty",
        ),
        CheckConstraint(
            "state IN ('created', 'preparing', 'awaiting_external_result', 'linked', "
            "'resolved_no_external_effect', 'failed_before_external_effect', 'manual_review')",
            name="ck_purchase_intents_state",
        ),
        Index("ix_purchase_intents_user_product", "user_id", "product_id"),
        Index(
            "ix_purchase_intents_account_offer",
            "external_billing_account_id",
            "billing_offer_id",
        ),
        Index("ix_purchase_intents_customer_purchase", "customer_id", "purchase_intent_id"),
        Index("ix_purchase_intents_mapping_revision", "mapping_revision_id"),
        Index(
            "ix_purchase_intents_commercial_fingerprint",
            "accepted_commercial_fingerprint",
        ),
        Index("ix_purchase_intents_state", "state"),
        Index("ix_purchase_intents_state_updated_at", "state", "state_updated_at"),
    )

    purchase_intent_id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    external_billing_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(uuid_type, nullable=False)
    product_id: Mapped[str] = mapped_column(Text, nullable=False)
    billing_offer_id: Mapped[str] = mapped_column(Text, nullable=False)
    mapping_revision_id: Mapped[uuid.UUID] = mapped_column(uuid_type, nullable=False)
    accepted_commercial_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    client_idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[PurchaseIntentState] = mapped_column(
        PersistedEnumType(PurchaseIntentState),
        nullable=False,
        default=PurchaseIntentState.CREATED,
    )
    accepted_snapshot_schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_snapshot: Mapped[dict] = mapped_column(json_type, nullable=False)
    legal_acceptance_event_id: Mapped[uuid.UUID] = mapped_column(uuid_type, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    state_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExternalCreateOperation(Base):
    __tablename__ = "external_create_operations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["purchase_intent_id", "customer_id"],
            ["purchase_intents.purchase_intent_id", "purchase_intents.customer_id"],
            name="fk_external_create_operations_purchase_customer",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(operation_kind = 'customer' AND purchase_intent_id IS NULL) "
            "OR (operation_kind IN ('agreement', 'subscription') AND purchase_intent_id IS NOT NULL)",
            name="ck_external_create_operations_purchase_requirement",
        ),
        CheckConstraint(
            "operation_kind IN ('customer', 'agreement', 'subscription')",
            name="ck_external_create_operations_kind",
        ),
        CheckConstraint(
            "trim(request_correlation_key) <> ''",
            name="ck_external_create_operations_correlation_nonempty",
        ),
        CheckConstraint(
            "(unknown_since IS NULL AND unknown_recovery_deadline_at IS NULL) "
            "OR (unknown_since IS NOT NULL AND unknown_recovery_deadline_at IS NOT NULL)",
            name="ck_external_create_operations_unknown_pair",
        ),
        CheckConstraint(
            "unknown_recovery_deadline_at = unknown_since + interval '2 hours'",
            name="ck_external_create_operations_unknown_deadline",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "(recovery_hint_schema_version IS NULL AND recovery_hint_document IS NULL) "
            "OR (recovery_hint_schema_version IS NOT NULL AND recovery_hint_document IS NOT NULL)",
            name="ck_external_create_operations_recovery_hint_pair",
        ),
        Index(
            "uq_external_create_operations_unresolved_customer",
            "customer_id",
            unique=True,
            postgresql_where=text("operation_kind = 'customer' AND resolved_at IS NULL"),
            sqlite_where=text("operation_kind = 'customer' AND resolved_at IS NULL"),
        ),
        Index(
            "ix_external_create_operations_customer_state",
            "customer_id",
            "operation_state",
        ),
        Index("ix_external_create_operations_purchase", "purchase_intent_id"),
        Index(
            "ix_external_create_operations_correlation",
            "request_correlation_key",
        ),
        Index(
            "ix_external_create_operations_unknown_deadline",
            "unknown_recovery_deadline_at",
        ),
        Index(
            "ix_external_create_operations_bound_object",
            "bound_external_object_id",
        ),
        Index(
            "ix_external_create_operations_recovery_scan",
            "operation_state",
            "unknown_recovery_deadline_at",
            "updated_at",
        ),
    )

    create_operation_id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    operation_kind: Mapped[ExternalCreateOperationKind] = mapped_column(
        PersistedEnumType(ExternalCreateOperationKind),
        nullable=False,
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("external_billing_customers.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    purchase_intent_id: Mapped[uuid.UUID | None] = mapped_column(uuid_type, nullable=True)
    request_correlation_key: Mapped[str] = mapped_column(Text, nullable=False)
    operation_state: Mapped[str] = mapped_column(Text, nullable=False)
    unknown_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unknown_recovery_deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    recovery_hint_schema_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    recovery_hint_document: Mapped[dict | None] = mapped_column(json_type, nullable=True)
    bound_external_object_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
