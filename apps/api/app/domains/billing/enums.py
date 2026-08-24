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


class EntitlementStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    SUPERSEDED = "superseded"


class EntitlementSource(StrEnum):
    TRIAL = "trial"
    ORDER = "order"


__all__ = [
    "EntitlementSource",
    "EntitlementStatus",
    "SubscriptionRenewalMode",
    "SubscriptionStatus",
]
