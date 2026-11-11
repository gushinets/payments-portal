"""Trusted backend identity from independent receiver-owned credentials."""

from dataclasses import dataclass
from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.backend_consumers import BackendConsumer, BackendPermission
from app.core.settings import settings

backend_service_bearer = HTTPBearer(
    scheme_name="BackendServiceBearer",
    auto_error=False,
    description="Backend-to-Portal service credential. Never the delegated user token or primary Portal bearer.",
)


@dataclass(frozen=True)
class BackendPrincipal:
    consumer: BackendConsumer

    @property
    def tenant_id(self) -> str:
        return self.consumer.tenant_id

    @property
    def region(self) -> str:
        return self.consumer.region


def authenticate_backend(
    request: Request,
    _credentials: Annotated[HTTPAuthorizationCredentials | None, Security(backend_service_bearer)],
) -> BackendPrincipal:
    if not settings.backend_consumers:
        raise HTTPException(503, detail={"code": "backend_session_unavailable"})
    headers = request.headers.getlist("authorization")
    scheme, _, supplied = (headers[0] if len(headers) == 1 else "").partition(" ")
    matched: BackendConsumer | None = None
    for consumer in settings.backend_consumers:
        current, previous = consumer.backend_to_portal_current_secret, consumer.backend_to_portal_previous_secret
        current_matches = compare_digest(supplied.encode(), current.get_secret_value().encode())
        previous_matches = compare_digest(supplied.encode(), previous.get_secret_value().encode() if previous else b"")
        if current_matches | (previous is not None and previous_matches):
            matched = consumer
    if scheme.lower() != "bearer" or not supplied or matched is None:
        raise HTTPException(401, detail={"code": "service_unauthorized"}, headers={"WWW-Authenticate": "Bearer"})
    principal = BackendPrincipal(matched)
    for name, expected in (
        ("tenant_id", principal.tenant_id),
        ("region", principal.region),
        ("consumer_id", matched.consumer_id),
    ):
        values = request.query_params.getlist(name)
        if values and values != [expected]:
            raise HTTPException(403, detail={"code": "backend_session_forbidden"})
    return principal


def authorize_exchange(principal: Annotated[BackendPrincipal, Depends(authenticate_backend)]) -> BackendPrincipal:
    if BackendPermission.EXCHANGE not in principal.consumer.permissions:
        raise HTTPException(403, detail={"code": "backend_session_forbidden"})
    return principal


def authorize_introspection(principal: Annotated[BackendPrincipal, Depends(authenticate_backend)]) -> BackendPrincipal:
    if BackendPermission.INTROSPECT not in principal.consumer.permissions:
        raise HTTPException(403, detail={"code": "backend_session_forbidden"})
    return principal


async def authorize_snapshot(
    request: Request,
    _credentials: Annotated[HTTPAuthorizationCredentials | None, Security(backend_service_bearer)],
) -> BackendPrincipal:
    principal = authenticate_backend(request, _credentials)
    if BackendPermission.READ_SNAPSHOT not in principal.consumer.permissions:
        raise HTTPException(403, detail={"code": "access_snapshot_forbidden"})
    if set(request.query_params) != {"tenant_id", "region"}:
        raise HTTPException(422, detail={"code": "access_snapshot_scope_required"})
    return principal
