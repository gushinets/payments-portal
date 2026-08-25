from __future__ import annotations

from app.models._shared import (
    Base,
    DateTime,
    Decimal,
    ForeignKey,
    Index,
    Integer,
    Mapped,
    Numeric,
    String,
    Text,
    datetime,
    func,
    json_type,
    mapped_column,
    uuid,
    uuid_type,
)


class PaymentWebhookEvent(Base):
    __tablename__ = "payment_webhook_events"
    __table_args__ = (
        Index(
            "ix_payment_webhook_events_region_provider_received_at",
            "region",
            "provider",
            "received_at",
        ),
        Index(
            "ix_payment_webhook_events_provider_endpoint_event_type",
            "provider",
            "endpoint",
            "event_type",
        ),
        Index(
            "ix_payment_webhook_events_provider_event_id",
            "provider_account_id",
            "provider_event_id",
        ),
        Index("ix_payment_webhook_events_order_id", "order_id"),
        Index("ix_payment_webhook_events_payment_id", "payment_id"),
        Index(
            "ix_payment_webhook_events_idempotency_lookup",
            "provider_account_id",
            "idempotency_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, default="anytoolai", index=True)
    region: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, default="ru", index=True)
    provider_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payment_provider_accounts.id"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String, nullable=False, default="cloudpayments")
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"), nullable=True)
    amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict] = mapped_column(json_type, nullable=False)
    headers: Mapped[dict | None] = mapped_column(json_type, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="received")
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
