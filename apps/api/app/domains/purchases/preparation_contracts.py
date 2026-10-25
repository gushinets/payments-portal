"""Provider-independent capabilities consumed by purchase preparation."""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Generic, Protocol, TypeVar
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import JsonValue

from app.core.errors import AppError
from app.domains.purchases.contracts import AcceptedPurchase, PurchaseAdmissionProof, PurchaseRefused
from app.infrastructure.persistence.external_creates import ExternalCreateClaim
from app.infrastructure.preflight import PreflightBudget
from app.models import ExternalCreateOperationKind, ExternalCreateOperationState


class ProofState(StrEnum):
    COMPLETE_MATCH = "complete_match"
    INCOMPLETE = "incomplete"
    MISMATCH = "mismatch"
    IDENTITY_CONFLICT = "identity_conflict"
    OWNER_CONFLICT = "owner_conflict"
    UNRESOLVED = "unresolved"


T = TypeVar("T")


@dataclass(frozen=True)
class PreparationProof(Generic[T]):
    state: ProofState
    reason: str
    value: T | None = field(default=None, repr=False)
    evidence_mode: str = "SIMULATED"
    observed_facts: dict[str, JsonValue] | None = None


class CreateUncertain(AppError):
    def __init__(self) -> None:
        super().__init__("external_create_uncertain")


class PreparationEvidence(Protocol):
    @property
    def schema_version(self) -> str: ...

    @property
    def billing_evidence_mode(self) -> str: ...

    @property
    def external_agreement_id(self) -> str | None: ...

    def storage_document(self) -> dict[str, JsonValue]: ...

    def point_proven_document(self, observed_at: datetime) -> dict[str, JsonValue]: ...

    def require_widget_binding(
        self,
        accepted: AcceptedPurchase,
        customer_key: str,
        customer_id: str,
        agreement_id: str,
        agreement_correlation: str,
        subscription_correlation: str,
    ) -> None: ...


class PreparationGateway(Protocol):
    async def before_send(self, kind: ExternalCreateOperationKind, budget: PreflightBudget) -> None: ...

    async def create(self, kind: ExternalCreateOperationKind, budget: PreflightBudget) -> int: ...

    async def prove(
        self, kind: ExternalCreateOperationKind, object_id: int, budget: PreflightBudget
    ) -> PreparationProof[int]: ...

    async def recover(self, kind: ExternalCreateOperationKind, budget: PreflightBudget) -> PreparationProof[int]: ...

    async def discover_before_send(
        self, kind: ExternalCreateOperationKind, budget: PreflightBudget
    ) -> PreparationProof[int] | None: ...

    async def prior_subscription_conflict(self, budget: PreflightBudget) -> bool: ...


@dataclass(frozen=True)
class PreparationContext:
    accepted: AcceptedPurchase
    customer_key: str
    email: str
    provider_customer_id: str | None
    agreement_record: PreparationEvidence | None
    agreement_id: str | None
    customer_created_here: bool


@dataclass(frozen=True)
class PreparationStep:
    operation_id: UUID
    kind: ExternalCreateOperationKind
    state: ExternalCreateOperationState
    claim: ExternalCreateClaim
    record: PreparationEvidence
    accepted: AcceptedPurchase
    customer_created_here: bool
    hold_epoch: int


Gateway = Callable[
    [PreparationEvidence, AcceptedPurchase],
    AbstractAsyncContextManager[tuple[PreparationGateway, PreflightBudget]],
]


def require_current_preparation_proof(accepted: AcceptedPurchase, proof: PurchaseAdmissionProof, now: datetime) -> None:
    if (
        now.utcoffset() is None
        or proof.effective_on != accepted.admission.effective_on
        or proof.timezone != accepted.admission.timezone
        or now.astimezone(ZoneInfo(proof.timezone)).date() != proof.effective_on
    ):
        raise PurchaseRefused("purchase_effective_date_changed", 409)
    if time.monotonic() >= proof.deadline:
        raise PurchaseRefused("purchase_admission_expired", 503)
