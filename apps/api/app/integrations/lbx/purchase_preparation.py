"""Private commands and bounded recovery for explicit account profiles.

The persisted document contains pinned policy and identity commands, never a
credential. Discovery filters are hints; every binding requires a point proof.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

from pydantic import JsonValue, field_serializer, field_validator

from app.domains.catalog.commercial_offer import SelectedCommercialOffer
from app.domains.purchases.contracts import AcceptedPurchase
from app.domains.purchases.preparation_contracts import CreateUncertain
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.errors import (
    LbxCreateUncertain,
    LbxError,
    LbxPreparationBlocked,
    LbxResponseInvalid,
    LbxScopeMismatch,
)
from app.integrations.lbx.preparation import LbxPreparation, PreparationProof, ProofState
from app.integrations.lbx.preparation_dto import PostAgreement, PostSubscription, PostUser, PrivateDto
from app.integrations.lbx.preparation_profile import PreparationProfile
from app.models import ExternalCreateOperationKind


class PreparationRecord(PrivateDto):
    schema_version: Literal["SIMULATED-purchase-preparation-v1", "LOCAL-043-purchase-preparation-v1"] = (
        "SIMULATED-purchase-preparation-v1"
    )
    profile: PreparationProfile
    customer: PostUser
    agreement: PostAgreement | None = None
    subscription: PostSubscription | None = None
    point_proven_at: datetime | None = None
    provider_observation: dict[str, JsonValue] | None = None

    @property
    def billing_evidence_mode(self) -> str:
        return self.profile.source_mode

    @property
    def external_agreement_id(self) -> str | None:
        return str(self.subscription.agreement_id) if self.subscription is not None else None

    def storage_document(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json")

    def point_proven_document(self, observed_at: datetime) -> dict[str, JsonValue]:
        return {**self.storage_document(), "point_proven_at": observed_at.isoformat()}

    def require_widget_binding(
        self,
        accepted: AcceptedPurchase,
        customer_key: str,
        customer_id: str,
        agreement_id: str,
        agreement_correlation: str,
        subscription_correlation: str,
    ) -> None:
        offer_document = next((pin for pin in accepted.review.documents if pin.doc_type == "offer"), None)
        policy = self.profile.inputs.policy
        if (
            self.customer.outer_id != customer_key
            or self.agreement is None
            or self.subscription is None
            or offer_document is None
            or str(self.agreement.user_id) != customer_id
            or str(self.subscription.agreement_id) != agreement_id
            or self.agreement.agreement_number != agreement_correlation
            or self.subscription.outer_id != subscription_correlation
            or self.agreement.organization_id != accepted.review.seller.organization_id
            or self.profile.organization_id != accepted.review.seller.organization_id
            or self.profile.seller_evidence.reference != accepted.review.seller.reference
            or self.profile.seller_evidence.revision != accepted.review.seller.revision
            or (not self.profile.is_stand and self.agreement.agreement_link != offer_document.url_path)
            or (self.profile.is_stand and (self.agreement.is_offer or self.agreement.agreement_link is not None))
            or self.profile.selection.external_billing_account_id != accepted.external_billing_account_id
            or (self.profile.selection.tenant_id, self.profile.selection.region)
            != (accepted.tenant_id, accepted.region)
            or policy is None
            or policy.historical_applicability != "pinned_effective_terms"
        ):
            raise LbxPreparationBlocked()

    @field_serializer("agreement", when_used="json")
    def exact_zero_debt(self, value: PostAgreement | None) -> object:
        if value is None:
            return None
        return (
            value.model_dump(mode="json", exclude_none=True)
            if self.profile.is_stand
            else {**value.model_dump(mode="json"), "debt_threshold": 0}
        )

    @field_serializer("customer")
    def customer_identity_only(self, value: PostUser) -> object:
        # Persist only original ownership/discovery inputs, never transient
        # credentials or profile names. Recovery cannot regenerate credentials.
        return value.model_dump(
            exclude_none=True, exclude={"login", "password", "user_surname", "user_name", "user_patronymic"}
        )

    @field_serializer("profile", when_used="json")
    def without_credential(self, value: PreparationProfile) -> object:
        return value.model_dump(mode="json", exclude={"server_username"})

    @field_validator("profile", mode="before")
    @classmethod
    def recorded_identity(cls, value: object) -> object:
        if isinstance(value, dict):
            # Server identity comes from trusted composition, never storage.
            # Both original schema versions remain recoverable.
            return PreparationProfile.model_validate_json(
                json.dumps(
                    {
                        **value,
                        "server_username": (
                            "COMPOSITION-ONLY"
                            if value.get("source_mode") == "CONFIGURED_SOURCE"
                            else "SIMULATED-purchase-recording"
                        ),
                    }
                )
            )
        return value


class LbxPurchasePreparation:
    def __init__(
        self,
        client: LbxServerClient,
        record: PreparationRecord,
        offer: SelectedCommercialOffer,
        *,
        customer_fields: dict[str, str] | None = None,
    ) -> None:
        self.client = client
        self.record = record
        self.offer = offer
        self.customer_fields = customer_fields or {}
        self.proofs = LbxPreparation(client, record.profile)

    async def before_send(self, kind: ExternalCreateOperationKind, budget: PreflightBudget) -> None:
        record, profile = self.record, self.record.profile
        if kind == ExternalCreateOperationKind.CUSTOMER:
            profile.require_customer(record.customer)
        elif kind == ExternalCreateOperationKind.AGREEMENT:
            if record.agreement is None:
                raise LbxPreparationBlocked()
            profile.require_agreement(record.agreement)
            proof = await self.proofs.prove_customer(
                user_id=record.agreement.user_id, billing_customer_key=record.customer.outer_id, budget=budget
            )
            if proof.state != ProofState.COMPLETE_MATCH:
                raise LbxPreparationBlocked()
        else:
            if record.subscription is None or record.agreement is None:
                raise LbxPreparationBlocked()
            profile.require_subscription(record.subscription, self.offer)
            profile.require_financial_policy()
            self.client.require_financial_approval()
            proof = await self.proofs.prove_agreement(
                agreement_id=record.subscription.agreement_id,
                expected=record.agreement,
                billing_customer_key=record.customer.outer_id,
                budget=budget,
            )
            if proof.state != ProofState.COMPLETE_MATCH:
                raise LbxPreparationBlocked()
        await self.client.prepare_create(budget=budget)

    async def create(self, kind: ExternalCreateOperationKind, budget: PreflightBudget) -> int:
        try:
            return await self._create(kind, budget)
        except LbxCreateUncertain:
            raise CreateUncertain() from None

    async def _create(self, kind: ExternalCreateOperationKind, budget: PreflightBudget) -> int:
        record = self.record
        if kind == ExternalCreateOperationKind.CUSTOMER:
            command = record.customer.model_copy(update=self.customer_fields)
            return (await self.client.create_user(command, profile=record.profile, budget=budget)).user_id
        if kind == ExternalCreateOperationKind.AGREEMENT and record.agreement is not None:
            return (
                await self.client.create_agreement(record.agreement, profile=record.profile, budget=budget)
            ).agreement_id
        if kind == ExternalCreateOperationKind.SUBSCRIPTION and record.subscription is not None:
            return (
                await self.client.create_subscription(
                    record.subscription, profile=record.profile, offer=self.offer, budget=budget
                )
            ).subscription_id
        raise LbxPreparationBlocked()

    async def prove(
        self, kind: ExternalCreateOperationKind, object_id: int, budget: PreflightBudget
    ) -> PreparationProof[int]:
        try:
            return await self._prove(kind, object_id, budget)
        except LbxError as error:
            return self._read_failure(error)

    def _read_failure(self, error: LbxError) -> PreparationProof[int]:
        state = (
            ProofState.IDENTITY_CONFLICT
            if isinstance(error, LbxScopeMismatch)
            else ProofState.INCOMPLETE
            if isinstance(error, (LbxResponseInvalid, LbxPreparationBlocked))
            else ProofState.UNRESOLVED
        )
        return PreparationProof(state, error.code, evidence_mode=self.record.profile.source_mode)

    async def _prove(
        self, kind: ExternalCreateOperationKind, object_id: int, budget: PreflightBudget
    ) -> PreparationProof[int]:
        record = self.record
        if kind == ExternalCreateOperationKind.CUSTOMER:
            proof = await self.proofs.prove_customer(
                user_id=object_id, billing_customer_key=record.customer.outer_id, budget=budget
            )
        elif kind == ExternalCreateOperationKind.AGREEMENT and record.agreement is not None:
            proof = await self.proofs.prove_agreement(
                agreement_id=object_id,
                expected=record.agreement,
                billing_customer_key=record.customer.outer_id,
                budget=budget,
            )
        elif record.subscription is not None and record.agreement is not None:
            if record.profile.is_stand:
                ids = await self.client.discover_subscriptions(user_id=record.agreement.user_id, budget=budget)
                if object_id not in ids:
                    return PreparationProof(ProofState.INCOMPLETE, "subscription_not_in_owner_inventory")
                for candidate in ids:
                    point = await self.client.get_subscription(subscription_id=candidate, budget=budget)
                    if point.agreement_id == record.subscription.agreement_id and candidate != object_id:
                        return PreparationProof(ProofState.OWNER_CONFLICT, "dedicated_agreement_multiple_subscriptions")
            proof = await self.proofs.prove_subscription(
                subscription_id=object_id,
                expected=record.subscription,
                agreement=record.agreement,
                billing_customer_key=record.customer.outer_id,
                offer=self.offer,
                budget=budget,
            )
        else:
            return PreparationProof(ProofState.INCOMPLETE, "command_missing")
        return PreparationProof(
            proof.state,
            proof.reason,
            object_id if proof.state == ProofState.COMPLETE_MATCH else None,
            evidence_mode=record.profile.source_mode,
            observed_facts=proof.observed_facts,
        )

    async def recover(self, kind: ExternalCreateOperationKind, budget: PreflightBudget) -> PreparationProof[int]:
        try:
            return await self._recover(kind, budget)
        except LbxError as error:
            return self._read_failure(error)

    async def _recover(self, kind: ExternalCreateOperationKind, budget: PreflightBudget) -> PreparationProof[int]:
        record = self.record
        if kind == ExternalCreateOperationKind.CUSTOMER:
            hints = await self.proofs.customer_hints(billing_customer_key=record.customer.outer_id, budget=budget)
        elif record.agreement is None:
            return PreparationProof(ProofState.INCOMPLETE, "command_missing")
        elif kind == ExternalCreateOperationKind.AGREEMENT:
            hints = await self.proofs.agreement_hints(
                user_id=record.agreement.user_id, billing_customer_key=record.customer.outer_id, budget=budget
            )
        else:
            hints = await self.proofs.discover(
                user_id=record.agreement.user_id, billing_customer_key=record.customer.outer_id, budget=budget
            )
        if hints.value is None:
            return PreparationProof(hints.state, hints.reason)
        candidates: list[int] = []
        for object_id in hints.value.candidate_ids:
            if kind == ExternalCreateOperationKind.AGREEMENT:
                point = await self.client.get_agreement(agreement_id=object_id, budget=budget)
                if point.agreement_number is None:
                    return PreparationProof(ProofState.INCOMPLETE, "agreement_correlation_missing")
                if point.agreement_number != record.agreement.agreement_number:
                    continue
            elif kind == ExternalCreateOperationKind.SUBSCRIPTION:
                point = await self.client.get_subscription(subscription_id=object_id, budget=budget)
                if point.agreement_id is None or record.subscription is None:
                    return PreparationProof(ProofState.INCOMPLETE, "subscription_owner_missing")
                if point.agreement_id != record.subscription.agreement_id:
                    continue
                # Any other object on the dedicated agreement is a conflict,
                # including an object whose outer_id differs or is missing.
            candidates.append(object_id)
        if len(candidates) > 1:
            return PreparationProof(ProofState.IDENTITY_CONFLICT, "multiple_create_candidates")
        if not candidates:
            return PreparationProof(ProofState.UNRESOLVED, "no_create_candidate")
        return await self.prove(kind, candidates[0], budget)

    async def discover_before_send(
        self, kind: ExternalCreateOperationKind, budget: PreflightBudget
    ) -> PreparationProof[int] | None:
        if not self.record.profile.is_stand:
            return None
        record = self.record
        if kind == ExternalCreateOperationKind.SUBSCRIPTION:
            if await self.prior_subscription_conflict(budget):
                return PreparationProof(ProofState.OWNER_CONFLICT, "prior_subscription_conflict")
            return None
        if kind == ExternalCreateOperationKind.CUSTOMER:
            hints = await self.proofs.customer_hints(billing_customer_key=record.customer.outer_id, budget=budget)
        else:
            assert record.agreement is not None
            hints = await self.proofs.agreement_hints(
                user_id=record.agreement.user_id, billing_customer_key=record.customer.outer_id, budget=budget
            )
        if hints.value is None:
            return PreparationProof(hints.state, hints.reason)
        candidates: list[int] = []
        for object_id in hints.value.candidate_ids:
            if kind == ExternalCreateOperationKind.AGREEMENT:
                point = await self.client.get_agreement(agreement_id=object_id, budget=budget)
                if point.user_id != record.agreement.user_id:
                    return PreparationProof(ProofState.OWNER_CONFLICT, "agreement_owner_conflict")
                if point.organization_id == 9:
                    continue  # Confirmed automatic unrelated agreement, never reusable.
                if point.organization_id != 21 or point.agreement_number != record.agreement.agreement_number:
                    return PreparationProof(ProofState.OWNER_CONFLICT, "unreserved_agreement_requires_review")
                # Dedicated means no subscription at all on this agreement.
                subscriptions = await self.proofs.discover(
                    user_id=point.user_id, billing_customer_key=record.customer.outer_id, budget=budget
                )
                if subscriptions.value is None:
                    return PreparationProof(subscriptions.state, subscriptions.reason)
                for sub_id in subscriptions.value.candidate_ids:
                    sub = await self.client.get_subscription(subscription_id=sub_id, budget=budget)
                    if sub.agreement_id == object_id:
                        return PreparationProof(ProofState.OWNER_CONFLICT, "agreement_already_used")
            candidates.append(object_id)
        if len(candidates) > 1:
            return PreparationProof(ProofState.IDENTITY_CONFLICT, "multiple_create_candidates")
        return await self.prove(kind, candidates[0], budget) if candidates else None

    async def prior_subscription_conflict(self, budget: PreflightBudget) -> bool:
        record = self.record
        if record.agreement is None or not record.profile.subscription_list_complete:
            raise LbxPreparationBlocked()
        hints = await self.proofs.discover(
            user_id=record.agreement.user_id, billing_customer_key=record.customer.outer_id, budget=budget
        )
        if hints.value is None:
            raise LbxPreparationBlocked()
        for object_id in hints.value.candidate_ids:
            point = await self.client.get_subscription(subscription_id=object_id, budget=budget)
            if point.tariff_id is None or point.services is None or point.agreement_id is None:
                raise LbxPreparationBlocked()
            if not point.services or any(service.tariff_service_id is None for service in point.services):
                raise LbxPreparationBlocked()
            if point.tariff_id == self.record.profile.selection.tariff_id:
                # No terminal-state mapping is invented by this preparation
                # slice. A plausible prior selected tariff retains the hold.
                return True
        return False
