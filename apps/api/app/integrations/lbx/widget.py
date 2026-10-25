"""Private HS256 Client JWT policy. No persistence, expiry fiction or logging."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from pydantic import SecretStr

from app.domains.catalog.mapping_evidence import MappingDocument, MappingEvidenceMode
from app.domains.catalog.commercial_offer import CommercialEvidenceMode, CommercialEvidenceBasis
from app.domains.catalog.contracts import SourceProvenance
from app.integrations.lbx.stand import Stand043Permission
from app.domains.purchases.contracts import PurchaseRefused


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class LocalStandWidgetPermission:
    """Explicit mixed-source exception limited to the configured local test stand.

    Application has already proved session, consent, customer, seller and exact
    current subscription. This capability cannot make recorded LBX evidence live.
    """

    stand: Stand043Permission
    user_id: UUID
    mapping: MappingDocument

    def require_source(self) -> None:
        self.stand.require_user(self.user_id)
        self.stand.require_financial_approval()
        document = self.mapping
        material = document.material
        if (
            document.evidence_mode != MappingEvidenceMode.SIMULATED
            or document.kernel_provenance != SourceProvenance.SIMULATED
            or document.lbx_evidence_mode != CommercialEvidenceMode.CONFIGURED_SOURCE
            or material.scope.external_billing_account_id != self.stand.account_id
            or material.technical.product_id != "proposal_ai"
            or material.billing_offer_id != "selected-offer:v1:32:1:1"
            or (material.references.effective_price, material.references.period_membership) != ("288", "82")
            or material.terms.money.currency != "RUB"
            or material.terms.money.decimal_places != 2
            or material.terms.money.recurring_amount != 100
            or material.terms.money.connection_amount != 0
            or material.terms.quantity.selected != 1
            or any(source.basis == CommercialEvidenceBasis.SIMULATED for source in document.field_sources)
        ):
            raise PurchaseRefused("billing_not_ready", 503)


def sign_widget_jwt(
    *,
    customer_id: str,
    secret: SecretStr,
    evidence_mode: MappingEvidenceMode,
    clock: Callable[[], float] = time.time,
    local_permission: LocalStandWidgetPermission | None = None,
) -> str:
    # A recorded proof can never acquire a live credential, even when a real
    # secret happens to be present in the process configuration.
    local_allowed = False
    if local_permission is not None:
        local_permission.require_source()
        local_allowed = evidence_mode == local_permission.mapping.evidence_mode
    key = secret.get_secret_value().encode()
    issued_at = int(clock())
    if (
        (evidence_mode != MappingEvidenceMode.GENUINE and not local_allowed)
        or len(key) < 32
        or not customer_id.isascii()
        or not customer_id.isdecimal()
        or int(customer_id) <= 0
        or customer_id != str(int(customer_id))
        or issued_at < 0
    ):
        raise PurchaseRefused("billing_not_ready", 503)
    header = _encode(b'{"alg":"HS256","typ":"JWT"}')
    payload = _encode(
        json.dumps({"ident_type": 7, "ident": customer_id, "iat": issued_at}, separators=(",", ":")).encode()
    )
    message = f"{header}.{payload}"
    return message + "." + _encode(hmac.new(key, message.encode(), hashlib.sha256).digest())
