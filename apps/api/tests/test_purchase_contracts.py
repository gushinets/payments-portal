from __future__ import annotations

from decimal import Decimal, localcontext
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.composition.purchases import load_profile
from app.core.settings import AppEnv
from app.domains.purchases.contracts import PurchaseRefused, PurchaseRequest
from app.domains.purchases.review import initial_amount
from apps.api.tests.support.commercial_mappings import operator_settings


def request_payload() -> dict:
    return {
        "product_id": "proposal_ai",
        "revision_id": str(uuid4()),
        "expected_fingerprint": "sha256:" + "a" * 64,
        "commercial_confirmation": True,
        "recurring_confirmation": False,
        "documents": [{"document_version_id": str(uuid4()), "acceptance_text_hash": "b" * 64}],
    }


def test_request_is_strict_bounded_and_canonical() -> None:
    payload = request_payload()
    payload["documents"].append({"document_version_id": str(uuid4()), "acceptance_text_hash": "c" * 64})
    first = PurchaseRequest.model_validate(payload)
    payload["documents"].reverse()
    assert PurchaseRequest.model_validate(payload).canonical_meaning() == first.canonical_meaning()
    for field in ("user_id", "organization_id", "external_billing_account_id", "metric_key"):
        with pytest.raises(ValidationError):
            PurchaseRequest.model_validate({**payload, field: "browser-controlled"})
    for invalid in ("true", 1, None):
        with pytest.raises(ValidationError):
            PurchaseRequest.model_validate({**payload, "commercial_confirmation": invalid})
    payload["documents"].append(payload["documents"][0])
    with pytest.raises(ValidationError):
        PurchaseRequest.model_validate(payload)


def test_initial_amount_is_lossless_beyond_decimal_context_and_javascript_number() -> None:
    with localcontext() as context:
        context.prec = 3
        assert (
            initial_amount(Decimal("9007199254740993.123456789012345678"), Decimal("0.000000000000000001"), 18)
            == "9007199254740993.123456789012345679"
        )
    assert initial_amount(Decimal("200.02"), Decimal("14.06"), 2) == "214.08"


def test_local_profile_cannot_enable_production_or_fill_missing_configuration() -> None:
    configuration = operator_settings()
    with pytest.raises(PurchaseRefused, match="purchase_not_enabled"):
        load_profile(configuration)
    with pytest.raises(PurchaseRefused, match="purchase_not_enabled"):
        load_profile(configuration.model_copy(update={"app_env": AppEnv.PRODUCTION}))
