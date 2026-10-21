from __future__ import annotations

from app.models._shared import (
    Base,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
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
from app.models.enums import PurchaseScopeHoldState


class BillingPurchaseScopeHold(Base):
    """Purchase serialization only; access-primary selection has a separate owner."""

    __tablename__ = "billing_purchase_scope_holds"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_purchase_scope_user_product"),
        ForeignKeyConstraint(
            ["user_id", "tenant_id", "region"],
            ["users.id", "users.tenant_id", "users.region"],
            name="fk_purchase_scope_user",
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
            name="fk_purchase_scope_intent",
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
            name="fk_purchase_scope_subscription",
            ondelete="RESTRICT",
        ),
        CheckConstraint("hold_state IN ('held', 'released')", name="ck_purchase_scope_state"),
        CheckConstraint("ownership_epoch > 0", name="ck_purchase_scope_epoch"),
        CheckConstraint(
            "purchase_intent_id IS NOT NULL OR subscription_id IS NOT NULL", name="ck_purchase_scope_owner"
        ),
        CheckConstraint(
            "(release_evidence_schema_version IS NULL AND release_evidence_document IS NULL) OR "
            "(release_evidence_schema_version IS NOT NULL AND release_evidence_schema_version = 'v1' "
            "AND release_evidence_document IS NOT NULL)",
            name="ck_purchase_scope_evidence_pair",
        ),
        CheckConstraint(
            "(hold_state = 'held' AND released_at IS NULL) OR "
            "(hold_state = 'released' AND released_at IS NOT NULL AND release_evidence_document IS NOT NULL)",
            name="ck_purchase_scope_release",
        ),
    )

    hold_id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(uuid_type, nullable=False)
    product_id: Mapped[str] = mapped_column(Text, nullable=False)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str] = mapped_column(Text, nullable=False)
    external_billing_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    purchase_intent_id: Mapped[uuid.UUID | None] = mapped_column(uuid_type, nullable=True)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(uuid_type, nullable=True)
    hold_state: Mapped[PurchaseScopeHoldState] = mapped_column(
        PersistedEnumType(PurchaseScopeHoldState),
        nullable=False,
        default=PurchaseScopeHoldState.HELD,
        server_default=text("'held'"),
    )
    ownership_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_evidence_schema_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    release_evidence_document: Mapped[dict | None] = mapped_column(json_type, nullable=True)
