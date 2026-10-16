from __future__ import annotations

from app.core.errors import AppError
from app.domains.catalog.contracts import CapabilityManifest


class SelectedCapabilityUnavailable(AppError):
    """A valid manifest does not permit the requested new technical binding."""


def require_selected_capability(
    manifest: CapabilityManifest,
    *,
    product_id: str,
    metric_units: dict[str, str],
) -> None:
    """Check only this selection; disabled unrelated capabilities remain valid.

    This neither grants paid access nor upgrades simulated source provenance.
    metric_units is the caller's explicit nonempty approved metric -> unit selection.
    """
    if not metric_units:
        raise SelectedCapabilityUnavailable("selected_metric_required")
    product = next((item for item in manifest.products if item.product_id == product_id), None)
    if product is None:
        raise SelectedCapabilityUnavailable("selected_product_missing")
    if not product.enabled:
        raise SelectedCapabilityUnavailable("selected_product_disabled")
    metrics = {item.metric_key: item for item in manifest.usage_metrics}
    for key, unit in metric_units.items():
        metric = metrics.get(key)
        if metric is None:
            raise SelectedCapabilityUnavailable("selected_metric_missing")
        if metric.product_id != product_id:
            raise SelectedCapabilityUnavailable("selected_metric_owner_mismatch")
        if metric.unit != unit:
            raise SelectedCapabilityUnavailable("selected_metric_unit_mismatch")
        if not metric.enabled:
            raise SelectedCapabilityUnavailable("selected_metric_disabled")
