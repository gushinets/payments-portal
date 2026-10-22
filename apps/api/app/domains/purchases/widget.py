"""Every explicit open repeats local ownership/consent and current point proof.

No new-sale catalog reads, CREATE, paid projection or token persistence occurs.
Historical links without original purchase evidence fail closed.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.domains.catalog.commercial_offer import CommercialScope
from app.domains.purchases.contracts import AcceptedPurchase, PurchaseRefused
from app.domains.purchases.preparation_contracts import Gateway, PreparationEvidence, ProofState
from app.domains.purchases.review import require_exact_consent
from app.domains.legal.service import ACCEPTANCE_KIND_BY_DOC_TYPE, expected_acceptance_text_hash
from app.infrastructure.queries import purchase_preparation, widget as queries
from app.models import (
    AuthSession,
    AcceptanceKind,
    DocumentVersion,
    ExternalBillingCustomerBindingState,
    ExternalCreateOperationKind,
    LegalAcceptanceEvent,
    LegalEntity,
    LegalEntityStatus,
    PurchaseIntent,
    PurchaseIntentState,
    User,
    UserStatus,
)


@dataclass(frozen=True, repr=False)
class WidgetPrincipal:
    user_id: UUID
    session_id: UUID


@dataclass(frozen=True)
class WidgetProofInput:
    intent_id: UUID
    customer_id: str
    subscription_id: int
    hold_epoch: int
    accepted: AcceptedPurchase = field(repr=False)
    record: PreparationEvidence = field(repr=False)


@dataclass(frozen=True, repr=False)
class WidgetBootstrap:
    credential: str
    mode: Literal["SIMULATED"] = "SIMULATED"


class WidgetApplication:
    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        scope: CommercialScope,
        decode_record: Callable[[str], PreparationEvidence],
        gateway: Gateway,
        clock: Callable[[], datetime],
        issue: Callable[[WidgetProofInput], WidgetBootstrap],
    ) -> None:
        self.factory = factory
        self.scope = scope
        self.decode_record = decode_record
        self.gateway = gateway
        self.clock = clock
        self.issue = issue

    async def bootstrap(self, principal: WidgetPrincipal, product_id: str, intent_id: UUID | None) -> WidgetBootstrap:
        return self.issue(await self.authorize(principal, product_id, intent_id))

    def _load(self, principal: WidgetPrincipal, product_id: str, intent_id: UUID | None) -> WidgetProofInput:
        with self.factory() as db:
            user = db.get(User, principal.user_id)
            session = db.get(AuthSession, principal.session_id)
            if (
                user is None
                or session is None
                or session.user_id != principal.user_id
                or session.revoked_at is not None
                or session.expires_at <= self.clock()
                or user.status != UserStatus.ACTIVE
                or user.email_verified_at is None
                or (user.tenant_id, user.region) != (self.scope.tenant_id, self.scope.region)
                or (session.tenant_id, session.region) != (self.scope.tenant_id, self.scope.region)
            ):
                raise PurchaseRefused("billing_not_ready", 403)
            links = queries.linked_subscriptions(db, user.id, product_id, self.scope.external_billing_account_id)
            if len(links) != 1:
                raise PurchaseRefused("billing_not_ready", 409)
            link = links[0]
            if intent_id is not None and link.purchase_intent_id != intent_id:
                raise PurchaseRefused("purchase_not_found", 404)
            # An imported link is not permission to invent original consent.
            intent = db.get(PurchaseIntent, link.purchase_intent_id) if link.purchase_intent_id else None
            if intent is None or intent.state != PurchaseIntentState.LINKED:
                raise PurchaseRefused("billing_not_ready", 409)
            accepted = AcceptedPurchase.model_validate_json(json.dumps(intent.accepted_snapshot))
            require_exact_consent(accepted.request, accepted.review)
            if (
                accepted.user_id != user.id
                or accepted.request.product_id != product_id
                or (accepted.tenant_id, accepted.region, accepted.external_billing_account_id)
                != (self.scope.tenant_id, self.scope.region, self.scope.external_billing_account_id)
                or link.customer_id != intent.customer_id
                or link.user_id != intent.user_id
                or link.mapping_revision_id != accepted.review.revision_id
                or intent.accepted_commercial_fingerprint != accepted.review.fingerprint
            ):
                raise PurchaseRefused("identity_conflict", 409)
            event = db.get(LegalAcceptanceEvent, intent.legal_acceptance_event_id)
            if (
                event is None
                or event.user_id != user.id
                or (event.tenant_id, event.region) != (accepted.tenant_id, accepted.region)
                or event.external_billing_account_id != accepted.external_billing_account_id
                or event.billing_offer_id != accepted.review.mapping.material.billing_offer_id
                or event.accepted_commercial_fingerprint != accepted.review.fingerprint
            ):
                raise PurchaseRefused("billing_not_ready", 409)
            selections = queries.document_acceptances(db, event.id)
            if {(row.document_version_id, row.acceptance_text_hash) for row in selections} != {
                (pin.document_version_id, pin.acceptance_text_hash) for pin in accepted.review.documents
            } or any(row.user_id != user.id for row in selections):
                raise PurchaseRefused("billing_not_ready", 409)
            pins = {pin.document_version_id: pin for pin in accepted.review.documents}
            if any(
                row.acceptance_kind
                != ACCEPTANCE_KIND_BY_DOC_TYPE.get(
                    pins[row.document_version_id].doc_type, AcceptanceKind.TERMS_ACCEPTANCE
                )
                for row in selections
            ):
                raise PurchaseRefused("billing_not_ready", 409)
            for pin in accepted.review.documents:
                document = db.get(DocumentVersion, pin.document_version_id)
                entity = db.get(LegalEntity, pin.legal_entity_id)
                # Original versions may be retired; their meaning must remain identical.
                if (
                    document is None
                    or entity is None
                    or entity.status != LegalEntityStatus.ACTIVE
                    or (entity.tenant_id, entity.region) != (accepted.tenant_id, accepted.region)
                    or document.legal_entity_id != pin.legal_entity_id
                    or document.content_hash != pin.content_hash
                    or document.version != pin.version
                    or document.doc_type != pin.doc_type
                    or document.url_path != pin.url_path
                    or expected_acceptance_text_hash(document) != pin.acceptance_text_hash
                ):
                    raise PurchaseRefused("billing_not_ready", 409)
            try:
                hold, customer = purchase_preparation.locked_owner(db, intent)
            except ValueError:
                raise PurchaseRefused("manual_review_required", 409) from None
            if intent.state != PurchaseIntentState.LINKED:
                raise PurchaseRefused("manual_review_required", 409)
            if (
                customer.binding_state != ExternalBillingCustomerBindingState.BOUND
                or customer.user_id != user.id
                or customer.external_billing_account_id != accepted.external_billing_account_id
                or not customer.provider_customer_id
                or hold.subscription_id != link.subscription_id
            ):
                raise PurchaseRefused("identity_conflict", 409)
            operations = queries.create_operations(db, customer.customer_id, intent.purchase_intent_id)
            if queries.uncertain_customer_create(db, customer.customer_id):
                raise PurchaseRefused("manual_review_required", 409)
            if any(purchase_preparation.open_review(db, row.create_operation_id) is not None for row in operations):
                raise PurchaseRefused("manual_review_required", 409)
            by_kind = {row.operation_kind: row for row in operations}
            agreement = by_kind.get(ExternalCreateOperationKind.AGREEMENT)
            subscription = by_kind.get(ExternalCreateOperationKind.SUBSCRIPTION)
            customer_operation = by_kind.get(ExternalCreateOperationKind.CUSTOMER)
            if (
                customer_operation is not None
                and customer_operation.bound_external_object_id != customer.provider_customer_id
            ):
                raise PurchaseRefused("identity_conflict", 409)
            if (
                agreement is None
                or subscription is None
                or not link.external_subscription_id
                or agreement.bound_external_object_id != link.external_agreement_id
                or subscription.bound_external_object_id != link.external_subscription_id
            ):
                raise PurchaseRefused("billing_not_ready", 409)
            record = self.decode_record(json.dumps(subscription.recovery_hint_document))
            if record.external_agreement_id != link.external_agreement_id:
                raise PurchaseRefused("identity_conflict", 409)
            try:
                record.require_widget_binding(
                    accepted,
                    customer.billing_customer_key,
                    customer.provider_customer_id,
                    link.external_agreement_id,
                    agreement.request_correlation_key,
                    subscription.request_correlation_key,
                )
            except AppError:
                raise PurchaseRefused("identity_conflict", 409) from None
            return WidgetProofInput(
                intent.purchase_intent_id,
                customer.provider_customer_id,
                int(link.external_subscription_id),
                hold.ownership_epoch,
                accepted,
                record,
            )

    async def authorize(self, principal: WidgetPrincipal, product_id: str, intent_id: UUID | None) -> WidgetProofInput:
        before = await asyncio.to_thread(self._load, principal, product_id, intent_id)
        async with self.gateway(before.record, before.accepted) as (gateway, budget):
            # The existing subscription point proof includes fresh GET of the
            # original customer pair and dedicated agreement, then effective terms.
            proof = await gateway.prove(ExternalCreateOperationKind.SUBSCRIPTION, before.subscription_id, budget)
        if proof.state != ProofState.COMPLETE_MATCH or proof.value != before.subscription_id:
            code = (
                "identity_conflict"
                if proof.state in (ProofState.IDENTITY_CONFLICT, ProofState.OWNER_CONFLICT)
                else "commercial_terms_conflict"
                if proof.state == ProofState.MISMATCH
                else "billing_not_ready"
            )
            raise PurchaseRefused(code, 503 if proof.state == ProofState.UNRESOLVED else 409)
        # Close logout/hold-change races across I/O before returning credentials.
        after = await asyncio.to_thread(self._load, principal, product_id, before.intent_id)
        if before != after:
            raise PurchaseRefused("manual_review_required", 409)
        return after
