from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import AuthSession, User

DEFAULT_TENANT_ID = "anytoolai"
DEFAULT_REGION = "ru"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_current_session(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> tuple[User, AuthSession]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_session")

    token = authorization.removeprefix("Bearer ").strip()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    session = db.query(AuthSession).filter(AuthSession.token_hash == token_hash).first()
    if (
        session is None
        or session.revoked_at is not None
        or as_utc(session.expires_at) <= utc_now()
    ):
        raise HTTPException(status_code=401, detail="invalid_session")

    user = (
        db.query(User)
        .filter(
            User.id == session.user_id,
            User.tenant_id == session.tenant_id,
            User.region == session.region,
        )
        .first()
    )
    if user is None:
        raise HTTPException(status_code=401, detail="invalid_session")

    session.last_seen_at = utc_now()
    db.add(session)
    db.commit()
    db.refresh(session)
    return user, session
