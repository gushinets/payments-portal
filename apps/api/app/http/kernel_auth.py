"""Reverse-direction service authentication with receiver-owned permissions."""

from dataclasses import dataclass
from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.core.settings import KernelAccessPermission, settings


@dataclass(frozen=True)
class KernelPrincipal:
    tenant_id: str
    region: str
    permissions: frozenset[KernelAccessPermission]


def authenticate_kernel(request: Request) -> KernelPrincipal:
    current, previous = settings.kernel_access_service_token, settings.kernel_access_service_token_previous
    if current is None:
        raise HTTPException(503, detail={"code": "kernel_session_unavailable"})
    headers = request.headers.getlist("authorization")
    authorization = headers[0] if len(headers) == 1 else ""
    scheme, _, supplied = authorization.partition(" ")
    supplied_bytes = supplied.encode("utf-8")
    current_matches = compare_digest(supplied_bytes, current.get_secret_value().encode("ascii"))
    previous_matches = compare_digest(supplied_bytes, previous.get_secret_value().encode("ascii") if previous else b"")
    if (
        scheme.lower() != "bearer"
        or not supplied
        or not (current_matches | (previous is not None and previous_matches))
    ):
        raise HTTPException(401, detail={"code": "service_unauthorized"}, headers={"WWW-Authenticate": "Bearer"})
    principal = KernelPrincipal(
        settings.instance_tenant_id, settings.instance_region, frozenset(settings.kernel_access_permissions)
    )
    for name, expected in (("tenant_id", principal.tenant_id), ("region", principal.region)):
        values = request.query_params.getlist(name)
        if values and values != [expected]:
            raise HTTPException(403, detail={"code": "kernel_session_forbidden"})
    return principal


def authorize_exchange(principal: Annotated[KernelPrincipal, Depends(authenticate_kernel)]) -> KernelPrincipal:
    if "kernel-session:exchange" not in principal.permissions:
        raise HTTPException(403, detail={"code": "kernel_session_forbidden"})
    return principal


def authorize_introspection(principal: Annotated[KernelPrincipal, Depends(authenticate_kernel)]) -> KernelPrincipal:
    if "kernel-session:introspect" not in principal.permissions:
        raise HTTPException(403, detail={"code": "kernel_session_forbidden"})
    return principal


async def authorize_snapshot(request: Request) -> KernelPrincipal:
    # Header-only authentication must not queue behind the shared sale threads
    # before reaching the reserved local read capacity.
    principal = authenticate_kernel(request)
    if "access-snapshot:read" not in principal.permissions:
        raise HTTPException(403, detail={"code": "access_snapshot_forbidden"})
    if set(request.query_params) != {"tenant_id", "region"}:
        raise HTTPException(422, detail={"code": "access_snapshot_scope_required"})
    return principal
