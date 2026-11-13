"""Canonical persisted model vocabularies."""

from enum import StrEnum


class RegionStatus(StrEnum):
    ACTIVE = "active"


class UserStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class MagicLinkPurpose(StrEnum):
    PASSWORD_RESET = "password_reset"
    EMAIL_VERIFICATION = "email_verification"


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


class ExternalCreateOperationState(StrEnum):
    PENDING = "pending"
    PROVEN_NOT_SENT = "proven_not_sent"
    POSSIBLE_SEND = "possible_send"
    UNKNOWN = "unknown"
    BOUND = "bound"
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
    UNVERIFIED = "unverified"
    ALLOWED = "allowed"
    BLOCKED = "blocked"


class ExternalSubscriptionCommercialAccessStatus(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


class BillingStateObservationKind(StrEnum):
    AUTHORITATIVE_SUBSCRIPTION_READ = "authoritative_subscription_read"
    TARGET_PRODUCT_DISCOVERY = "target_product_discovery"
    ALLOWANCE_ACTIVATION = "allowance_activation"
    PRIMARY_SELECTION = "primary_selection"
    DETERMINISTIC_ACCESS_BOUNDARY = "deterministic_access_boundary"


class WebhookDeliveryState(StrEnum):
    PENDING = "pending"
    PROCESSED = "processed"
    IGNORED = "ignored"


class BillingWorkKind(StrEnum):
    SUBSCRIPTION_RECONCILIATION = "subscription_reconciliation"
    SUBSCRIPTION_TRUST_EXPIRY = "subscription_trust_expiry"
    BILLING_ENROLLMENT_SWEEP = "billing_enrollment_sweep"
    CUSTOMER_INVENTORY = "customer_inventory"
    EXTERNAL_CREATE_DEADLINE = "external_create_deadline"
    EXTERNAL_CREATE_RECOVERY = "external_create_recovery"
    ACCESS_INVALIDATION = "access_invalidation"
    ALLOWANCE_EXHAUSTION = "allowance_exhaustion"


class BillingWorkState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    INVALID = "invalid"
    DONE = "done"
    PAUSED = "paused"


class BillingWorkScope(StrEnum):
    ALLOWANCE = "allowance"
    BILLING_ACCOUNT = "billing_account"
    SUBSCRIPTION = "subscription"
    CUSTOMER = "customer"
    CREATE_OPERATION = "create_operation"
    USER = "user"


__all__ = [
    "AcceptanceKind",
    "BillingStateObservationKind",
    "BillingWorkKind",
    "BillingWorkScope",
    "BillingWorkState",
    "ExternalBillingCustomerBindingState",
    "ExternalCreateOperationKind",
    "ExternalCreateOperationState",
    "ExternalSubscriptionCommercialAccessStatus",
    "ExternalSubscriptionFinancialAccessStatus",
    "ExternalSubscriptionLifecycleStatus",
    "LegalEntityStatus",
    "LegalEntityType",
    "MagicLinkPurpose",
    "PurchaseIntentState",
    "RegionStatus",
    "UserStatus",
    "WebhookDeliveryState",
]
