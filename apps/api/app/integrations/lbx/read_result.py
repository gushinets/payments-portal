"""Private selected-read result with its configured/requested scope."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class LbxRead(Generic[T]):
    """Integration-only source DTO and configured/requested identity context.

    Account identity is the deployment's credential binding, not a provider
    attestation: these GET responses contain no billing-account identity.
    Normalize this before Application. No atomic snapshot is implied.
    """

    external_billing_account_id: str
    tariff_id: int
    tariff_service_id: int | None
    observed_at: datetime
    value: T
