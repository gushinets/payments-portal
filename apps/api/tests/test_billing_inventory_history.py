"""Consumed retained proof validation; no provider or database calls."""

import pytest
from pydantic import ValidationError

from app.domains.billing.inventory_history import RetainedPointEvidence, complete_owned_point
from app.domains.billing.reconciliation_contracts import IdentityProof, SubscriptionRelationship


def test_retained_point_evidence_uses_owned_relationship_and_accepts_legacy_absence() -> None:
    proof = RetainedPointEvidence.model_validate(
        {
            "identity": "match",
            "complete": False,
            "point_relationship": {"agreement_id": "456", "tariff_id": 702},
            "calendar": {},
        }
    )
    assert proof.identity == IdentityProof.MATCH
    assert proof.point_relationship == SubscriptionRelationship("456", 702)
    assert not complete_owned_point(proof)
    assert complete_owned_point(proof.model_copy(update={"complete": True}))
    legacy = RetainedPointEvidence.model_validate({"identity": "match", "complete": True})
    assert legacy.point_relationship is None and not complete_owned_point(legacy)


@pytest.mark.parametrize(
    "change",
    [
        {"identity": "unknown"},
        {"complete": "true"},
        {"point_relationship": {"agreement_id": None, "tariff_id": 702}},
        {"point_relationship": {"agreement_id": "456", "tariff_id": "unknown"}},
    ],
)
def test_retained_point_evidence_rejects_malformed_consumed_fields(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RetainedPointEvidence.model_validate({"identity": "match", "complete": True, **change})
