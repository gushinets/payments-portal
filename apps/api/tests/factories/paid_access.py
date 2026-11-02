"""Explicit simulated paid projection factories; no current terms fallback."""

from app.domains.billing.paid_contracts import EffectiveState, PaidGrant
from app.core.time import utc_now
from app.models import AuthSession, User
from datetime import timedelta
import hashlib
from uuid import uuid4


def grant_document(product: str) -> dict:
    return EffectiveState(grants=(PaidGrant(product_id=product),)).model_dump(mode="json")


def reader_identity(
    token: str, *, verified: bool = True, tenant: str = "anytoolai", region: str = "ru"
) -> tuple[User, AuthSession]:
    identity = uuid4()
    user = User(
        id=identity,
        tenant_id=tenant,
        region=region,
        email=f"{identity}@example.test",
        email_normalized=f"{identity}@example.test",
        email_verified_at=utc_now() if verified else None,
    )
    session = AuthSession(
        user_id=identity,
        tenant_id=tenant,
        region=region,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=utc_now() + timedelta(days=1),
    )
    return user, session
