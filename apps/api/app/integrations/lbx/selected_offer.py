"""Complete selected reads -> exact neutral evidence or a safe local refusal.

Only this Integration sees LBX fields. The async function owns outer I/O; the
synchronous normalizer owns no database, client, cache or publication state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date
from decimal import Decimal

from app.domains.catalog.commercial_offer import (
    CommercialEvidenceBasis,
    CommercialMoney,
    CommercialObservation,
    CommercialPeriod,
    CommercialPolicy,
    CommercialQuantity,
    CommercialScope,
    CommercialSourceReferences,
    MaterialCommercialTerms,
    OfferRefusalKind,
    SelectedCommercialOffer,
    SelectedOfferRefused,
    canonical_document,
    commercial_digest,
)
from app.domains.catalog.product_link import ProductLinkRequest
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.client import LbxRead, LbxServerClient
from app.integrations.lbx.discounts import selected_discounts
from app.integrations.lbx.dto import LbxInlinePrice, LbxServicePrice, LbxTariff, LbxTariffPeriod, LbxTariffService
from app.integrations.lbx.errors import LbxError
from app.integrations.lbx.offer_inputs import (
    REQUIRED_POLICY_FIELDS,
    EvidenceReference,
    SelectedOfferInputs,
    SelectedOfferRequest,
    SelectedPolicyEvidence,
)
from app.integrations.lbx.offer_provenance import selected_offer_provenance
from app.integrations.lbx.offer_values import (
    MAX_MONEY_SCALE,
    _exact,
    _incomplete,
    _minor_units,
    _multiply,
    _quantity_bounds,
    _required,
)


PERIOD_UNITS = {1: "day", 2: "week", 3: "month", 4: "year"}
PERIOD_ANCHORS = {0: "calendar_month", 1: "instance_start", 2: "first_instance_start"}
_TARIFF_FLAGS = (
    "archive",
    "balance_blocks",
    "block_to_close_days",
    "dynamic_rent",
    "dynamic_rent_unblock_type",
    "payment_type",
    "float_period",
    "assign_unavailable",
    "client_unavailable",
    "proportional_rent",
    "demo_period_length",
    "currency_id",
)
_SERVICE_FLAGS = (
    "bulk_service",
    "periodic_service",
    "min_multiplicator",
    "max_multiplicator",
    "user_can_set_mul",
    "user_available",
    "archive",
    "catalog_id",
    "catalog_service_id",
    "payment_object",
    "hidden_for_user",
)


@dataclass(frozen=True)
class SelectedReadSet:
    """Integration-only; never pass these DTOs into Application or Domain."""

    tariff: LbxRead[LbxTariff]
    periods: LbxRead[list[LbxTariffPeriod]]
    services: LbxRead[list[LbxTariffService]]
    prices: LbxRead[list[LbxServicePrice]]


async def _read_selected(
    client: LbxServerClient, selection: SelectedOfferRequest | ProductLinkRequest, budget: PreflightBudget
) -> SelectedReadSet:
    # Each read uses the same nonrenewable caller budget; no nested run().
    tariff = await client.get_tariff(tariff_id=selection.tariff_id, budget=budget)
    periods = await client.list_tariff_periods(tariff_id=selection.tariff_id, budget=budget)
    services = await client.list_tariff_services(tariff_id=selection.tariff_id, budget=budget)
    prices = await client.list_service_prices(
        tariff_id=selection.tariff_id, tariff_service_id=selection.tariff_service_id, budget=budget
    )
    return SelectedReadSet(tariff, periods, services, prices)


async def read_selected_offer(
    client: LbxServerClient,
    *,
    selection: SelectedOfferRequest,
    inputs: SelectedOfferInputs,
    budget: PreflightBudget,
) -> SelectedCommercialOffer:
    """Two finite selected read sets detect observed drift, not atomicity.

    Caller owns admission and client lifecycle. No connections/SQL transactions
    belong here. Shared deadline/cancellation errors retain Step 2 semantics.
    """
    budget.check()
    try:
        first = normalize_selected_offer(await _read_selected(client, selection, budget), selection, inputs, budget)
        second = normalize_selected_offer(await _read_selected(client, selection, budget), selection, inputs, budget)
    except LbxError as failure:
        raise SelectedOfferRefused(OfferRefusalKind.INCOMPLETE, failure.code) from None
    budget.check()
    if first.selected_evidence_digest != second.selected_evidence_digest:
        _incomplete("selected_source_changed")
    return replace(second, observations=first.observations + second.observations)


def _validate_configuration(
    selection: SelectedOfferRequest, inputs: SelectedOfferInputs
) -> tuple[SelectedPolicyEvidence, tuple[EvidenceReference, ...]]:
    currency = _required(inputs.currency, "currency_evidence_missing")
    policy = _required(inputs.policy, "policy_evidence_missing")
    if currency.external_billing_account_id != selection.external_billing_account_id:
        _incomplete("currency_account_mismatch")
    if (
        inputs.calendar is not None
        and inputs.calendar.external_billing_account_id != selection.external_billing_account_id
    ):
        _incomplete("calendar_account_mismatch")
    for field in ("tenant_id", "region", "external_billing_account_id", "tariff_id", "tariff_service_id", "period_id"):
        if getattr(policy, field) != getattr(selection, field):
            _incomplete("policy_scope_mismatch")
    if policy.valid_until is not None and policy.valid_until <= policy.valid_from:
        _incomplete("policy_validity_invalid")
    if selection.effective_on < policy.valid_from or (
        policy.valid_until is not None and selection.effective_on >= policy.valid_until
    ):
        _incomplete("policy_not_applicable")
    for field in REQUIRED_POLICY_FIELDS:
        _required(getattr(policy, field), "policy_" + field + "_unknown")
    for field, known_values in (
        ("tax_treatment", {"included", "not_applicable", "additional"}),
        ("account_discounts", {"none", "present"}),
        ("proration", {"none", "proportional"}),
        ("historical_applicability", {"pinned_effective_terms", "mutable_current"}),
        ("connection_charge_basis", {"per_service_unit", "once", "tiered"}),
    ):
        if getattr(policy, field) not in known_values:
            _incomplete("policy_" + field + "_unknown")
    references = (
        currency.evidence,
        policy.evidence,
        selection.quantity_evidence,
        _required(policy.account_binding, "account_binding_unproven"),
        _required(policy.list_completeness, "list_completeness_unproven"),
        _required(policy.price_applicability, "price_applicability_unproven"),
        _required(policy.historical_policy, "historical_policy_unproven"),
    )
    # DOCUMENTED is not account-specific credential/currency/history proof.
    for proof in (currency.evidence, references[3], references[4], references[6]):
        if proof.basis == CommercialEvidenceBasis.DOCUMENTED:
            _incomplete("account_evidence_required")
    if not policy.complete_selected_lists:
        _incomplete("partial_selected_lists")
    if policy.effective_price_rule != "latest_start_inclusive_next_exclusive":
        _incomplete("price_applicability_unknown")
    return policy, references


def _price_start(price: LbxServicePrice | LbxInlinePrice) -> date:
    return _required(
        price.start_date if isinstance(price, LbxServicePrice) else price.price_start_date, "price_start_unknown"
    )


def _applicable_price[Price: (LbxServicePrice, LbxInlinePrice)](
    prices: list[Price], period: LbxTariffPeriod, effective_on: date, budget: PreflightBudget
) -> tuple[Price, date | None]:
    relevant = [row for row in prices if row.period_id == period.period_id]
    for row in relevant:
        budget.check()
        _price_start(row)
        if isinstance(row, LbxServicePrice) and (row.period_type, row.period_length) != (
            period.period_type,
            period.period_length,
        ):
            _incomplete("price_period_conflict")
    relevant.sort(key=_price_start)
    if len({_price_start(row) for row in relevant}) != len(relevant):
        _incomplete("price_applicability_ambiguous")
    for index, row in enumerate(relevant):
        following = _price_start(relevant[index + 1]) if index + 1 < len(relevant) else None
        if isinstance(row, LbxServicePrice) and row.next_change_date is not None and row.next_change_date != following:
            _incomplete("price_schedule_gap_or_overlap")
    applicable = [row for row in relevant if _price_start(row) <= effective_on]
    if not applicable:
        _incomplete("applicable_price_missing")
    row = applicable[-1]
    index = relevant.index(row)
    until = _price_start(relevant[index + 1]) if index + 1 < len(relevant) else None
    return row, until


def normalize_selected_offer(
    reads: SelectedReadSet,
    selection: SelectedOfferRequest,
    inputs: SelectedOfferInputs,
    budget: PreflightBudget,
) -> SelectedCommercialOffer:
    """No defaults for material facts; unsupported is classified after completeness."""
    budget.check()
    policy, proofs = _validate_configuration(selection, inputs)
    observations: list[CommercialObservation] = []
    paths = (
        f"/tariffs/{selection.tariff_id}",
        f"/tariffs/{selection.tariff_id}/periods",
        f"/tariffs/{selection.tariff_id}/services",
        f"/tariffs/{selection.tariff_id}/services/{selection.tariff_service_id}/prices",
    )
    for read, path in zip((reads.tariff, reads.periods, reads.services, reads.prices), paths, strict=True):
        budget.check()
        if read.external_billing_account_id != selection.external_billing_account_id:
            _incomplete("source_account_mismatch")
        if read.tariff_id != selection.tariff_id:
            _incomplete("source_offer_mismatch")
        if read.observed_at.tzinfo is None or read.observed_at.utcoffset() is None:
            _incomplete("source_observation_invalid")
        observations.append(CommercialObservation(path, read.observed_at))
    if reads.prices.tariff_service_id != selection.tariff_service_id:
        _incomplete("source_component_mismatch")
    tariff = reads.tariff.value
    if tariff.tariff_id != selection.tariff_id:
        _incomplete("source_offer_mismatch")
    periods = [row for row in reads.periods.value if row.period_id == selection.period_id]
    services = [row for row in reads.services.value if row.tariff_service_id == selection.tariff_service_id]
    if len(periods) != 1:
        _incomplete("period_membership_missing_or_ambiguous")
    if len(services) != 1 or services[0].tariff_id != selection.tariff_id:
        _incomplete("component_membership_missing_or_ambiguous")
    period, service = periods[0], services[0]
    # Validate default assignment for every service in the complete tariff, not just the selected one.
    component_ids: set[int] = set()
    default_components: list[str] = []
    for component in reads.services.value:
        budget.check()
        if component.tariff_id != selection.tariff_id or component.tariff_service_id in component_ids:
            _incomplete("component_membership_missing_or_ambiguous")
        component_ids.add(component.tariff_service_id)
        flag = _required(component.enabled_by_default, "component_enabled_by_default_unknown")
        if flag not in (0, 1):
            _incomplete("component_enabled_by_default_unknown")
        if flag == 1:
            default_components.append(str(component.tariff_service_id))
    for owner, fields, prefix in ((tariff, _TARIFF_FLAGS, "offer_"), (service, _SERVICE_FLAGS, "component_")):
        for field in fields:
            _required(getattr(owner, field), prefix + field + "_unknown")
    for field in ("hidden", "period_type", "period_length"):
        _required(getattr(period, field), "period_" + field + "_unknown")
    for owner, fields in (
        (
            tariff,
            (
                "archive",
                "balance_blocks",
                "dynamic_rent_unblock_type",
                "payment_type",
                "assign_unavailable",
                "client_unavailable",
                "proportional_rent",
            ),
        ),
        (service, ("periodic_service", "user_can_set_mul", "user_available", "archive", "hidden_for_user")),
    ):
        if any(getattr(owner, field) not in (0, 1) for field in fields):
            _incomplete("source_flag_meaning_unknown")
    if tariff.dynamic_rent not in (0, 1, 2):
        _incomplete("pricing_algorithm_unknown")
    if period.period_type not in PERIOD_UNITS or tariff.float_period not in PERIOD_ANCHORS:
        _incomplete("period_meaning_unknown")
    price, effective_until = _applicable_price(reads.prices.value, period, selection.effective_on, budget)
    inline = [row for row in _required(service.prices, "inline_prices_missing") if row.period_id == selection.period_id]
    if len(inline) != 1:
        _incomplete("inline_price_missing_or_ambiguous")
    for field in ("price", "connection_price", "bulk_price", "bulk_include_amount"):
        _required(getattr(price, field), "effective_" + field + "_unknown")
        _required(getattr(inline[0], field), "inline_" + field + "_unknown")
        if field != "bulk_include_amount":
            _exact(getattr(price, field), "effective_money_invalid")
            _exact(getattr(inline[0], field), "inline_money_invalid")
        if getattr(price, field) != getattr(inline[0], field):
            _incomplete("inline_effective_price_conflict")
    if inline[0].price_start_date != price.start_date:
        _incomplete("inline_effective_date_conflict")
    discount_rows = selected_discounts(service, inline[0])
    currency = _required(inputs.currency, "currency_evidence_missing")
    if tariff.currency_id != currency.currency_id:
        _incomplete("currency_identity_mismatch")
    iso = _required(currency.iso_currency, "currency_iso_unknown")
    units = _required(currency.source_units, "money_units_unknown")
    scale = _required(currency.decimal_places, "money_scale_unknown")
    if type(scale) is not int or not 0 <= scale <= MAX_MONEY_SCALE:
        _incomplete("money_scale_invalid")
    quantity = _exact(selection.commercial_quantity, "commercial_quantity_invalid")
    # Swagger NewServiceInfo/ExistingServiceInfo require an integer multiplier.
    # This is independent of whether its money product is exact.
    if quantity != quantity.to_integral_value():
        raise SelectedOfferRefused(OfferRefusalKind.NOT_SELLABLE, "commercial_quantity_not_integer")
    recurring = _exact(price.price, "recurring_price_invalid")
    connection = _exact(price.connection_price, "connection_price_invalid")
    _exact(price.bulk_price, "bulk_price_invalid")
    if units == "minor":
        _minor_units(recurring, 0)
        _minor_units(connection, 0)
        recurring_parts, connection_parts = recurring.as_tuple(), connection.as_tuple()
        recurring = Decimal((recurring_parts.sign, recurring_parts.digits, int(recurring_parts.exponent) - scale))
        connection = Decimal((connection_parts.sign, connection_parts.digits, int(connection_parts.exponent) - scale))
    total_recurring = _multiply(recurring, quantity)
    total_connection = (
        _multiply(connection, quantity) if policy.connection_charge_basis == "per_service_unit" else connection
    )
    for amount in (recurring, connection, total_recurring, total_connection):
        _minor_units(amount, scale)
    minimum, maximum = _quantity_bounds(service)
    # All mandatory facts are now known. No catch-all pricing engine.
    unsupported = (
        (service.enabled_by_default != 1, "selected_component_not_default"),
        (len(default_components) > 1, "additional_default_components_unsupported"),
        (tariff.archive != 0 or tariff.assign_unavailable != 0, "offer_unavailable"),
        (service.archive != 0 or period.hidden, "component_or_period_unavailable"),
        (service.periodic_service != 1 or service.bulk_service, "fixed_periodic_profile_required"),
        (tariff.payment_type != 0 or tariff.balance_blocks != 1, "prepaid_blocking_required"),
        (tariff.dynamic_rent != 0 or tariff.dynamic_rent_unblock_type != 0, "fixed_full_funding_required"),
        (tariff.demo_period_length != 0, "demo_unsupported"),
        (tariff.proportional_rent != 0 or policy.proration != "none", "proration_unsupported"),
        (service.user_can_set_mul != 0 or service.user_available != 0, "customer_management_unsupported"),
        (price.bulk_price != 0 or price.bulk_include_amount != 0, "bulk_modifiers_unsupported"),
        (bool(discount_rows) or policy.account_discounts != "none", "discounts_unsupported"),
        (policy.tax_treatment not in {"included", "not_applicable"}, "tax_profile_unsupported"),
        (
            not policy.credit_disabled or not policy.promised_payment_disabled or not policy.manual_activation_disabled,
            "activation_profile_unsupported",
        ),
        (not policy.independent_service_selection, "service_composition_unsupported"),
        (policy.historical_applicability != "pinned_effective_terms", "historical_profile_unsupported"),
        (policy.connection_charge_basis not in {"per_service_unit", "once"}, "connection_profile_unsupported"),
        (
            quantity <= 0 or not minimum <= quantity <= maximum,
            "commercial_quantity_out_of_bounds",
        ),
        (recurring <= 0 or connection < 0, "price_profile_unsupported"),
    )
    for condition, reason in unsupported:
        if condition:
            raise SelectedOfferRefused(OfferRefusalKind.NOT_SELLABLE, reason)
    terms = MaterialCommercialTerms(
        money=CommercialMoney(iso, scale, recurring, connection, total_recurring, total_connection),
        period=CommercialPeriod(
            PERIOD_UNITS[period.period_type],
            period.period_length,
            PERIOD_ANCHORS[tariff.float_period],
            price.start_date,
            effective_until,
        ),
        quantity=CommercialQuantity("commercial_service", quantity, minimum, maximum),
        policy=CommercialPolicy(
            policy.tax_treatment,
            "none",
            policy.proration,
            tariff.demo_period_length,
            True,
            True,
            tariff.block_to_close_days,
            True,
            False,
            False,
            policy.connection_charge_basis,
            policy.renewal_terms,
            policy.cancellation_terms,
            policy.historical_applicability,
        ),
    )
    scope = CommercialScope(selection.tenant_id, selection.region, selection.external_billing_account_id)
    references = CommercialSourceReferences(
        str(selection.tariff_id),
        str(selection.tariff_service_id),
        str(selection.period_id),
        str(period.tariff_period_id),
        str(price.price_id),
    )
    mode, field_sources = selected_offer_provenance(inputs, policy, proofs, references, paths)
    # Only selected material and proven dependencies. No observation/evaluation
    # time, editorial strings, old/future price amounts or unrelated list rows.
    evidence = canonical_document(
        {
            "schema_version": 1,
            "digest_scope": "selected_offer",
            "scope": asdict(scope),
            "references": asdict(references),
            "terms": asdict(terms),
            "evidence_mode": mode,
            "dependencies": {
                "billing_calendar": None if inputs.calendar is None else inputs.calendar.model_dump(mode="json"),
                "default_components": sorted(default_components),
                "currency_definition": {
                    "source_reference": str(currency.currency_id),
                    "currency": iso,
                    "source_units": units,
                    "decimal_places": scale,
                },
                "component_context": {
                    "catalog_reference": str(service.catalog_id),
                    "catalog_component_reference": str(service.catalog_service_id),
                    "fiscal_classification_reference": str(service.payment_object),
                    "visible_to_customer": service.hidden_for_user == 0,
                },
                "offer_visible_to_customer": tariff.client_unavailable == 0,
                "policy_applicability": {
                    "valid_from": policy.valid_from,
                    "valid_until": policy.valid_until,
                    "complete_selected_lists": policy.complete_selected_lists,
                    "independent_service_selection": policy.independent_service_selection,
                    "effective_price_rule": policy.effective_price_rule,
                    "credit_disabled": policy.credit_disabled,
                    "promised_payment_disabled": policy.promised_payment_disabled,
                    "manual_activation_disabled": policy.manual_activation_disabled,
                },
            },
            "field_sources": [asdict(source) for source in field_sources],
        }
    )
    budget.check()
    return SelectedCommercialOffer(
        scope,
        references,
        terms,
        mode,
        "selected_offer",
        commercial_digest(evidence),
        evidence,
        field_sources,
        tuple(observations),
    )
