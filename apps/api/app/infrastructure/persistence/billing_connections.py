"""Shared PostgreSQL serialization for origin-backed connection admission."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.errors import AppError


class ConnectionScopeBusy(Exception):
    """Only a known PostgreSQL lock timeout is expected contention."""


class ConnectionIsolationUnsupported(AppError):
    def __init__(self) -> None:
        super().__init__("billing_connection_isolation_unsupported")


def connection_lock_key(tenant_id: str, region: str, provider_origin: str) -> int:
    """Stable v1 key shared by legacy/default aliases and rotated credentials.

    Hash collisions only serialize unrelated connections. SQL evidence still
    decides scope; acquiring the lock never establishes provider identity.
    """
    encoded = json.dumps(
        ["payments-portal/connection-scope/v1", tenant_id, region, provider_origin],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big", signed=True)


def lock_connection_scope(db: Session, *, tenant_id: str, region: str, provider_origin: str) -> None:
    """Lock before scope reads, through commit/rollback; inherit caller budgets.

    READ COMMITTED must observe a predecessor's commit after waiting, even if
    authentication already read rows. Row locks cannot protect an absent first
    head/customer. No connection, credential, or commercial registry is created.
    """
    if not tenant_id or not region or not provider_origin:
        raise ValueError("connection lock requires deployment scope and normalized origin")
    if db.get_bind().dialect.name != "postgresql" or db.connection().get_isolation_level() != "READ COMMITTED":
        raise ConnectionIsolationUnsupported()
    try:
        db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": connection_lock_key(tenant_id, region, provider_origin)},
        )
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) == "55P03":
            raise ConnectionScopeBusy() from None
        raise
