"""Explicit SIMULATED account delta, separate from real-sale enablement.

Loading is caller-owned and lazy. Missing real G2 facts never prevent startup.
There is intentionally no production CREATE enable switch in this slice.
"""

from __future__ import annotations

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import SecretStr

from app.domains.catalog.commercial_offer import (
    CommercialEvidenceBasis,
    CommercialEvidenceMode,
    SelectedCommercialOffer,
)
from app.integrations.lbx.errors import LbxPreparationBlocked
from app.integrations.lbx.offer_inputs import (
    REQUIRED_POLICY_FIELDS,
    EvidenceReference,
    SelectedOfferInputs,
    SelectedOfferRequest,
)
from app.integrations.lbx.preparation_dto import Identity, PostAgreement, PostSubscription, PostUser, PrivateDto


class PreparationProfile(PrivateDto):
    schema_version: Literal["SIMULATED-lbx-preparation-v1"]
    source_mode: Literal["SIMULATED"]
    server_origin: str
    server_username: SecretStr
    selection: SelectedOfferRequest
    inputs: SelectedOfferInputs
    organization_id: Identity
    account_evidence: EvidenceReference
    seller_evidence: EvidenceReference
    customer_evidence: EvidenceReference
    create_evidence: EvidenceReference
    dedicated_agreement_evidence: EvidenceReference
    subscription_list_evidence: EvidenceReference
    subscription_list_complete: Literal[True]
    currency_symbol: str
    customer_type: Literal[1, 2]
    lawful_customer_fields: tuple[str, ...]
    service_composition: Literal["explicit_single", "account_default_single"]
    activate_by_balance: bool
    activate_manually: bool
    demo_period_length: int
    is_offer: bool
    # Caller pins the account-calendar date in consent, not host wall time.
    start_time: Literal["00:00:00"]
    allowed_states: tuple[int, ...]
    allowed_blocking: tuple[int, ...]

    def require_account(self, *, account_id: str, origin: str, username: SecretStr) -> None:
        selection, inputs = self.selection, self.inputs
        currency, calendar, policy = inputs.currency, inputs.calendar, inputs.policy
        if (
            selection.external_billing_account_id != account_id
            or self.server_origin != origin
            or self.server_username != username
            or inputs.source_mode != CommercialEvidenceMode.SIMULATED
            or currency is None
            or calendar is None
            or policy is None
            or any(value.external_billing_account_id != account_id for value in (currency, calendar, policy))
            or not self.currency_symbol
            or currency.iso_currency is None
            or currency.source_units not in {"major", "minor"}
            or currency.decimal_places is None
            or not 0 <= currency.decimal_places <= 36
            or any(getattr(policy, name) is None for name in REQUIRED_POLICY_FIELDS)
            or policy.account_binding is None
            or policy.list_completeness is None
            or policy.historical_policy is None
            or policy.price_applicability is None
        ):
            raise LbxPreparationBlocked()
        references = (
            self.account_evidence,
            self.seller_evidence,
            self.customer_evidence,
            self.create_evidence,
            self.dedicated_agreement_evidence,
            self.subscription_list_evidence,
            currency.evidence,
            calendar.evidence,
            selection.quantity_evidence,
            policy.evidence,
            policy.account_binding,
            policy.list_completeness,
            policy.historical_policy,
            policy.price_applicability,
        )
        if any(reference.basis != CommercialEvidenceBasis.SIMULATED for reference in references):
            raise LbxPreparationBlocked()
        if (
            any(
                getattr(policy, name) != getattr(selection, name)
                for name in ("tenant_id", "region", "tariff_id", "tariff_service_id", "period_id")
            )
            or not policy.valid_from <= selection.effective_on
            or (policy.valid_until is not None and selection.effective_on >= policy.valid_until)
            or policy.credit_disabled is not True
            or policy.promised_payment_disabled is not True
            or policy.manual_activation_disabled is not True
            or self.activate_manually
            or self.demo_period_length != 0
            or not self.activate_by_balance
            or not self.allowed_states
            or not set(self.allowed_states) <= {-2, 2}
            or not self.allowed_blocking
            or not set(self.allowed_blocking) <= {0, 1}
            or policy.complete_selected_lists is not True
            or policy.independent_service_selection is not True
        ):
            raise LbxPreparationBlocked()
        try:
            ZoneInfo(calendar.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise LbxPreparationBlocked() from None

    def require_customer(self, command: PostUser) -> None:
        supplied = set(command.model_dump(exclude_none=True)) - {"outer_id"}
        allowed = set(self.lawful_customer_fields)
        if (
            command.type != self.customer_type
            or supplied != allowed
            or not allowed <= set(PostUser.model_fields) - {"outer_id"}
        ):
            raise LbxPreparationBlocked()

    def require_agreement(self, command: PostAgreement) -> None:
        if (
            command.organization_id != self.organization_id
            or command.is_offer != self.is_offer
            or command.create_date != self.selection.effective_on
        ):
            raise LbxPreparationBlocked()

    def require_offer(self, offer: SelectedCommercialOffer) -> None:
        selection, currency, policy = self.selection, self.inputs.currency, self.inputs.policy
        if currency is None or policy is None:
            raise LbxPreparationBlocked()
        terms = offer.terms
        if (
            offer.evidence_mode != CommercialEvidenceMode.SIMULATED
            or (offer.scope.tenant_id, offer.scope.region, offer.scope.external_billing_account_id)
            != (selection.tenant_id, selection.region, selection.external_billing_account_id)
            or (offer.references.offer, offer.references.component, offer.references.period)
            != (str(selection.tariff_id), str(selection.tariff_service_id), str(selection.period_id))
            or (terms.money.currency, terms.money.decimal_places) != (currency.iso_currency, currency.decimal_places)
            or terms.quantity.selected != selection.commercial_quantity
            or terms.quantity.selected != terms.quantity.selected.to_integral_value()
            or not terms.quantity.minimum <= terms.quantity.selected <= terms.quantity.maximum
            or not terms.period.price_effective_from <= selection.effective_on
            or (
                terms.period.price_effective_until is not None
                and selection.effective_on >= terms.period.price_effective_until
            )
            or terms.policy.renewal_terms != policy.renewal_terms
            or terms.policy.cancellation_terms != policy.cancellation_terms
            or terms.policy.historical_applicability != policy.historical_applicability
            or terms.policy.connection_charge_basis != policy.connection_charge_basis
            or terms.policy.tax_treatment != policy.tax_treatment
            or terms.policy.discounts != policy.account_discounts
            or terms.policy.proration != policy.proration
            or terms.policy.demo_days != 0
            or not terms.policy.prepaid
            or not terms.policy.full_funding_required
            or not terms.policy.insufficient_funds_block
            or terms.policy.customer_service_management
            or terms.policy.customer_quantity_management
        ):
            raise LbxPreparationBlocked()

    def require_subscription(self, command: PostSubscription, offer: SelectedCommercialOffer) -> None:
        self.require_offer(offer)
        selected = self.selection
        if (
            command.tariff_id != selected.tariff_id
            or command.period_id != selected.period_id
            or command.subscription_start_date != f"{selected.effective_on.isoformat()} {self.start_time}"
            or command.activate_by_balance != self.activate_by_balance
            or command.activate_manually != self.activate_manually
            or command.demo_period_length != self.demo_period_length
        ):
            raise LbxPreparationBlocked()
        if self.service_composition == "account_default_single":
            if command.services is not None:
                raise LbxPreparationBlocked()
        elif (
            command.services is None
            or len(command.services) != 1
            or command.services[0].tariff_service_id != selected.tariff_service_id
            or command.services[0].multiplicator != selected.commercial_quantity
        ):
            raise LbxPreparationBlocked()
