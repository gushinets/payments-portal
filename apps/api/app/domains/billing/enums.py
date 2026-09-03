"""Temporary billing compatibility exports for model vocabularies."""

from enum import StrEnum

from app.models.enums import (
    BillingPeriod,
    BundleProductStatus,
    BundleStatus,
    EntitlementSource,
    EntitlementStatus,
    OrderItemType,
    OrderStatus,
    PaymentStatus,
    PaymentWebhookEventStatus,
    PlanLimitOveragePolicy,
    PlanLimitResetPolicy,
    PlanPriceComponentType,
    PlanStatus,
    ProductStatus,
    RefundStatus,
    SubscriptionEventType,
    SubscriptionRenewalMode,
    SubscriptionScopeType,
    SubscriptionStatus,
)


class ProviderSubscriptionState(StrEnum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    PAUSED = "paused"
    ENDED = "ended"


class SensitiveMetadataKey(StrEnum):
    TOKEN = "token"
    SECRET = "secret"
    PASSWORD = "password"
    AUTHORIZATION = "authorization"
    CARD = "card"
    RAW_PAYLOAD = "raw_payload"
    RAW_BODY = "raw_body"


class ProductAccessStatus(StrEnum):
    INACTIVE = "inactive"
    PENDING = "pending"
    ACTIVE = "active"


# Kept for callers that still use the pre-ANY-326 name.
WebhookEventStatus = PaymentWebhookEventStatus


__all__ = [
    "BillingPeriod",
    "BundleProductStatus",
    "BundleStatus",
    "EntitlementSource",
    "EntitlementStatus",
    "OrderItemType",
    "OrderStatus",
    "PaymentStatus",
    "PaymentWebhookEventStatus",
    "PlanLimitOveragePolicy",
    "PlanLimitResetPolicy",
    "PlanPriceComponentType",
    "PlanStatus",
    "ProductAccessStatus",
    "ProductStatus",
    "ProviderSubscriptionState",
    "RefundStatus",
    "SensitiveMetadataKey",
    "SubscriptionEventType",
    "SubscriptionRenewalMode",
    "SubscriptionScopeType",
    "SubscriptionStatus",
    "WebhookEventStatus",
]
