"""Private HS256 Client JWT policy. No persistence, expiry fiction or logging."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable

from pydantic import SecretStr

from app.domains.catalog.mapping_evidence import MappingEvidenceMode
from app.domains.purchases.contracts import PurchaseRefused


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def sign_widget_jwt(
    *,
    customer_id: str,
    secret: SecretStr,
    evidence_mode: MappingEvidenceMode,
    clock: Callable[[], float] = time.time,
) -> str:
    # A recorded proof can never acquire a live credential, even when a real
    # secret happens to be present in the process configuration.
    key = secret.get_secret_value().encode()
    issued_at = int(clock())
    if (
        evidence_mode != MappingEvidenceMode.GENUINE
        or len(key) < 32
        or not customer_id.isascii()
        or not customer_id.isdecimal()
        or int(customer_id) <= 0
        or customer_id != str(int(customer_id))
        or issued_at < 0
    ):
        raise PurchaseRefused("billing_not_ready", 503)
    header = _encode(b'{"alg":"HS256","typ":"JWT"}')
    payload = _encode(
        json.dumps({"ident_type": 7, "ident": customer_id, "iat": issued_at}, separators=(",", ":")).encode()
    )
    message = f"{header}.{payload}"
    return message + "." + _encode(hmac.new(key, message.encode(), hashlib.sha256).digest())
