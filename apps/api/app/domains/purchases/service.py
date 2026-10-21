"""Purchase admission owns transactions; source reads never hold a DB session."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.domains.catalog.commercial_offer import CommercialScope
from app.domains.legal.service import create_document_acceptance
from app.domains.purchases.contracts import (
    AcceptedPurchase,
    PersistedPurchase,
    PurchaseAdmissionProof,
    PurchaseRefused,
    PurchaseRequest,
    PurchaseReview,
    SellerEvidence,
)
from app.domains.purchases.review import purchase_review, require_exact_consent
from app.domains.purchases.transactions import reserve_purchase_scope
from app.infrastructure.persistence.commercial_mappings import bound_publication_transaction, lock_mapping_scope
from app.infrastructure.persistence.purchase_scopes import PurchaseScopeConflict, PurchaseScopeIdentity
from app.models import (
    DocumentVersion,
    ExternalBillingCustomer,
    LegalAcceptanceEvent,
    LegalEntity,
    PurchaseIntent,
    User,
    UserStatus,
)


class _NewAdmissionRequired(Exception):
    pass


class PurchaseApplication:
    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        scope: CommercialScope,
        allow_simulated: bool,
        profile_terms: Callable[[], tuple[SellerEvidence, bool]],
        fresh_compare: Callable[[PurchaseReview], Awaitable[PurchaseAdmissionProof]],
        clock: Callable[[], datetime],
        lock_timeout_seconds: float,
    ) -> None:
        self.factory = factory
        self.scope = scope
        self.allow_simulated = allow_simulated
        self.profile_terms = profile_terms
        self.fresh_compare = fresh_compare
        self.clock = clock
        self.lock_timeout_seconds = lock_timeout_seconds

    def _review(self, db: Session, product_id: str) -> PurchaseReview:
        seller, recurring = self.profile_terms()
        return purchase_review(
            db,
            scope=self.scope,
            product_id=product_id,
            allow_simulated=self.allow_simulated,
            seller=seller,
            recurring_required=recurring,
            now=self.clock(),
        )

    def review(self, product_id: str) -> PurchaseReview:
        with self.factory() as db:
            return self._review(db, product_id)

    def status(self, user_id: UUID, intent_id: UUID) -> PersistedPurchase:
        with self.factory() as db:
            intent = db.scalar(
                select(PurchaseIntent)
                .join(User, User.id == PurchaseIntent.user_id)
                .where(
                    PurchaseIntent.purchase_intent_id == intent_id,
                    PurchaseIntent.user_id == user_id,
                    PurchaseIntent.external_billing_account_id == self.scope.external_billing_account_id,
                    User.tenant_id == self.scope.tenant_id,
                    User.region == self.scope.region,
                )
            )
            if intent is None:
                raise PurchaseRefused("purchase_not_found", 404)
            return PersistedPurchase(
                purchase_intent_id=intent.purchase_intent_id,
                state=intent.state.value,
                accepted=AcceptedPurchase.model_validate_json(json.dumps(intent.accepted_snapshot)),
                state_updated_at=intent.state_updated_at,
            )

    @staticmethod
    def _matches(intent: PurchaseIntent, payload: PurchaseRequest) -> bool:
        accepted = AcceptedPurchase.model_validate_json(json.dumps(intent.accepted_snapshot))
        if accepted.request.canonical_meaning() != payload.canonical_meaning():
            raise PurchaseRefused("idempotency_conflict", 409)
        return True

    def _reserve(
        self, user_id: UUID, key: str, payload: PurchaseRequest, create: Callable[[Session], PurchaseIntent]
    ) -> UUID:
        try:
            result = reserve_purchase_scope(
                self.factory,
                scope=PurchaseScopeIdentity(
                    user_id,
                    payload.product_id,
                    self.scope.tenant_id,
                    self.scope.region,
                    self.scope.external_billing_account_id,
                ),
                client_idempotency_key=key,
                create_intent=create,
                replay_matches=lambda intent: self._matches(intent, payload),
            )
        except PurchaseScopeConflict:
            raise PurchaseRefused("idempotency_conflict", 409) from None
        if result.occupied:
            raise PurchaseRefused("purchase_scope_occupied", 409)
        if result.purchase_intent_id is None:
            raise PurchaseRefused("purchase_commit_uncertain", 503)
        return result.purchase_intent_id

    def _fast(self, user_id: UUID, key: str, payload: PurchaseRequest) -> UUID:
        def new_admission(_db: Session) -> PurchaseIntent:
            raise _NewAdmissionRequired()

        return self._reserve(user_id, key, payload, new_admission)

    async def purchase(self, user_id: UUID, key: str, payload: PurchaseRequest) -> PersistedPurchase:
        try:
            intent_id = await asyncio.to_thread(self._fast, user_id, key, payload)
            return await asyncio.to_thread(self.status, user_id, intent_id)
        except _NewAdmissionRequired:
            pass
        review = await asyncio.to_thread(self._prepare, user_id, payload)
        # All DB work (including auth's session) is closed before outer HTTP.
        proof = await self.fresh_compare(review)
        intent_id = await asyncio.to_thread(self._commit, user_id, key, payload, review, proof)
        return await asyncio.to_thread(self.status, user_id, intent_id)

    def _prepare(self, user_id: UUID, payload: PurchaseRequest) -> PurchaseReview:
        with self.factory() as db:
            user = db.get(User, user_id)
            if user is None or user.status != UserStatus.ACTIVE or user.email_verified_at is None:
                raise PurchaseRefused("purchase_ineligible", 403)
            review = self._review(db, payload.product_id)
            require_exact_consent(payload, review)
            return review

    def _commit(
        self,
        user_id: UUID,
        key: str,
        payload: PurchaseRequest,
        review: PurchaseReview,
        proof: PurchaseAdmissionProof,
    ) -> UUID:
        def create(db: Session) -> PurchaseIntent:
            self._require_current_proof(proof)
            bound_publication_transaction(db, deadline=proof.deadline, lock_timeout_seconds=self.lock_timeout_seconds)
            lock_mapping_scope(
                db, account_id=self.scope.external_billing_account_id, offer_id=review.mapping.material.billing_offer_id
            )
            # Prevent selected legal rows from being retired/edited until commit.
            list(
                db.scalars(
                    select(DocumentVersion)
                    .where(DocumentVersion.id.in_([doc.document_version_id for doc in review.documents]))
                    .with_for_update(read=True)
                )
            )
            list(
                db.scalars(
                    select(LegalEntity)
                    .where(LegalEntity.id.in_({doc.legal_entity_id for doc in review.documents}))
                    .with_for_update(read=True)
                )
            )
            current = self._review(db, payload.product_id)
            require_exact_consent(payload, current)
            user = db.get(User, user_id)
            if user is None or user.status != UserStatus.ACTIVE or user.email_verified_at is None:
                raise PurchaseRefused("purchase_ineligible", 403)
            now = self.clock()
            event = LegalAcceptanceEvent(
                id=uuid4(),
                tenant_id=self.scope.tenant_id,
                region=self.scope.region,
                user_id=user_id,
                external_billing_account_id=self.scope.external_billing_account_id,
                billing_offer_id=review.mapping.material.billing_offer_id,
                accepted_commercial_fingerprint=review.fingerprint,
                accepted_at=now,
            )
            db.add(event)
            db.flush()
            for pin in review.documents:
                document = db.get(DocumentVersion, pin.document_version_id)
                if document is None:
                    raise PurchaseRefused("purchase_legal_unavailable", 503)
                create_document_acceptance(
                    db, document=document, acceptance_event=event, acceptance_text_hash=pin.acceptance_text_hash
                )
            customer = db.scalar(
                select(ExternalBillingCustomer).where(
                    ExternalBillingCustomer.external_billing_account_id == self.scope.external_billing_account_id,
                    ExternalBillingCustomer.user_id == user_id,
                )
            )
            if customer is None:
                customer = ExternalBillingCustomer(
                    customer_id=uuid4(),
                    external_billing_account_id=self.scope.external_billing_account_id,
                    user_id=user_id,
                    billing_customer_key=uuid4().hex,
                )
                db.add(customer)
                db.flush()
            accepted = AcceptedPurchase(
                tenant_id=self.scope.tenant_id,
                region=self.scope.region,
                external_billing_account_id=self.scope.external_billing_account_id,
                user_id=user_id,
                request=payload,
                review=review,
                admission=proof,
                accepted_at=now,
            )
            intent = PurchaseIntent(
                purchase_intent_id=uuid4(),
                user_id=user_id,
                customer_id=customer.customer_id,
                external_billing_account_id=self.scope.external_billing_account_id,
                product_id=payload.product_id,
                billing_offer_id=review.mapping.material.billing_offer_id,
                mapping_revision_id=review.revision_id,
                accepted_commercial_fingerprint=review.fingerprint,
                client_idempotency_key=key,
                accepted_snapshot_schema_version="v1",
                accepted_snapshot=accepted.model_dump(mode="json"),
                legal_acceptance_event_id=event.id,
            )
            db.add(intent)
            db.flush()
            self._require_current_proof(proof)
            return intent

        try:
            intent_id = self._reserve(user_id, key, payload, create)
        except DBAPIError:
            # A lost COMMIT acknowledgement is not proof of rollback. Resolve
            # only by the original key/meaning in a new authoritative session.
            try:
                intent_id = self._fast(user_id, key, payload)
            except (_NewAdmissionRequired, DBAPIError):
                raise PurchaseRefused("purchase_commit_uncertain", 503) from None
        return intent_id

    def _require_current_proof(self, proof: PurchaseAdmissionProof) -> None:
        now = self.clock()
        if now.utcoffset() is None or now.astimezone(ZoneInfo(proof.timezone)).date() != proof.effective_on:
            raise PurchaseRefused("purchase_effective_date_changed", 409)
        if time.monotonic() >= proof.deadline:
            raise PurchaseRefused("purchase_admission_expired", 503)
