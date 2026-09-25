from __future__ import annotations

from app.models._shared import (
    Base,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Mapped,
    Text,
    datetime,
    func,
    json_type,
    mapped_column,
    text,
    uuid,
    uuid_type,
)


class BillingWorkItem(Base):
    __tablename__ = "billing_work_items"
    __table_args__ = (
        CheckConstraint(
            "trim(payload_schema_version) <> ''",
            name="ck_billing_work_items_payload_schema_nonempty",
        ),
        CheckConstraint(
            "(lease_owner IS NULL AND lease_expires_at IS NULL) "
            "OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_billing_work_items_lease_pair",
        ),
        Index(
            "ix_billing_work_items_kind_state_due",
            "work_kind",
            "work_state",
            "next_attempt_at",
        ),
        Index(
            "ix_billing_work_items_scope",
            "scope_kind",
            "scope_reference",
        ),
        Index("ix_billing_work_items_coalescing_key", "coalescing_key"),
        Index(
            "ix_billing_work_items_priority_retry",
            "work_state",
            "priority",
            "next_attempt_at",
        ),
        Index("ix_billing_work_items_lease_expiry", "lease_expires_at"),
        Index(
            "ix_billing_work_items_claim_scan",
            "work_state",
            "lease_expires_at",
            "priority",
            "next_attempt_at",
        ),
        Index("ix_billing_work_items_kind_state", "work_kind", "work_state"),
    )

    work_item_id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    work_kind: Mapped[str] = mapped_column(Text, nullable=False)
    scope_kind: Mapped[str] = mapped_column(Text, nullable=False)
    scope_reference: Mapped[str] = mapped_column(Text, nullable=False)
    coalescing_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    payload_document: Mapped[dict] = mapped_column(json_type, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    work_state: Mapped[str] = mapped_column(Text, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_classification: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ExternalBillingWebhookDelivery(Base):
    __tablename__ = "external_billing_webhook_deliveries"
    __table_args__ = (
        CheckConstraint(
            "trim(payload_hash) <> ''",
            name="ck_external_billing_webhook_deliveries_hash_nonempty",
        ),
        CheckConstraint(
            "trim(correlation_schema_version) <> ''",
            name="ck_external_billing_webhook_deliveries_corr_schema_nonempty",
        ),
        CheckConstraint(
            "trim(evidence_schema_version) <> ''",
            name="ck_external_billing_webhook_deliveries_evidence_schema_nonempty",
        ),
        Index(
            "ix_external_billing_webhook_deliveries_account_received",
            "external_billing_account_id",
            "received_at",
        ),
        Index(
            "ix_external_billing_webhook_deliveries_processing_received",
            "processing_state",
            "received_at",
        ),
        Index("ix_external_billing_webhook_deliveries_received_at", "received_at"),
        Index("ix_external_billing_webhook_deliveries_provider_event", "provider_event_id"),
        Index("ix_external_billing_webhook_deliveries_payload_hash", "payload_hash"),
    )

    delivery_id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    external_billing_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_document: Mapped[dict] = mapped_column(json_type, nullable=False)
    evidence_schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_document: Mapped[dict] = mapped_column(json_type, nullable=False)
    processing_state: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_classification: Mapped[str | None] = mapped_column(Text, nullable=True)


class ManualReviewCase(Base):
    __tablename__ = "manual_review_cases"
    __table_args__ = (
        CheckConstraint(
            "trim(evidence_schema_version) <> ''",
            name="ck_manual_review_cases_evidence_schema_nonempty",
        ),
        Index("ix_manual_review_cases_reason_state", "reason_code", "case_state"),
        Index("ix_manual_review_cases_scope", "scope_kind", "scope_reference"),
        Index("ix_manual_review_cases_state", "case_state"),
        Index("ix_manual_review_cases_state_created", "case_state", "created_at"),
        Index("ix_manual_review_cases_resolved_by", "resolved_by_principal"),
    )

    review_case_id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    scope_kind: Mapped[str] = mapped_column(Text, nullable=False)
    scope_reference: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_document: Mapped[dict] = mapped_column(json_type, nullable=False)
    case_state: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_principal: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_schema_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_document: Mapped[dict | None] = mapped_column(json_type, nullable=True)
