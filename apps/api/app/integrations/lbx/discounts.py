"""Discount evidence for one selected service/period/current inline price."""

from app.integrations.lbx.dto import LbxDiscount, LbxInlinePrice, LbxTariffService
from app.integrations.lbx.offer_values import _incomplete


def selected_discounts(service: LbxTariffService, inline: LbxInlinePrice) -> list[LbxDiscount]:
    """Support observed price-level and documented service-level representations.

    Callers first prove this inline price matches the selected effective price.
    Missing evidence is not an empty list; explicit null cannot be overridden by
    another representation. Two supplied representations must agree.
    """
    nested_present = "discounts" in inline.model_fields_set
    legacy_present = "discounts" in service.model_fields_set
    nested = inline.discounts
    legacy = None
    if nested_present and nested is None or legacy_present and service.discounts is None:
        _incomplete("discounts_null")
    if legacy_present:
        periods = service.discounts
        assert periods is not None
        selected = [row for row in periods if row.period_id == inline.period_id]
        if len(selected) > 1:
            _incomplete("discounts_ambiguous")
        if selected:
            legacy = selected[0].discounts
            if legacy is None:
                _incomplete("discounts_null" if "discounts" in selected[0].model_fields_set else "discounts_unknown")
        elif not periods:
            legacy = []  # Legacy explicit service-wide empty list.
        else:
            _incomplete("discounts_selected_period_missing")
    for rows in (nested, legacy):
        if rows is not None and len({row.discount_id for row in rows}) != len(rows):
            _incomplete("discounts_ambiguous")
    if nested is not None and legacy is not None:
        if sorted(nested, key=lambda row: row.discount_id) != sorted(legacy, key=lambda row: row.discount_id):
            _incomplete("discounts_conflict")
    result = nested if nested is not None else legacy
    if result is None:
        _incomplete("discounts_unknown")
    return result
