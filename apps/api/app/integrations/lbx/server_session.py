"""Server authentication on the client's existing lock and source budget."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx
from pydantic import SecretStr

from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.dto import LbxEnvelope, LbxSession
from app.integrations.lbx.errors import LbxAuthenticationFailed, LbxResponseInvalid
from app.integrations.lbx.transport import _Attempts

if TYPE_CHECKING:
    from app.integrations.lbx.client import LbxServerClient


@dataclass(frozen=True)
class _Session:
    token: SecretStr = field(repr=False)
    expires_at: float


async def ensure_session(
    client: LbxServerClient, attempts: _Attempts, budget: PreflightBudget, *, allow_refresh: bool
) -> _Session:
    current = client._session
    if current is not None and time.monotonic() < current.expires_at:
        return current
    # Lock waiting, auth HTTP and auth body/cleanup are in the SAME source
    # task and absolute deadline as the selected GET. No refresh worker.
    async with client._session_lock:
        budget.check()
        current = client._session
        if current is not None and time.monotonic() < current.expires_at:
            return current
        if not allow_refresh:
            raise LbxAuthenticationFailed()
        client._session = None
        started = time.monotonic()
        config = client._configuration
        credentials = httpx.BasicAuth(
            config.lbx_server_username.get_secret_value(), config.lbx_server_password.get_secret_value()
        )
        wire = await client._request_once("/auth", LbxEnvelope[LbxSession], attempts, budget, auth=credentials)
        # Start BEFORE the auth round trip; never assume another 600s after
        # receiving a delayed response or invent a fixed provider lifetime.
        try:
            expires_at = started + wire.expires_in
        except OverflowError:
            raise LbxResponseInvalid() from None
        if not math.isfinite(expires_at):
            raise LbxResponseInvalid()
        session = _Session(wire.token, expires_at)
        budget.check()
        if time.monotonic() >= session.expires_at:
            raise LbxAuthenticationFailed()
        client._session = session
        return session
