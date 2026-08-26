from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import User


def lock_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    return db.query(User).filter(User.id == user_id).with_for_update().first()
