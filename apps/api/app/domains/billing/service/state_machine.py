"""Subscription lifecycle state transitions."""

from __future__ import annotations

from app.domains.billing.enums import AuthoritativeSubscriptionState
from app.models import SubscriptionStatus


class SubscriptionLifecycleError(ValueError):
    """Raised when a lifecycle command cannot be applied safely."""


AUTHORITATIVE_SUBSCRIPTION_STATUS_MAP = {
    AuthoritativeSubscriptionState.ACTIVE: SubscriptionStatus.ACTIVE,
    AuthoritativeSubscriptionState.PAST_DUE: SubscriptionStatus.PAST_DUE,
    AuthoritativeSubscriptionState.CANCELED: SubscriptionStatus.CANCELED,
    AuthoritativeSubscriptionState.REJECTED: SubscriptionStatus.CANCELED,
    AuthoritativeSubscriptionState.EXPIRED: SubscriptionStatus.CANCELED,
    AuthoritativeSubscriptionState.PAUSED: SubscriptionStatus.PAUSED,
    AuthoritativeSubscriptionState.ENDED: SubscriptionStatus.CANCELED,
}

SUBSCRIPTION_STATUS_TRANSITIONS = {
    SubscriptionStatus.TRIALING: frozenset(
        {
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.PAST_DUE,
            SubscriptionStatus.CANCELED,
            SubscriptionStatus.EXPIRED,
            SubscriptionStatus.PAUSED,
        }
    ),
    SubscriptionStatus.ACTIVE: frozenset(
        {
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.PAST_DUE,
            SubscriptionStatus.CANCELED,
            SubscriptionStatus.EXPIRED,
            SubscriptionStatus.REFUNDED,
            SubscriptionStatus.PAUSED,
        }
    ),
    SubscriptionStatus.PAST_DUE: frozenset(
        {
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.PAST_DUE,
            SubscriptionStatus.CANCELED,
            SubscriptionStatus.EXPIRED,
            SubscriptionStatus.REFUNDED,
            SubscriptionStatus.PAUSED,
        }
    ),
    SubscriptionStatus.PAUSED: frozenset(
        {
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.PAST_DUE,
            SubscriptionStatus.CANCELED,
            SubscriptionStatus.EXPIRED,
            SubscriptionStatus.REFUNDED,
            SubscriptionStatus.PAUSED,
        }
    ),
    SubscriptionStatus.CANCELED: frozenset({SubscriptionStatus.EXPIRED, SubscriptionStatus.REFUNDED}),
    SubscriptionStatus.EXPIRED: frozenset({SubscriptionStatus.REFUNDED}),
}


def subscription_status_from_authoritative_state(state: AuthoritativeSubscriptionState) -> SubscriptionStatus:
    try:
        return AUTHORITATIVE_SUBSCRIPTION_STATUS_MAP[state]
    except KeyError as exc:
        raise SubscriptionLifecycleError("unsupported_authoritative_subscription_state") from exc


def ensure_subscription_status_transition(current: SubscriptionStatus, next_status: SubscriptionStatus) -> None:
    try:
        current_status = SubscriptionStatus(current)
    except ValueError as exc:
        raise SubscriptionLifecycleError("invalid_current_subscription_status") from exc
    if next_status not in SUBSCRIPTION_STATUS_TRANSITIONS.get(current_status, frozenset()):
        raise SubscriptionLifecycleError("invalid_subscription_status_transition")
