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


class ExternalBillingCustomerBindingState(StrEnum):
    UNBOUND = "unbound"
    BOUND = "bound"
    IDENTITY_CONFLICT = "identity_conflict"


class PurchaseIntentState(StrEnum):
    CREATED = "created"
    PREPARING = "preparing"
    AWAITING_EXTERNAL_RESULT = "awaiting_external_result"
    LINKED = "linked"
    RESOLVED_NO_EXTERNAL_EFFECT = "resolved_no_external_effect"
    FAILED_BEFORE_EXTERNAL_EFFECT = "failed_before_external_effect"
    MANUAL_REVIEW = "manual_review"


class ExternalCreateOperationKind(StrEnum):
    CUSTOMER = "customer"
    AGREEMENT = "agreement"
    SUBSCRIPTION = "subscription"


class ExternalSubscriptionLifecycleStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ENDED = "ended"


class ExternalSubscriptionFinancialAccessStatus(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"


class ExternalSubscriptionCommercialAccessStatus(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


class BillingStateObservationKind(StrEnum):
    AUTHORITATIVE_SUBSCRIPTION_READ = "authoritative_subscription_read"
    TARGET_PRODUCT_DISCOVERY = "target_product_discovery"
    PRIMARY_SELECTION = "primary_selection"
    DETERMINISTIC_ACCESS_BOUNDARY = "deterministic_access_boundary"


__all__ = [
    "AcceptanceKind",
    "BillingStateObservationKind",
    "ExternalBillingCustomerBindingState",
    "ExternalCreateOperationKind",
    "ExternalSubscriptionCommercialAccessStatus",
    "ExternalSubscriptionFinancialAccessStatus",
    "ExternalSubscriptionLifecycleStatus",
    "LegalEntityStatus",
    "LegalEntityType",
    "MagicLinkPurpose",
    "PurchaseIntentState",
    "RegionStatus",
    "UserStatus",
]
