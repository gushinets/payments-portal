"""Billing-owned provider and metadata vocabularies."""

from enum import StrEnum


class AuthoritativeSubscriptionState(StrEnum):
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


__all__ = [
    "AuthoritativeSubscriptionState",
    "ProductAccessStatus",
    "SensitiveMetadataKey",
]
