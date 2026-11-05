"""Append historical support fixtures without bypassing observation immutability."""

from app.models import BillingStateObservation


def observation_factory(
    previous: BillingStateObservation, *, schema: str, document: dict | list
) -> BillingStateObservation:
    return BillingStateObservation(
        observation_kind=previous.observation_kind,
        external_billing_account_id=previous.external_billing_account_id,
        user_id=previous.user_id,
        product_id=previous.product_id,
        access_scope_id=previous.access_scope_id,
        subscription_id=previous.subscription_id,
        observed_at=previous.observed_at,
        evidence_schema_version=schema,
        evidence_document=document,
        completeness_classification=previous.completeness_classification,
        result_classification=previous.result_classification,
        resulting_access_revision=None,
    )
