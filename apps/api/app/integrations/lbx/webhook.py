"""LBX webhook authentication and minimal allowlisted decoding, without HTTP I/O."""

import hashlib
import hmac
import json
from enum import StrEnum

from app.core.errors import AppError
from app.domains.billing.webhook_contracts import SubscriptionHint

# Application receive limit, not an asserted provider payload limit.
MAX_BODY_BYTES = 65536


class SubscriptionEvent(StrEnum):
    CREATE = "create_subscription"
    CHANGE = "change_subscription"
    BLOCK = "block_subscription"
    PERIOD = "new_charge_period"
    CLOSE = "close_subscription"
    DELETE = "delete_subscription"


class WebhookRejected(AppError):
    """Static diagnostic code only; never retains headers, payload or parser text."""


def authenticated(values: list[str], expected: str) -> bool:
    # Duplicate header values are ambiguous even when one value matches.
    return len(values) == 1 and bool(expected) and hmac.compare_digest(values[0].encode(), expected.encode())


def _identifier(value: object) -> str:
    if type(value) is not int or not 0 < value < 10**20:
        raise WebhookRejected("lbx_webhook_invalid")
    return str(value)


def decode_hint(body: bytes) -> SubscriptionHint:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        raise WebhookRejected("lbx_webhook_invalid") from None
    if not isinstance(payload, dict):
        raise WebhookRejected("lbx_webhook_invalid")
    try:
        event = SubscriptionEvent(payload.get("event"))
    except (ValueError, TypeError):
        raise WebhookRejected("lbx_webhook_event_unsupported") from None
    parameters = payload.get("parameters")
    if not isinstance(parameters, dict):
        raise WebhookRejected("lbx_webhook_invalid")
    return SubscriptionHint(
        event.value,
        _identifier(parameters.get("subscription_id")),
        _identifier(parameters.get("agreement_id")),
        _identifier(parameters["user_id"]) if "user_id" in parameters else None,
        hashlib.sha256(body).hexdigest(),
    )
