"""Selected material field provenance; no I/O, validation or approval decisions."""

from __future__ import annotations

from app.domains.catalog.commercial_offer import (
    CommercialEvidenceBasis,
    CommercialEvidenceMode,
    CommercialFieldSource,
    CommercialSourceReferences,
)
from app.integrations.lbx.offer_inputs import EvidenceReference, SelectedOfferInputs, SelectedPolicyEvidence


def selected_offer_provenance(
    inputs: SelectedOfferInputs,
    policy: SelectedPolicyEvidence,
    proofs: tuple[EvidenceReference, ...],
    references: CommercialSourceReferences,
    paths: tuple[str, ...],
) -> tuple[CommercialEvidenceMode, tuple[CommercialFieldSource, ...]]:
    mode = inputs.source_mode
    if any(proof.basis == CommercialEvidenceBasis.SIMULATED for proof in proofs):
        mode = CommercialEvidenceMode.SIMULATED
    configuration_sources = tuple(
        CommercialFieldSource(field, proof.reference, proof.revision, proof.basis)
        for field, proof in zip(
            (
                "money.currency/units/scale",
                "policy",
                "quantity.selected",
                "scope.credential_binding",
                "source.list_completeness",
                "period.price_applicability",
                "policy.historical_applicability",
            ),
            proofs,
            strict=True,
        )
    )
    configuration_sources += tuple(
        CommercialFieldSource(field, policy.evidence.reference, policy.evidence.revision, policy.evidence.basis)
        for field in (
            "policy.tax_treatment",
            "policy.discounts.account",
            "policy.proration.configured",
            "policy.connection_charge_basis",
            "policy.renewal_terms",
            "policy.cancellation_terms",
            "policy.credit_disabled",
            "policy.promised_payment_disabled",
            "policy.manual_activation_disabled",
            "policy.independent_service_selection",
        )
    )
    if inputs.calendar is not None:
        proof = inputs.calendar.evidence
        if proof.basis == CommercialEvidenceBasis.SIMULATED:
            mode = CommercialEvidenceMode.SIMULATED
        configuration_sources += (
            CommercialFieldSource("scope.billing_calendar", proof.reference, proof.revision, proof.basis),
        )
    wire_basis = (
        CommercialEvidenceBasis.SIMULATED
        if inputs.source_mode == CommercialEvidenceMode.SIMULATED
        else CommercialEvidenceBasis.ACCOUNT_EVIDENCE
    )
    wire_fields = (
        ("policy.prepaid", paths[0] + "#/payment_type"),
        ("policy.insufficient_funds_block", paths[0] + "#/balance_blocks"),
        ("policy.block_to_close_days", paths[0] + "#/block_to_close_days"),
        ("policy.full_funding_required", paths[0] + "#/dynamic_rent_unblock_type"),
        ("policy.fixed_price", paths[0] + "#/dynamic_rent"),
        ("policy.demo_days", paths[0] + "#/demo_period_length"),
        ("policy.proration.source", paths[0] + "#/proportional_rent"),
        ("period.anchor", paths[0] + "#/float_period"),
        ("period.membership/unit/length", paths[1] + "#period=" + references.period),
        ("component.membership/quantity.bounds", paths[2] + "#component=" + references.component),
        ("dependencies.default_components", paths[2] + "#/enabled_by_default"),
        ("policy.discounts.service", paths[2] + "#/discounts"),
        ("policy.customer_service_management", paths[2] + "#/user_available"),
        ("policy.customer_quantity_management", paths[2] + "#/user_can_set_mul"),
        ("money.recurring_unit_amount", paths[3] + "#price=" + references.effective_price + "/price"),
        ("money.connection_unit_amount", paths[3] + "#price=" + references.effective_price + "/connection_price"),
        ("period.price_effective_from/until", paths[3] + "#price=" + references.effective_price),
        ("money.recurring_amount", "exact_product(money.recurring_unit_amount,quantity.selected)"),
        ("money.connection_amount", "policy.connection_charge_basis+money.connection_unit_amount+quantity.selected"),
    )
    wire_sources = tuple(
        CommercialFieldSource(field, reference, "LBX Swagger 1.0.11 + selected-offer v1", wire_basis)
        for field, reference in wire_fields
    )
    return mode, configuration_sources + wire_sources
