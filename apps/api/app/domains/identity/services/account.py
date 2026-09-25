from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.models import User


@dataclass(frozen=True)
class AccountSessionResult:
    tenant_id: str
    region: str
    user_id: uuid.UUID
    email: str


def load_account_session(*, user: User) -> AccountSessionResult:
    return AccountSessionResult(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        email=user.email,
    )
