"""Decode saved purchase evidence without consulting mutable source configuration."""

import json

from app.domains.purchases.contracts import AcceptedPurchase, PurchaseRefused
from app.models import PurchaseIntent


def accepted(row: PurchaseIntent) -> AcceptedPurchase:
    try:
        result = AcceptedPurchase.model_validate_json(json.dumps(row.accepted_snapshot))
    except (ValueError, TypeError):
        raise PurchaseRefused("purchase_history_unproven", 409) from None
    if (
        row.accepted_snapshot_schema_version != result.schema_version
        or row.product_id != result.meaning.product_id
        or row.mapping_revision_id != result.meaning.revision_id
        or row.accepted_commercial_fingerprint != result.offer.fingerprint
        or result.meaning.expected_fingerprint != result.offer.fingerprint
        or row.billing_offer_id != result.selection.billing_offer_id
        or result.selection.product_id != row.product_id
        or (result.technical_terms is not None and result.technical_terms.account_id != row.external_billing_account_id)
    ):
        raise PurchaseRefused("purchase_history_unproven", 409)
    return result
