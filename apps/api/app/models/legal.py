from __future__ import annotations

from app.models.enums import AcceptanceKind, LegalEntityStatus, LegalEntityType
from app.models._shared import (
    Base,
    Boolean,
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
    ip_type,
    json_type,
    mapped_column,
    text,
    uuid,
    uuid_type,
)


class LegalEntity(Base):
    __tablename__ = "legal_entities"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", "region", name="uq_legal_entities_id_tenant_region"),
        Index("ix_legal_entities_tenant_region_status", "tenant_id", "region", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[LegalEntityType] = mapped_column(PersistedEnumType(LegalEntityType), nullable=False)
    tax_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    registration_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    legal_address: Mapped[str] = mapped_column(Text, nullable=False)
    support_email: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[LegalEntityStatus] = mapped_column(
        PersistedEnumType(LegalEntityStatus), nullable=False, default=LegalEntityStatus.ACTIVE, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["legal_entity_id", "tenant_id", "region"],
            ["legal_entities.id", "legal_entities.tenant_id", "legal_entities.region"],
            name="fk_document_versions_legal_entity_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "region",
            "doc_type",
            "version",
            name="uq_document_versions_tenant_region_doc_type_version",
        ),
        UniqueConstraint(
            "id",
            "tenant_id",
            "region",
            name="uq_document_versions_id_tenant_region",
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
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(uuid_type, nullable=False, index=True)
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
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class LegalAcceptanceEvent(Base):
    __tablename__ = "legal_acceptance_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "tenant_id", "region"],
            ["users.id", "users.tenant_id", "users.region"],
            name="fk_legal_acceptance_events_user_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(external_billing_account_id IS NULL "
            "AND billing_offer_id IS NULL "
            "AND accepted_commercial_fingerprint IS NULL) "
            "OR (external_billing_account_id IS NOT NULL "
            "AND trim(external_billing_account_id) <> '' "
            "AND billing_offer_id IS NOT NULL "
            "AND trim(billing_offer_id) <> '' "
            "AND accepted_commercial_fingerprint IS NOT NULL "
            "AND trim(accepted_commercial_fingerprint) <> '')",
            name="ck_legal_acceptance_events_commercial_triplet",
        ),
        UniqueConstraint(
            "id",
            "user_id",
            "external_billing_account_id",
            "billing_offer_id",
            "accepted_commercial_fingerprint",
            name="uq_legal_acceptance_events_purchase_binding",
        ),
        UniqueConstraint(
            "id",
            "tenant_id",
            "region",
            "user_id",
            name="uq_legal_acceptance_events_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(uuid_type, nullable=False, index=True)
    external_billing_account_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    billing_offer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_commercial_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    ip: Mapped[str | None] = mapped_column(ip_type, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DocumentAcceptance(Base):
    __tablename__ = "document_acceptances"
    __table_args__ = (
        ForeignKeyConstraint(
            ["legal_acceptance_event_id", "tenant_id", "region", "user_id"],
            [
                "legal_acceptance_events.id",
                "legal_acceptance_events.tenant_id",
                "legal_acceptance_events.region",
                "legal_acceptance_events.user_id",
            ],
            name="fk_document_acceptances_event_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["document_version_id", "tenant_id", "region"],
            ["document_versions.id", "document_versions.tenant_id", "document_versions.region"],
            name="fk_document_acceptances_document_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "legal_acceptance_event_id",
            "document_version_id",
            name="uq_document_acceptances_event_document",
        ),
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
    legal_acceptance_event_id: Mapped[uuid.UUID] = mapped_column(uuid_type, nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(uuid_type, nullable=False, index=True)
    guest_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    entrypoint_session_id: Mapped[uuid.UUID | None] = mapped_column(uuid_type, nullable=True)
    document_version_id: Mapped[uuid.UUID] = mapped_column(uuid_type, nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    acceptance_kind: Mapped[AcceptanceKind] = mapped_column(PersistedEnumType(AcceptanceKind), nullable=False)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
