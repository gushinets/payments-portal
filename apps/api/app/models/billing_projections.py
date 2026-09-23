from __future__ import annotations

from app.models._shared import (
    Base,
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Mapped,
    Text,
    UniqueConstraint,
    datetime,
    json_type,
    mapped_column,
    uuid,
    uuid_type,
)


class CapabilityManifestProjection(Base):
    __tablename__ = "capability_manifest_projections"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "region",
            name="uq_capability_manifest_projections_scope",
        ),
        Index(
            "ix_capability_manifest_projections_manifest_version",
            "manifest_version",
        ),
        Index(
            "ix_capability_manifest_projections_last_sync",
            "last_complete_sync_at",
        ),
    )

    projection_id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_version: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_complete_sync_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    manifest_document: Mapped[dict] = mapped_column(json_type, nullable=False)


class ExternalBillingCatalogProjection(Base):
    __tablename__ = "external_billing_catalog_projections"
    __table_args__ = (
        UniqueConstraint(
            "external_billing_account_id",
            name="uq_external_billing_catalog_projections_account",
        ),
        Index(
            "ix_external_billing_catalog_projections_catalog_version",
            "catalog_version",
        ),
        Index(
            "ix_external_billing_catalog_projections_catalog_digest",
            "catalog_digest",
        ),
        Index(
            "ix_external_billing_catalog_projections_last_sync",
            "last_complete_sync_at",
        ),
    )

    projection_id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    external_billing_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    catalog_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    catalog_digest: Mapped[str] = mapped_column(Text, nullable=False)
    last_complete_sync_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    catalog_document: Mapped[dict] = mapped_column(json_type, nullable=False)


class CommercialMappingRevision(Base):
    __tablename__ = "commercial_mapping_revisions"
    __table_args__ = (
        UniqueConstraint(
            "mapping_revision_id",
            "external_billing_account_id",
            name="uq_commercial_mapping_revisions_id_account",
        ),
        UniqueConstraint(
            "mapping_revision_id",
            "external_billing_account_id",
            "billing_offer_id",
            name="uq_commercial_mapping_revisions_id_account_offer",
        ),
        UniqueConstraint(
            "external_billing_account_id",
            "billing_offer_id",
            "revision_number",
            name="uq_commercial_mapping_revisions_account_offer_revision",
        ),
        CheckConstraint(
            "revision_number > 0",
            name="ck_commercial_mapping_revisions_revision_positive",
        ),
        CheckConstraint(
            "trim(mapping_schema_version) <> ''",
            name="ck_commercial_mapping_revisions_schema_nonempty",
        ),
        Index(
            "ix_commercial_mapping_revisions_publication",
            "external_billing_account_id",
            "billing_offer_id",
            "published_at",
        ),
        Index(
            "ix_commercial_mapping_revisions_manifest",
            "external_billing_account_id",
            "billing_offer_id",
            "manifest_version",
        ),
        Index(
            "ix_commercial_mapping_revisions_principal",
            "published_by_principal",
        ),
    )

    mapping_revision_id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    external_billing_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    billing_offer_id: Mapped[str] = mapped_column(Text, nullable=False)
    revision_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    manifest_version: Mapped[str] = mapped_column(Text, nullable=False)
    catalog_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    catalog_digest: Mapped[str] = mapped_column(Text, nullable=False)
    mapping_schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    mapping_document: Mapped[dict] = mapped_column(json_type, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_by_principal: Mapped[str] = mapped_column(Text, nullable=False)
