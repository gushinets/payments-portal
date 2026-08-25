from __future__ import annotations

from app.models._shared import (
    Base,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Mapped,
    String,
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


class PaymentProviderAccount(Base):
    __tablename__ = "payment_provider_accounts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "region",
            "provider",
            "legal_entity_id",
            name="uq_pay_provider_accounts_tenant_region_provider_entity",
        ),
        Index("ix_payment_provider_accounts_region_enabled", "region", "enabled"),
        Index(
            "uq_payment_provider_accounts_default",
            "tenant_id",
            "region",
            "provider",
            unique=True,
            postgresql_where=text("legal_entity_id IS NULL"),
            sqlite_where=text("legal_entity_id IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("legal_entities.id"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    public_identifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    test_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict] = mapped_column(json_type, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
