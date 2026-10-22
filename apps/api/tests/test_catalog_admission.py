from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domains.catalog.admission import SelectedCapabilityUnavailable, require_selected_capability
from app.domains.catalog.contracts import (
    CapabilityManifest,
    CapabilityMetric,
    CapabilityProduct,
    SourceProvenance,
)


@pytest.fixture
def manifest() -> CapabilityManifest:
    """Simulated typed facts for the selection predicate, independent of HTTP."""
    return CapabilityManifest(
        schema_version=1,
        tenant_id="anytoolai",
        region="ru",
        manifest_version="simulated-admission-test-manifest",
        generated_at=datetime(2026, 10, 16, tzinfo=UTC),
        products=(CapabilityProduct("proposal_ai", True), CapabilityProduct("kernel_demo", False)),
        usage_metrics=(
            CapabilityMetric("proposal_ai.test_generations", "proposal_ai", "generation", True),
            CapabilityMetric("proposal_ai.second_test_metric", "proposal_ai", "generation", True),
        ),
        provenance=SourceProvenance.SIMULATED,
    )


def test_selected_capability_requires_at_least_one_metric(manifest: CapabilityManifest) -> None:
    with pytest.raises(SelectedCapabilityUnavailable) as error:
        require_selected_capability(manifest, product_id="proposal_ai", metric_units={})
    assert error.value.code == "selected_metric_required"


@pytest.mark.parametrize(
    "metric_units",
    [
        {"proposal_ai.test_generations": "generation"},
        {"proposal_ai.test_generations": "generation", "proposal_ai.second_test_metric": "generation"},
    ],
    ids=["one_metric", "several_metrics_of_one_product"],
)
def test_selected_capability_accepts_nonempty_valid_metrics(
    manifest: CapabilityManifest,
    metric_units: dict[str, str],
) -> None:
    require_selected_capability(manifest, product_id="proposal_ai", metric_units=metric_units)
