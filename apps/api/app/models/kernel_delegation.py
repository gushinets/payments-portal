"""Hashed, single-use delegation credentials owned by an existing Portal session."""

from sqlalchemy import CheckConstraint

from app.models._shared import (
    Base,
    DateTime,
    ForeignKey,
    Mapped,
    Text,
    datetime,
    mapped_column,
    uuid,
    uuid_type,
)


class KernelSessionDelegation(Base):
    __tablename__ = "kernel_session_delegations"
    __table_args__ = (
        CheckConstraint(
            "(exchanged_at IS NULL AND token_hash IS NULL AND token_expires_at IS NULL) OR "
            "(exchanged_at IS NOT NULL AND token_hash IS NOT NULL AND token_expires_at IS NOT NULL)",
            name="ck_kernel_delegation_exchange_shape",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(uuid_type, primary_key=True, default=uuid.uuid4)
    auth_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    audience: Mapped[str] = mapped_column(Text, nullable=False)
    code_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    code_challenge: Mapped[str] = mapped_column(Text, nullable=False)
    code_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exchanged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_hash: Mapped[str | None] = mapped_column(Text, unique=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
