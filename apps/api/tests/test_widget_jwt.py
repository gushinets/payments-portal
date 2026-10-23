"""Cryptographic policy only; these tokens never reach an LBX service."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from pydantic import SecretStr, ValidationError

from app.domains.catalog.mapping_evidence import MappingEvidenceMode
from app.domains.purchases.contracts import PurchaseRefused
from app.integrations.lbx.widget import sign_widget_jwt
from apps.api.tests.support.lbx import lbx_settings


def test_only_type_seven_current_iat_is_signed_without_fake_expiry() -> None:
    secret = SecretStr("test-only-dedicated-client-key-32-bytes")

    def mint(now: int) -> str:
        return sign_widget_jwt(
            customer_id="1501", secret=secret, evidence_mode=MappingEvidenceMode.GENUINE, clock=lambda: now
        )

    token = mint(1792600000)
    header, payload, signature = token.split(".")
    assert json.loads(base64.urlsafe_b64decode(header + "==")) == {"alg": "HS256", "typ": "JWT"}
    assert json.loads(base64.urlsafe_b64decode(payload + "==")) == {"ident_type": 7, "ident": "1501", "iat": 1792600000}
    assert hmac.compare_digest(
        base64.urlsafe_b64decode(signature + "=="),
        hmac.new(secret.get_secret_value().encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest(),
    )
    assert mint(1792600000) == token  # same-second tokens may be identical
    assert mint(1792600001) != token


@pytest.mark.parametrize(
    "customer,key,mode",
    [
        ("1501", "x" * 32, MappingEvidenceMode.SIMULATED),
        ("1501", "short", MappingEvidenceMode.GENUINE),
        ("0", "x" * 32, MappingEvidenceMode.GENUINE),
        ("01501", "x" * 32, MappingEvidenceMode.GENUINE),
        ("provider-label", "x" * 32, MappingEvidenceMode.GENUINE),
    ],
)
def test_simulated_or_invalid_identity_can_never_get_a_live_jwt(
    customer: str, key: str, mode: MappingEvidenceMode
) -> None:
    with pytest.raises(PurchaseRefused, match="billing_not_ready"):
        sign_widget_jwt(customer_id=customer, secret=SecretStr(key), evidence_mode=mode)


def test_runtime_signing_key_must_be_dedicated_and_private() -> None:
    with pytest.raises(ValidationError, match="must be dedicated"):
        lbx_settings(lbx_widget_signing_secret="short")
    with pytest.raises(ValidationError, match="must be dedicated"):
        lbx_settings(lbx_server_password="x" * 32, lbx_widget_signing_secret="x" * 32)
    configuration = lbx_settings(lbx_widget_signing_secret="private-widget-only-key-32-bytes-long")
    assert "private-widget-only-key" not in repr(configuration)
