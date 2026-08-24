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


class SubscriptionScopeType(StrEnum):
    PRODUCT = "product"
    BUNDLE = "bundle"
    ALL_ACCESS = "all_access"


class BillingPeriod(StrEnum):
    DAY = "day"
    DAYS = "days"
    WEEK = "week"
    WEEKS = "weeks"
    MONTH = "month"
    MONTHS = "months"
    YEAR = "year"
    YEARS = "years"
    ANNUAL = "annual"
    YEARLY = "yearly"


class ProviderSubscriptionState(StrEnum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    PAUSED = "paused"
    ENDED = "ended"


class SubscriptionEventType(StrEnum):
    TRIAL_STARTED = "trial_started"
    PAID_PERIOD_ACTIVATED = "paid_period_activated"
    AUTOMATIC_RENEWAL_ENABLED = "automatic_renewal_enabled"
    RENEWAL_SUCCEEDED = "renewal_succeeded"
    RENEWAL_FAILED = "renewal_failed"
    PROVIDER_SUBSCRIPTION_STATE_APPLIED = "provider_subscription_state_applied"
    CANCELLATION_REQUESTED = "cancellation_requested"
    REFUND_APPLIED = "refund_applied"
    PARTIAL_REFUND_APPLIED = "partial_refund_applied"
    SUBSCRIPTION_EXPIRED = "subscription_expired"


class OrderStatus(StrEnum):
    PENDING_PAYMENT = "pending_payment"
    PAYMENT_FAILED = "payment_failed"
    PAID = "paid"
    CANCELED = "canceled"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class PaymentStatus(StrEnum):
    CANCELED = "canceled"
    SUCCEEDED = "succeeded"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"


class WebhookEventStatus(StrEnum):
    PROCESSED = "processed"


class SensitiveMetadataKey(StrEnum):
    TOKEN = "token"
    SECRET = "secret"
    PASSWORD = "password"
    AUTHORIZATION = "authorization"
    CARD = "card"
    RAW_PAYLOAD = "raw_payload"
    RAW_BODY = "raw_body"


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


class ProductAccessStatus(StrEnum):
    INACTIVE = "inactive"
    PENDING = "pending"
    ACTIVE = "active"


__all__ = [
    "BillingPeriod",
    "EntitlementSource",
    "EntitlementStatus",
    "OrderStatus",
    "PaymentStatus",
    "ProductAccessStatus",
    "ProviderSubscriptionState",
    "SensitiveMetadataKey",
    "SubscriptionEventType",
    "SubscriptionRenewalMode",
    "SubscriptionScopeType",
    "SubscriptionStatus",
    "WebhookEventStatus",
]
