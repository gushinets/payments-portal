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
    uuid,
    uuid_type,
)
from app.models.enums import BillingStateObservationKind


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
