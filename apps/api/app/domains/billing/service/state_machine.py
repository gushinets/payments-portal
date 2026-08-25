"""Subscription lifecycle state transitions."""

from __future__ import annotations

from app.domains.billing.enums import ProviderSubscriptionState, SubscriptionStatus


class SubscriptionLifecycleError(ValueError):
    """Raised when a lifecycle command cannot be applied safely."""


PROVIDER_SUBSCRIPTION_STATUS_MAP = {
    ProviderSubscriptionState.ACTIVE: SubscriptionStatus.ACTIVE,
    ProviderSubscriptionState.PAST_DUE: SubscriptionStatus.PAST_DUE,
    ProviderSubscriptionState.CANCELED: SubscriptionStatus.CANCELED,
    ProviderSubscriptionState.REJECTED: SubscriptionStatus.CANCELED,
    ProviderSubscriptionState.EXPIRED: SubscriptionStatus.CANCELED,
    ProviderSubscriptionState.PAUSED: SubscriptionStatus.PAUSED,
    ProviderSubscriptionState.ENDED: SubscriptionStatus.CANCELED,
}

SUBSCRIPTION_STATUS_TRANSITIONS = {
    SubscriptionStatus.TRIALING: frozenset(
        {SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELED, SubscriptionStatus.EXPIRED}
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
}


def subscription_status_from_provider_state(state: ProviderSubscriptionState) -> SubscriptionStatus:
    return PROVIDER_SUBSCRIPTION_STATUS_MAP[state]


def ensure_subscription_status_transition(current: str, next_status: SubscriptionStatus) -> None:
    try:
        current_status = SubscriptionStatus(current)
    except ValueError as exc:
        raise SubscriptionLifecycleError("invalid_current_subscription_status") from exc
    if next_status not in SUBSCRIPTION_STATUS_TRANSITIONS.get(current_status, frozenset()):
        raise SubscriptionLifecycleError("invalid_subscription_status_transition")
