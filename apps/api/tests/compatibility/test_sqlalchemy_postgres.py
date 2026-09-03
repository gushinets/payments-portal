from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.tests.support.postgres import alembic_test_config
from app.models import AuthSession, Payment, PaymentWebhookEvent, User, UserStatus

pytestmark = pytest.mark.postgres


def test_postgres_orm_round_trip_and_rollback(migrated_database: Engine) -> None:
    with alembic_test_config(migrated_database.url) as config:
        expected_alembic_head = ScriptDirectory.from_config(config).get_current_head()

    assert PaymentWebhookEvent.__table__.c.raw_payload.type.compile(dialect=migrated_database.dialect) == "JSONB"
    payment_id_index = next(
        index for index in Payment.__table__.indexes if index.name == "uq_payments_provider_account_payment_id"
    )
    assert payment_id_index.unique is True
    assert str(payment_id_index.dialect_options["postgresql"]["where"]) == ("provider_payment_id IS NOT NULL")
    assert {foreign_key.target_fullname for foreign_key in Payment.__table__.c.order_id.foreign_keys} == {"orders.id"}

    verified_at = datetime.now(timezone.utc)

    with Session(migrated_database) as session:
        user = User(
            tenant_id="anytoolai",
            region="ru",
            email="compatibility@example.com",
            email_normalized="compatibility@example.com",
            email_verified_at=verified_at,
            status=UserStatus.ACTIVE,
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
        stored_auth_session = session.scalar(select(AuthSession).where(AuthSession.user_id == user_id))

        assert stored_user is not None
        assert isinstance(stored_user.id, uuid.UUID)
        assert stored_user.metadata_ == {"source": "sqlalchemy-compatibility"}
        assert stored_user.email_verified_at == verified_at
        assert stored_auth_session is not None
        assert str(stored_auth_session.ip) == "127.0.0.1"
        assert session.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == expected_alembic_head

        session.add(
            User(
                tenant_id=stored_user.tenant_id,
                region=stored_user.region,
                email="COMPATIBILITY@example.com",
                email_normalized=stored_user.email_normalized,
                status=UserStatus.ACTIVE,
                metadata_={},
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

        session.rollback()
        assert session.scalar(select(User).where(User.id == user_id)) is not None

        session.add(
            AuthSession(
                tenant_id=stored_user.tenant_id,
                region=stored_user.region,
                user_id=uuid.uuid4(),
                token_hash="missing-user-token-hash",
                expires_at=verified_at + timedelta(hours=1),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

        session.rollback()
        assert session.scalar(select(User).where(User.id == user_id)) is not None
