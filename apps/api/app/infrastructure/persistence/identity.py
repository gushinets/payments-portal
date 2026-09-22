"""Focused storage interpretation for canonical Portal identity."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError


SCOPED_EMAIL_UNIQUE_CONSTRAINT = "uq_users_tenant_region_email_normalized"


def is_scoped_email_unique_conflict(error: Exception) -> bool:
    if not isinstance(error, IntegrityError):
        return False
    constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    return constraint_name == SCOPED_EMAIL_UNIQUE_CONSTRAINT
