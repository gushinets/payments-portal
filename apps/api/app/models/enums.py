"""Canonical persisted model vocabularies."""

from enum import StrEnum


class ProductStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class BundleStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class BundleProductStatus(StrEnum):
    ACTIVE = "active"


class PlanStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


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


class SubscriptionRenewalMode(StrEnum):
    MANUAL = "manual"
    AUTOMATIC = "automatic"


class PlanPriceComponentType(StrEnum):
    PRODUCT_PLAN = "product_plan"


class PlanLimitResetPolicy(StrEnum):
    BILLING_PERIOD = "billing_period"


class PlanLimitOveragePolicy(StrEnum):
    DENY = "deny"


class CheckoutSessionStatus(StrEnum):
    CREATED = "created"
    ORDER_CREATED = "order_created"


class OrderStatus(StrEnum):
    CREATED = "created"
    REQUIRES_CONSENTS = "requires_consents"
    PENDING_PAYMENT = "pending_payment"
    PAID = "paid"
    PAYMENT_FAILED = "payment_failed"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"
    REGION_MISMATCH = "region_mismatch"


class OrderItemType(StrEnum):
    PRODUCT_PLAN = "product_plan"
    BUNDLE_PLAN = "bundle_plan"
    ALL_ACCESS_PLAN = "all_access_plan"


class PaymentStatus(StrEnum):
    CREATED = "created"
    REQUIRES_ACTION = "requires_action"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"
    DISPUTED = "disputed"


class RefundStatus(StrEnum):
    REQUESTED = "requested"
    SUCCEEDED = "succeeded"


class PaymentWebhookEventStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    PROCESSED = "processed"
    IGNORED = "ignored"
    DUPLICATE = "duplicate"
    FAILED = "failed"


class SubscriptionStatus(StrEnum):
    def __new__(cls, value: str, is_live: bool):
        member = str.__new__(cls, value)
        member._value_ = value
        member.is_live = is_live
        return member

    TRIALING = "trialing", True
    ACTIVE = "active", True
    PAST_DUE = "past_due", True
    CANCELED = "canceled", False
    EXPIRED = "expired", False
    REFUNDED = "refunded", False
    PAUSED = "paused", True

    @classmethod
    def live_values(cls) -> tuple[str, ...]:
        return tuple(status.value for status in cls if status.is_live)


class EntitlementStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    SUPERSEDED = "superseded"


class EntitlementSource(StrEnum):
    TRIAL = "trial"
    ORDER = "order"


class SubscriptionEventType(StrEnum):
    TRIAL_STARTED = "trial_started"
    PAID_PERIOD_ACTIVATED = "paid_period_activated"
    SUBSCRIPTION_REPLACED = "subscription_replaced"
    AUTOMATIC_RENEWAL_ENABLED = "automatic_renewal_enabled"
    RENEWAL_SUCCEEDED = "renewal_succeeded"
    RENEWAL_FAILED = "renewal_failed"
    PROVIDER_SUBSCRIPTION_STATE_APPLIED = "provider_subscription_state_applied"
    CANCELLATION_REQUESTED = "cancellation_requested"
    REFUND_APPLIED = "refund_applied"
    PARTIAL_REFUND_APPLIED = "partial_refund_applied"
    SUBSCRIPTION_EXPIRED = "subscription_expired"


class RegionStatus(StrEnum):
    ACTIVE = "active"


class UserStatus(StrEnum):
    ACTIVE = "active"


class MagicLinkPurpose(StrEnum):
    PASSWORD_RESET = "password_reset"


class LegalEntityStatus(StrEnum):
    ACTIVE = "active"


class LegalEntityType(StrEnum):
    INDIVIDUAL_ENTREPRENEUR = "individual_entrepreneur"
    MERCHANT_OF_RECORD = "merchant_of_record"
    COMPANY = "company"


class AcceptanceKind(StrEnum):
    PRIVACY_CONSENT = "privacy_consent"
    TERMS_ACCEPTANCE = "terms_acceptance"
    RECURRING_CONSENT = "recurring_consent"
    COOKIES = "cookies"


__all__ = [
    "AcceptanceKind",
    "BillingPeriod",
    "BundleProductStatus",
    "BundleStatus",
    "CheckoutSessionStatus",
    "EntitlementSource",
    "EntitlementStatus",
    "LegalEntityStatus",
    "LegalEntityType",
    "MagicLinkPurpose",
    "OrderItemType",
    "OrderStatus",
    "PaymentStatus",
    "PaymentWebhookEventStatus",
    "PlanLimitOveragePolicy",
    "PlanLimitResetPolicy",
    "PlanPriceComponentType",
    "PlanStatus",
    "ProductStatus",
    "RefundStatus",
    "RegionStatus",
    "SubscriptionEventType",
    "SubscriptionRenewalMode",
    "SubscriptionScopeType",
    "SubscriptionStatus",
    "UserStatus",
]
