from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def test_postgres_orm_round_trip_and_rollback(migrated_database: Engine) -> None:
    from app.models import AuthSession, User

    verified_at = datetime.now(timezone.utc)

    with Session(migrated_database) as session:
        user = User(
            tenant_id="anytoolai",
            region="ru",
            email="compatibility@example.com",
            email_normalized="compatibility@example.com",
            email_verified_at=verified_at,
            status="active",
            metadata_={"source": "sqlalchemy-compatibility"},
        )
        session.add(user)
        session.flush()
        session.add(
            AuthSession(
                tenant_id=user.tenant_id,
                region=user.region,
                user_id=user.id,
                token_hash="compatibility-token-hash",
                expires_at=verified_at + timedelta(hours=1),
                ip="127.0.0.1",
            )
        )
        session.commit()
        user_id = user.id

    with Session(migrated_database) as session:
        stored_user = session.scalar(select(User).where(User.id == user_id))
        stored_auth_session = session.scalar(
            select(AuthSession).where(AuthSession.user_id == user_id)
        )

        assert stored_user is not None
        assert isinstance(stored_user.id, uuid.UUID)
        assert stored_user.metadata_ == {"source": "sqlalchemy-compatibility"}
        assert stored_user.email_verified_at == verified_at
        assert stored_auth_session is not None
        assert str(stored_auth_session.ip) == "127.0.0.1"
        assert session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260729_0004"

        session.add(
            User(
                tenant_id=stored_user.tenant_id,
                region=stored_user.region,
                email="COMPATIBILITY@example.com",
                email_normalized=stored_user.email_normalized,
                status="active",
                metadata_={},
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

        session.rollback()
        assert session.scalar(select(User).where(User.id == user_id)) is not None
