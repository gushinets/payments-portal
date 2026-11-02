from __future__ import annotations

from datetime import date
from sqlalchemy import Date

from app.models._shared import (
    Base,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Mapped,
    Text,
    datetime,
    func,
    mapped_column,
    uuid,
    uuid_type,
    json_type,
    UniqueConstraint,
)


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
        UniqueConstraint(
            "subscription_id",
            "source_component_id",
            "metric_key",
            "provider_cycle_key",
            name="uq_purchased_allowances_logical_cycle",
        ),
        CheckConstraint(
            "(cycle_schema_version = 'legacy-utc:v1' AND period_start IS NOT NULL AND period_end IS NOT NULL "
            "AND cycle_date_start IS NULL AND cycle_date_end IS NULL AND calendar_document IS NULL AND unit IS NULL AND terms_document IS NULL) OR "
            "(cycle_schema_version = 'calendar:v1' AND period_start IS NULL AND period_end IS NULL "
            "AND cycle_date_start IS NOT NULL AND cycle_date_end IS NOT NULL AND cycle_date_start <= cycle_date_end "
            "AND provider_cycle_start IS NULL AND provider_cycle_end IS NULL "
            "AND calendar_document IS NOT NULL AND unit IS NOT NULL AND terms_document IS NOT NULL AND provider_cycle_key IS NOT NULL) OR "
            "(cycle_schema_version = 'timestamp:v1' AND period_start IS NOT NULL AND period_end IS NOT NULL "
            "AND provider_cycle_start IS NOT NULL AND provider_cycle_end IS NOT NULL "
            "AND cycle_date_start IS NULL AND cycle_date_end IS NULL "
            "AND calendar_document IS NOT NULL AND unit IS NOT NULL AND terms_document IS NOT NULL AND provider_cycle_key IS NOT NULL)",
            name="ck_purchased_allowances_cycle_shape",
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
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cycle_schema_version: Mapped[str] = mapped_column(
        Text, nullable=False, default="legacy-utc:v1", server_default="legacy-utc:v1"
    )
    cycle_date_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    cycle_date_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    calendar_document: Mapped[dict | None] = mapped_column(json_type, nullable=True)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms_document: Mapped[dict | None] = mapped_column(json_type, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
