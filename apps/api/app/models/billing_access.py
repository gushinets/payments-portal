from __future__ import annotations

from app.models._shared import (
    Base,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Mapped,
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


class PaidAccessState(Base):
    __tablename__ = "paid_access_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "tenant_id", "region"],
            ["users.id", "users.tenant_id", "users.region"],
            name="fk_paid_access_states_user_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "region",
            "user_id",
            name="uq_paid_access_states_tenant_region_user",
        ),
    )

    paid_access_state_id: Mapped[uuid.UUID] = mapped_column(
        uuid_type,
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(uuid_type, nullable=False)
    access_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    effective_state_schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    effective_state_document: Mapped[dict] = mapped_column(json_type, nullable=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccessInvalidationOutbox(Base):
    __tablename__ = "access_invalidation_outbox"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "tenant_id", "region"],
            ["users.id", "users.tenant_id", "users.region"],
            name="fk_access_invalidation_outbox_user_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "region",
            "user_id",
            name="uq_access_invalidation_outbox_tenant_region_user",
        ),
        CheckConstraint(
            "pending_revision > 0",
            name="ck_access_invalidation_outbox_pending_revision_positive",
        ),
        CheckConstraint(
            "pending_revision >= delivered_revision",
            name="ck_access_invalidation_outbox_revision_order",
        ),
        Index(
            "ix_access_invalidation_outbox_next_attempt_at",
            "next_attempt_at",
        ),
    )

    outbox_id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(uuid_type, nullable=False)
    pending_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    delivered_revision: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error_classification: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
