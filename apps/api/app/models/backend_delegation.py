"""Hashed, single-use delegation credentials owned by an existing Portal session."""

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Integer

from app.models._shared import (
    Base,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Mapped,
    Text,
    datetime,
    mapped_column,
    uuid,
    uuid_type,
)


class BackendSessionDelegation(Base):
    __tablename__ = "backend_session_delegations"
    __table_args__ = (
        CheckConstraint(
            "(exchanged_at IS NULL AND token_hash IS NULL AND token_expires_at IS NULL) OR "
            "(exchanged_at IS NOT NULL AND token_hash IS NOT NULL AND token_expires_at IS NOT NULL)",
            name="ck_backend_delegation_exchange_shape",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    auth_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    consumer_id: Mapped[str] = mapped_column(Text, nullable=False)
    code_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    code_challenge: Mapped[str] = mapped_column(Text, nullable=False)
    code_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exchanged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_hash: Mapped[str | None] = mapped_column(Text, unique=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BackendConsumerPolicy(Base):
    """Monotonic installation guard; secrets and callbacks are never persisted."""

    __tablename__ = "backend_consumer_policies"
    __table_args__ = (CheckConstraint("consumer_policy_revision > 0", name="ck_backend_policy_positive"),)

    consumer_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, primary_key=True)
    region: Mapped[str] = mapped_column(Text, primary_key=True)
    consumer_policy_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    policy_digest: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_delivery_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class BackendCodeIssuanceBudget(Base):
    """Successful code issuances, independent of credential retention and parent sessions."""

    __tablename__ = "backend_code_issuance_budgets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "tenant_id", "region"],
            ["users.id", "users.tenant_id", "users.region"],
            name="fk_backend_code_budget_user_scope",
            ondelete="CASCADE",
        ),
        CheckConstraint("issued_count > 0 AND issued_count <= 60", name="ck_backend_code_budget_count"),
    )

    tenant_id: Mapped[str] = mapped_column(Text, primary_key=True)
    region: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True)
    consumer_id: Mapped[str] = mapped_column(Text, primary_key=True)
    issued_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
