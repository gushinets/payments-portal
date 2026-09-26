from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.settings import settings
from app.domains.identity.errors import InvalidAuthSessionError
from app.domains.identity.services.auth import authenticate_session
from app.models import AuthSession, User


def get_current_session(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> tuple[User, AuthSession]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_session")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        return authenticate_session(
            db,
            token=token,
            tenant_id=settings.instance_tenant_id,
            region=settings.instance_region,
        )
    except InvalidAuthSessionError as exc:
        raise HTTPException(status_code=401, detail="invalid_session") from exc
