"""Current selected LBX facts, independent of legacy approval/proof documents."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.core.settings import Settings
from app.domains.catalog.commercial_offer import (
    CommercialEvidenceMode,
    CommercialMoney,
    CommercialPeriod,
    CommercialQuantity,
    OfferRefusalKind,
    SelectedOfferRefused,
    SelectedOfferSourceFailed,
)
from app.domains.catalog.product_link import CurrentOffer, ProductLinkRequest, current_offer_fingerprint
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.errors import LbxError
from app.integrations.lbx.discounts import selected_discounts
from app.integrations.lbx.offer_values import (
    _exact,
    _incomplete,
    _minor_units,
    _multiply,
    _quantity_bounds,
    _required,
)
from app.integrations.lbx.selected_offer import (
    PERIOD_ANCHORS,
    PERIOD_UNITS,
    SelectedReadSet,
    _applicable_price,
    _read_selected,
)


# LBX support confirms that price start dates are inclusive in the Moscow calendar.
BILLING_TIMEZONE = ZoneInfo("Europe/Moscow")


def utc_now() -> datetime:
    return datetime.now(UTC)


def current_billing_date() -> date:
    """The confirmed provider calendar, shared by offer reads and agreement CREATE."""
    return utc_now().astimezone(BILLING_TIMEZONE).date()


def normalize_current_offer(
    reads: SelectedReadSet,
    selection: ProductLinkRequest,
    configuration: Settings,
    budget: PreflightBudget,
    *,
    effective_on: date,
) -> CurrentOffer:
    budget.check()
    tariff = reads.tariff.value
    for read in (reads.tariff, reads.periods, reads.services, reads.prices):
        if (
            read.external_billing_account_id != configuration.lbx_external_billing_account_id
            or read.tariff_id != selection.tariff_id
            or read.observed_at.utcoffset() is None
        ):
            _incomplete("source_scope_mismatch")
    if tariff.tariff_id != selection.tariff_id or reads.prices.tariff_service_id != selection.tariff_service_id:
        _incomplete("source_scope_mismatch")
    periods = [row for row in reads.periods.value if row.period_id == selection.period_id]
    services = [row for row in reads.services.value if row.tariff_service_id == selection.tariff_service_id]
    if len(periods) != 1 or len({row.period_id for row in reads.periods.value}) != len(reads.periods.value):
        _incomplete("period_membership_missing_or_ambiguous")
    if len(services) != 1:
        _incomplete("component_membership_missing_or_ambiguous")
    defaults: list[int] = []
    identities: set[int] = set()
    for row in reads.services.value:
        budget.check()
        if row.tariff_id != selection.tariff_id or row.tariff_service_id in identities:
            _incomplete("component_membership_missing_or_ambiguous")
        identities.add(row.tariff_service_id)
        if row.enabled_by_default not in (0, 1):
            _incomplete("component_enabled_by_default_unknown")
        if row.enabled_by_default == 1:
            defaults.append(row.tariff_service_id)
    service, period = services[0], periods[0]
    for owner, fields in (
        (
            tariff,
            (
                "archive",
                "balance_blocks",
                "block_to_close_days",
                "dynamic_rent",
                "dynamic_rent_unblock_type",
                "payment_type",
                "float_period",
                "assign_unavailable",
                "proportional_rent",
                "demo_period_length",
                "currency_id",
            ),
        ),
        (
            service,
            (
                "bulk_service",
                "periodic_service",
                "min_multiplicator",
                "max_multiplicator",
                "user_can_set_mul",
                "user_available",
                "archive",
            ),
        ),
        (period, ("hidden", "period_type", "period_length")),
    ):
        for field in fields:
            _required(getattr(owner, field), field + "_unknown")
    for owner, fields in (
        (
            tariff,
            (
                "archive",
                "balance_blocks",
                "dynamic_rent_unblock_type",
                "payment_type",
                "assign_unavailable",
                "proportional_rent",
            ),
        ),
        (service, ("periodic_service", "user_can_set_mul", "user_available", "archive")),
    ):
        if any(getattr(owner, field) not in (0, 1) for field in fields):
            _incomplete("source_flag_meaning_unknown")
    if tariff.dynamic_rent not in (0, 1, 2):
        _incomplete("pricing_algorithm_unknown")
    if period.period_type not in PERIOD_UNITS or tariff.float_period not in PERIOD_ANCHORS:
        _incomplete("period_meaning_unknown")
    currency = configuration.lbx_currency_mapping
    if currency is None or tariff.currency_id != currency.provider_currency_id:
        _incomplete("currency_interpretation_unsupported")
    price, until = _applicable_price(reads.prices.value, period, effective_on, budget)
    inline, _ = _applicable_price(_required(service.prices, "inline_prices_missing"), period, effective_on, budget)
    for field in ("price", "connection_price", "bulk_price", "bulk_include_amount"):
        actual = _required(getattr(price, field), field + "_unknown")
        if actual != _required(getattr(inline, field), "inline_" + field + "_unknown"):
            _incomplete("inline_effective_price_conflict")
    if inline.price_start_date != price.start_date:
        _incomplete("inline_effective_date_conflict")
    discount_rows = selected_discounts(service, inline)
    recurring = _exact(price.price, "recurring_price_invalid")
    connection = _exact(price.connection_price, "connection_price_invalid")
    quantity = Decimal(selection.quantity)
    if quantity != 1 and connection != 0:
        _incomplete("connection_quantity_basis_unproven")
    minimum, maximum = _quantity_bounds(service)
    unsupported = (
        (defaults != [selection.tariff_service_id], "additional_or_missing_default_components_unsupported"),
        (
            tariff.archive != 0 or tariff.assign_unavailable != 0 or service.archive != 0 or period.hidden,
            "offer_unavailable",
        ),
        (service.periodic_service != 1 or service.bulk_service, "fixed_periodic_profile_required"),
        (tariff.payment_type != 0 or tariff.balance_blocks != 1, "prepaid_blocking_required"),
        (tariff.dynamic_rent != 0 or tariff.dynamic_rent_unblock_type != 0, "fixed_full_funding_required"),
        (tariff.demo_period_length != 0, "demo_unsupported"),
        (tariff.proportional_rent != 0, "proration_unsupported"),
        (service.user_can_set_mul != 0 or service.user_available != 0, "customer_management_unsupported"),
        (price.bulk_price != 0 or price.bulk_include_amount != 0, "bulk_modifiers_unsupported"),
        (bool(discount_rows), "discounts_unsupported"),
        (not minimum <= quantity <= maximum, "commercial_quantity_out_of_bounds"),
        (recurring <= 0 or connection < 0, "price_profile_unsupported"),
    )
    for condition, reason in unsupported:
        if condition:
            raise SelectedOfferRefused(OfferRefusalKind.NOT_SELLABLE, reason)
    total = _multiply(recurring, quantity)
    for amount in (recurring, connection, total):
        _minor_units(amount, currency.scale)
    money = CommercialMoney(currency.iso_currency, currency.scale, recurring, connection, total, connection)
    normalized_period = CommercialPeriod(
        PERIOD_UNITS[period.period_type],
        period.period_length,
        PERIOD_ANCHORS[tariff.float_period],
        price.start_date,
        until,
    )
    normalized_quantity = CommercialQuantity("commercial_service", quantity, minimum, maximum)
    offer = CurrentOffer(
        money,
        normalized_period,
        normalized_quantity,
        selection.tariff_id,
        selection.tariff_service_id,
        selection.period_id,
        period.tariff_period_id,
        price.price_id,
        True,
        True,
        tariff.block_to_close_days,
        CommercialEvidenceMode.CONFIGURED_SOURCE,
        max(read.observed_at for read in (reads.tariff, reads.periods, reads.services, reads.prices)),
        "",
    )
    return replace(
        offer, fingerprint=current_offer_fingerprint(configuration.lbx_external_billing_account_id, selection, offer)
    )


async def read_current_offer(
    client: LbxServerClient,
    *,
    selection: ProductLinkRequest,
    configuration: Settings,
    budget: PreflightBudget,
) -> CurrentOffer:
    effective_on = current_billing_date()
    try:
        first = normalize_current_offer(
            await _read_selected(client, selection, budget), selection, configuration, budget, effective_on=effective_on
        )
        second = normalize_current_offer(
            await _read_selected(client, selection, budget), selection, configuration, budget, effective_on=effective_on
        )
    except LbxError as error:
        raise SelectedOfferSourceFailed(error.code) from None
    budget.check()
    if first.fingerprint != second.fingerprint:
        raise SelectedOfferSourceFailed("selected_source_changed")
    return second
