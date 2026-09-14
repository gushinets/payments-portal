"""Compatibility export; new code imports app.domains.identity.router."""

from app.domains.identity.session import (  # noqa: F401
    DEFAULT_REGION,
    DEFAULT_TENANT_ID,
)
from app.domains.identity.services.auth import as_utc  # noqa: F401
from app.http_dependencies import get_current_session  # noqa: F401
from app.domains.identity.router import *  # noqa: F403
