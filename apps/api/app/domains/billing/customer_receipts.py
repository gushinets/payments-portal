"""Decode only the bounded persisted customer CREATE receipt identity."""

from app.domains.billing.contracts import BillingRefused
from app.models import ExternalCreateOperation

CUSTOMER_RECEIPT_SCHEMA = "customer-create-receipt:v1"


def receipt_id(operation: ExternalCreateOperation) -> str | None:
    if operation.recovery_hint_schema_version is None and operation.recovery_hint_document is None:
        return None
    hint = operation.recovery_hint_document
    if operation.recovery_hint_schema_version != CUSTOMER_RECEIPT_SCHEMA or not isinstance(hint, dict):
        raise BillingRefused("billing_identity_unproven", 409)
    value = hint.get("provider_customer_candidate_id")
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdecimal()
        or len(value) > 20
        or int(value) <= 0
        or str(int(value)) != value
    ):
        raise BillingRefused("billing_identity_unproven", 409)
    return value
