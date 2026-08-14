"""Compatibility export; new code imports app.domains.identity.router."""

from app.domains.identity.session import (  # noqa: F401
    DEFAULT_REGION,
    DEFAULT_TENANT_ID,
    as_utc,
    get_current_session,
)
from app.domains.identity.router import *  # noqa: F403
