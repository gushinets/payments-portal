"""Provider-neutral subscription vocabularies."""

from enum import StrEnum


class SubscriptionStatus(StrEnum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REFUNDED = "refunded"
    PAUSED = "paused"


class SubscriptionRenewalMode(StrEnum):
    MANUAL = "manual"
    AUTOMATIC = "automatic"


__all__ = ["SubscriptionRenewalMode", "SubscriptionStatus"]
