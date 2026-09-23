"""Canonical persisted model vocabularies."""

from enum import StrEnum


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
    "LegalEntityStatus",
    "LegalEntityType",
    "MagicLinkPurpose",
    "RegionStatus",
    "UserStatus",
]
