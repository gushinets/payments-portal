"""Explicit versioned evidence that the selected GETs cannot themselves attest.

Composition supplies these inputs. No runtime defaults, settings loader,
approval decision or implicit fixture fallback lives here.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, DecimalException
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.domains.catalog.commercial_offer import CommercialEvidenceBasis, CommercialEvidenceMode


class OfferInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, hide_input_in_errors=True)


Nonempty = Annotated[str, Field(min_length=1, pattern=r"\S")]
SourceId = Annotated[int, Field(gt=0)]


def _configured_decimal(value: Any) -> Decimal:
    if type(value) is int:
        return Decimal(value)
    if isinstance(value, str):
        try:
            value = Decimal(value)
        except DecimalException:
            raise ValueError("exact finite decimal input required") from None
    if isinstance(value, Decimal) and value.is_finite():
        return value
    raise ValueError("exact finite decimal input required")


ConfiguredDecimal = Annotated[Decimal, BeforeValidator(_configured_decimal)]


class EvidenceReference(OfferInput):
    reference: Nonempty
    revision: Nonempty
    basis: CommercialEvidenceBasis


class SelectedOfferRequest(OfferInput):
    tenant_id: Nonempty
    region: Nonempty
    external_billing_account_id: Nonempty
    tariff_id: SourceId
    tariff_service_id: SourceId
    period_id: SourceId
    # Explicit billing-calendar selection, never datetime.now().date().
    effective_on: date
    commercial_quantity: ConfiguredDecimal
    quantity_evidence: EvidenceReference


class AccountCurrencyEvidence(OfferInput):
    external_billing_account_id: Nonempty
    currency_id: SourceId
    iso_currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None
    source_units: Literal["major", "minor"] | None = None
    decimal_places: int | None = None
    evidence: EvidenceReference


class AccountCalendarEvidence(OfferInput):
    """Explicit account configuration, never inferred from locale or host time."""

    external_billing_account_id: Nonempty
    timezone: Nonempty
    evidence: EvidenceReference


# Mandatory policy facts for selected-offer normalization; absent values stay
# representable at the input boundary so they receive precise refusal reasons.
REQUIRED_POLICY_FIELDS = (
    "complete_selected_lists",
    "independent_service_selection",
    "effective_price_rule",
    "tax_treatment",
    "account_discounts",
    "proration",
    "credit_disabled",
    "promised_payment_disabled",
    "manual_activation_disabled",
    "connection_charge_basis",
    "renewal_terms",
    "cancellation_terms",
    "historical_applicability",
)


class SelectedPolicyEvidence(OfferInput):
    """All values are explicit; absent facts remain incomplete, not disabled.

    The reference must cover this exact selection, currency, credential binding,
    completeness/applicability rules and the named policy fields. It is not
    an operator's assertion of production approval. Step 5 owns approval.
    """

    tenant_id: Nonempty
    region: Nonempty
    external_billing_account_id: Nonempty
    tariff_id: SourceId
    tariff_service_id: SourceId
    period_id: SourceId
    valid_from: date
    valid_until: date | None
    evidence: EvidenceReference
    account_binding: EvidenceReference | None = None
    list_completeness: EvidenceReference | None = None
    price_applicability: EvidenceReference | None = None
    historical_policy: EvidenceReference | None = None
    complete_selected_lists: bool | None = None
    independent_service_selection: bool | None = None
    effective_price_rule: str | None = None
    tax_treatment: str | None = None
    account_discounts: str | None = None
    proration: str | None = None
    credit_disabled: bool | None = None
    promised_payment_disabled: bool | None = None
    manual_activation_disabled: bool | None = None
    connection_charge_basis: str | None = None
    renewal_terms: Nonempty | None = None
    cancellation_terms: Nonempty | None = None
    historical_applicability: str | None = None


class SelectedOfferInputs(OfferInput):
    schema_version: Literal[1]
    # This labels the HTTP source, independent of configuration proof labels.
    source_mode: CommercialEvidenceMode
    calendar: AccountCalendarEvidence | None = None
    currency: AccountCurrencyEvidence | None = None
    policy: SelectedPolicyEvidence | None = None
