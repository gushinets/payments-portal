"""PostgreSQL mechanics only; the application owns the outer transaction."""

from __future__ import annotations

import hashlib
import json
import math
import time

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.errors import AppError


class MappingStorageBusy(AppError):
    def __init__(self) -> None:
        super().__init__("mapping_storage_busy")


class MappingStorageDeadline(AppError):
    def __init__(self) -> None:
        super().__init__("mapping_publication_expired")


def mapping_lock_key(account_id: str, offer_id: str) -> int:
    """v1 key = signed first 64 SHA-256 bits of compact UTF-8 JSON below.

    Account/offer is the table's unique scope (including first publication).
    Hash collisions merely serialize unrelated work; SQL predicates still
    establish identity. All publishers must use this namespaced v1 convention.
    """
    encoded = json.dumps(
        ["payments-portal/commercial-mapping/v1", account_id, offer_id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big", signed=True)


def bound_publication_transaction(db: Session, *, deadline: float, lock_timeout_seconds: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise MappingStorageDeadline()
    # Floor rather than round: neither DB wait may extend the preflight lease.
    statement_ms = math.floor(remaining * 1000)
    if statement_ms < 1:
        raise MappingStorageDeadline()
    lock_ms = max(1, min(statement_ms, math.floor(lock_timeout_seconds * 1000)))
    db.execute(text("SELECT set_config('statement_timeout', :value, true)"), {"value": f"{statement_ms}ms"})
    db.execute(text("SELECT set_config('lock_timeout', :value, true)"), {"value": f"{lock_ms}ms"})


def require_publication_isolation(db: Session) -> None:
    # The post-lock read must see a contender's commit, including the first row.
    db.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))


def lock_mapping_scope(db: Session, *, account_id: str, offer_id: str) -> None:
    try:
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": mapping_lock_key(account_id, offer_id)})
    except DBAPIError as error:
        state = getattr(error.orig, "sqlstate", None)
        if state == "55P03":
            raise MappingStorageBusy() from None
        if state == "57014":
            raise MappingStorageDeadline() from None
        raise
