"""One resumable purchase use case; transactions end before every source await.

The persisted create operation is the send authority. No elapsed-time retry,
background task, paid-state observation or access-primary selection lives here.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.domains.catalog.commercial_offer import CommercialScope
from app.domains.purchases.contracts import AcceptedPurchase, PurchaseAdmissionProof, PurchaseRefused, PurchaseReview
from app.domains.purchases.preparation_review import escalate_overdue, review_operation
from app.domains.purchases.preparation_contracts import (
    CreateUncertain,
    Gateway,
    PreparationContext,
    PreparationEvidence,
    PreparationProof,
    PreparationStep,
    ProofState,
    require_current_preparation_proof,
)
from app.infrastructure.persistence.external_creates import (
    ExternalCreateClaim,
    bind_external_create,
    claim_external_create,
)
from app.infrastructure.queries import purchase_preparation as queries
from app.models import (
    ExternalBillingCustomer,
    ExternalBillingCustomerBindingState,
    ExternalCreateOperation,
    ExternalCreateOperationKind,
    ExternalCreateOperationState,
    ExternalSubscription,
    ExternalSubscriptionCommercialAccessStatus,
    ExternalSubscriptionFinancialAccessStatus,
    ExternalSubscriptionLifecycleStatus,
    PurchaseIntent,
    PurchaseIntentState,
    User,
    UserStatus,
)


class PurchasePreparation:
    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        scope: CommercialScope,
        fresh_compare: Callable[[PurchaseReview], Awaitable[PurchaseAdmissionProof]],
        make_record: Callable[[PreparationContext, ExternalCreateOperationKind, str], PreparationEvidence],
        decode_record: Callable[[str], PreparationEvidence],
        gateway: Gateway,
        clock: Callable[[], datetime],
    ) -> None:
        self.factory = factory
        self.scope = scope
        self.fresh_compare = fresh_compare
        self.make_record = make_record
        self.decode_record = decode_record
        self.gateway = gateway
        self.clock = clock

    def _owned(self, db: Session, user_id: UUID, intent_id: UUID) -> PurchaseIntent:
        intent = queries.owned_intent(
            db,
            user_id,
            intent_id,
            tenant_id=self.scope.tenant_id,
            region=self.scope.region,
            account_id=self.scope.external_billing_account_id,
        )
        if intent is None:
            raise PurchaseRefused("purchase_not_found", 404)
        return intent

    @staticmethod
    def _accepted(intent: PurchaseIntent) -> AcceptedPurchase:
        return AcceptedPurchase.model_validate_json(json.dumps(intent.accepted_snapshot))

    @staticmethod
    def _eligible(db: Session, user_id: UUID) -> User:
        user = db.get(User, user_id)
        if user is None or user.status != UserStatus.ACTIVE or user.email_verified_at is None:
            raise PurchaseRefused("purchase_ineligible", 403)
        return user

    def _next(
        self, user_id: UUID, intent_id: UUID, *, read_only: bool, inspection: bool = False
    ) -> PreparationStep | None:
        with self.factory.begin() as db:
            intent = self._owned(db, user_id, intent_id)
            if not inspection and intent.state in (
                PurchaseIntentState.LINKED,
                PurchaseIntentState.MANUAL_REVIEW,
                PurchaseIntentState.FAILED_BEFORE_EXTERNAL_EFFECT,
                PurchaseIntentState.RESOLVED_NO_EXTERNAL_EFFECT,
            ):
                return None
            try:
                hold, customer = queries.locked_owner(db, intent)
            except ValueError:
                raise PurchaseRefused("purchase_scope_occupied", 409) from None
            if not inspection and customer.binding_state == ExternalBillingCustomerBindingState.IDENTITY_CONFLICT:
                intent.state = PurchaseIntentState.MANUAL_REVIEW
                intent.state_updated_at = self.clock()
                return None
            accepted = self._accepted(intent)
            customer_op = queries.operation_for(db, intent, ExternalCreateOperationKind.CUSTOMER)
            agreement_op = queries.operation_for(db, intent, ExternalCreateOperationKind.AGREEMENT)
            # A shared customer created by an earlier intent must use B12. A
            # newly point-bound customer has no prior account inventory to mirror.
            created_here = (
                customer_op is not None
                and customer_op.operation_state == ExternalCreateOperationState.BOUND
                and customer_op.created_at >= intent.created_at
                and not queries.other_customer_operations(db, intent)
            )
            for kind in ExternalCreateOperationKind:
                operation = queries.operation_for(db, intent, kind)
                if operation is not None and operation.operation_state == ExternalCreateOperationState.BOUND:
                    continue
                if (
                    kind == ExternalCreateOperationKind.CUSTOMER
                    and customer.binding_state == ExternalBillingCustomerBindingState.BOUND
                ):
                    if not customer.provider_customer_id:
                        raise PurchaseRefused("purchase_customer_identity_unproven", 409)
                    continue
                if operation is None:
                    if read_only:
                        return None
                    user = self._eligible(db, user_id)
                    if kind == ExternalCreateOperationKind.SUBSCRIPTION and queries.local_subscription_conflict(
                        db, intent
                    ):
                        raise PurchaseRefused("purchase_scope_occupied", 409)
                    correlation = uuid4().hex
                    record = self.make_record(
                        PreparationContext(
                            accepted,
                            customer.billing_customer_key,
                            user.email,
                            customer.provider_customer_id,
                            self.decode_record(json.dumps(agreement_op.recovery_hint_document))
                            if agreement_op is not None
                            else None,
                            agreement_op.bound_external_object_id if agreement_op is not None else None,
                            created_here,
                        ),
                        kind,
                        correlation,
                    )
                    operation = ExternalCreateOperation(
                        create_operation_id=uuid4(),
                        external_billing_account_id=intent.external_billing_account_id,
                        customer_id=customer.customer_id,
                        purchase_intent_id=None if kind == ExternalCreateOperationKind.CUSTOMER else intent_id,
                        operation_kind=kind,
                        request_correlation_key=correlation,
                        operation_state=ExternalCreateOperationState.UNSENT,
                        recovery_hint_schema_version=record.schema_version,
                        recovery_hint_document=record.storage_document(),
                    )
                    db.add(operation)
                    db.flush()
                if not inspection and operation.operation_state in (
                    ExternalCreateOperationState.MANUAL_REVIEW,
                    ExternalCreateOperationState.FAILED_BEFORE_SEND,
                ):
                    intent.state = PurchaseIntentState.MANUAL_REVIEW
                    intent.state_updated_at = self.clock()
                    return None
                return PreparationStep(
                    operation.create_operation_id,
                    kind,
                    operation.operation_state,
                    ExternalCreateClaim(
                        operation.create_operation_id, operation.send_fencing_token, operation.scope_ownership_epoch
                    ),
                    self.decode_record(json.dumps(operation.recovery_hint_document)),
                    accepted,
                    created_here,
                    hold.ownership_epoch,
                )
            return None

    def _claim(
        self, user_id: UUID, intent_id: UUID, step: PreparationStep, proof: PurchaseAdmissionProof
    ) -> ExternalCreateClaim | None:
        with self.factory.begin() as db:
            intent = self._owned(db, user_id, intent_id)
            try:
                hold, _ = queries.locked_owner(db, intent)
            except ValueError:
                raise PurchaseRefused("purchase_scope_occupied", 409) from None
            if hold.ownership_epoch != step.hold_epoch:
                return None
            self._eligible(db, user_id)
            if intent.state in (PurchaseIntentState.MANUAL_REVIEW, PurchaseIntentState.LINKED):
                return None
            require_current_preparation_proof(step.accepted, proof, self.clock())
            if step.kind == ExternalCreateOperationKind.SUBSCRIPTION and queries.local_subscription_conflict(
                db, intent
            ):
                raise PurchaseRefused("purchase_scope_occupied", 409)
            claim = claim_external_create(db, step.operation_id, now=self.clock())
            if claim is not None:
                intent.state = PurchaseIntentState.PREPARING
                intent.state_updated_at = self.clock()
            return claim

    def _review_operation(
        self,
        db: Session,
        operation: ExternalCreateOperation,
        intent: PurchaseIntent,
        *,
        reason: str,
        principal: str = "purchase-preparation",
        identity_conflict: bool = False,
    ) -> None:
        review_operation(
            db,
            operation,
            intent,
            reason=reason,
            principal=principal,
            identity_conflict=identity_conflict,
            clock=self.clock,
            decode_record=self.decode_record,
        )

    def _outcome(
        self,
        user_id: UUID,
        intent_id: UUID,
        step: PreparationStep,
        *,
        reason: str,
        manual: bool = False,
        before_send: bool = False,
        identity_conflict: bool = False,
    ) -> None:
        with self.factory.begin() as db:
            intent = self._owned(db, user_id, intent_id)
            # The old hold remains the first lock even following audited release.
            queries.lock_original_scope(db, intent)
            operation = queries.lock_operation(db, step.operation_id)
            if (
                operation.operation_state == ExternalCreateOperationState.BOUND
                or operation.send_fencing_token != step.claim.send_fencing_token
            ):
                return
            if manual:
                self._review_operation(db, operation, intent, reason=reason, identity_conflict=identity_conflict)
            elif operation.operation_state != ExternalCreateOperationState.MANUAL_REVIEW:
                operation.operation_state = (
                    ExternalCreateOperationState.FAILED_BEFORE_SEND
                    if before_send
                    else ExternalCreateOperationState.UNKNOWN
                )
                operation.updated_at = self.clock()
                if before_send:
                    operation.resolved_at = self.clock()
                    queries.complete_recovery_item(db, operation.create_operation_id)
                    self._review_operation(db, operation, intent, reason=reason)
                    operation.operation_state = ExternalCreateOperationState.FAILED_BEFORE_SEND
                else:
                    intent.state = PurchaseIntentState.AWAITING_EXTERNAL_RESULT
                intent.state_updated_at = self.clock()

    def _bind(self, user_id: UUID, intent_id: UUID, step: PreparationStep, object_id: int) -> bool:
        with self.factory.begin() as db:
            intent = self._owned(db, user_id, intent_id)
            queries.lock_original_scope(db, intent)
            try:
                hold, _ = queries.locked_owner(db, intent)
            except ValueError:
                operation = queries.lock_operation(db, step.operation_id)
                self._review_operation(db, operation, intent, reason="late_create_fence_conflict")
                return False
            operation = queries.lock_operation(db, step.operation_id)
            if (
                operation.operation_state == ExternalCreateOperationState.BOUND
                and operation.bound_external_object_id == str(object_id)
                and operation.send_fencing_token == step.claim.send_fencing_token
                and operation.scope_ownership_epoch == step.claim.scope_ownership_epoch
            ):
                # A competing recovery can finish the same proof first. Linking
                # its subscription advances the hold epoch, but a repeated
                # result for that exact bound operation remains harmless.
                return False
            if hold.ownership_epoch != step.hold_epoch:
                self._review_operation(db, operation, intent, reason="late_create_fence_conflict")
                return False
            if step.kind == ExternalCreateOperationKind.AGREEMENT and queries.agreement_already_linked(
                db, intent.external_billing_account_id, str(object_id)
            ):
                operation = queries.lock_operation(db, step.operation_id)
                self._review_operation(db, operation, intent, reason="agreement_already_linked")
                return False
            if not bind_external_create(db, step.claim, verified_external_object_id=str(object_id), now=self.clock()):
                operation = queries.lock_operation(db, step.operation_id)
                if (
                    operation.operation_state != ExternalCreateOperationState.BOUND
                    or operation.bound_external_object_id != str(object_id)
                ):
                    self._review_operation(db, operation, intent, reason="late_create_fence_conflict")
                return False
            operation = db.get(ExternalCreateOperation, step.operation_id)
            operation.recovery_hint_document = step.record.point_proven_document(self.clock())
            if step.kind == ExternalCreateOperationKind.CUSTOMER:
                customer = db.get(ExternalBillingCustomer, intent.customer_id)
                customer.provider_customer_id = str(object_id)
                customer.binding_state = ExternalBillingCustomerBindingState.BOUND
                customer.binding_updated_at = self.clock()
            elif step.kind == ExternalCreateOperationKind.SUBSCRIPTION:
                if queries.local_subscription_conflict(db, intent):
                    raise IntegrityError("purchase link conflict", None, None)
                assert step.record.external_agreement_id is not None
                subscription = ExternalSubscription(
                    subscription_id=uuid4(),
                    external_billing_account_id=intent.external_billing_account_id,
                    customer_id=intent.customer_id,
                    user_id=intent.user_id,
                    product_id=intent.product_id,
                    purchase_intent_id=intent_id,
                    mapping_revision_id=intent.mapping_revision_id,
                    external_subscription_id=str(object_id),
                    external_agreement_id=step.record.external_agreement_id,
                    lifecycle_status=ExternalSubscriptionLifecycleStatus.INACTIVE,
                    financial_access_status=ExternalSubscriptionFinancialAccessStatus.BLOCKED,
                    commercial_access_status=ExternalSubscriptionCommercialAccessStatus.INELIGIBLE,
                    # Denying placeholder, already expired. No financial-state
                    # observation, allowance or paid trust is asserted here.
                    last_authoritative_read_at=self.clock(),
                    projection_valid_until=self.clock(),
                )
                db.add(subscription)
                db.flush()
                hold.subscription_id = subscription.subscription_id
                hold.ownership_epoch += 1
                intent.state = PurchaseIntentState.LINKED
                intent.resolved_at = self.clock()
            else:
                intent.state = PurchaseIntentState.PREPARING
            intent.state_updated_at = self.clock()
            db.flush()  # uniqueness must succeed before the next CREATE
            return True

    async def inspect(self, user_id: UUID, intent_id: UUID) -> PreparationProof[int] | None:
        """Bounded operator read-only inspection, including an escalated case.

        The private result is evidence for support, never binding or send permission.
        """
        step = await asyncio.to_thread(self._next, user_id, intent_id, read_only=True, inspection=True)
        if step is None or step.state == ExternalCreateOperationState.UNSENT:
            return None
        async with self.gateway(step.record, step.accepted) as (gateway, budget):
            return await gateway.recover(step.kind, budget)

    async def advance(self, user_id: UUID, intent_id: UUID, *, read_only: bool = False) -> None:
        # At most the three selected creates; concurrent claim losers return.
        for _ in ExternalCreateOperationKind:
            step = await asyncio.to_thread(self._next, user_id, intent_id, read_only=read_only)
            if step is None:
                return
            if step.state == ExternalCreateOperationState.UNSENT and read_only:
                return
            claimed = step.state != ExternalCreateOperationState.UNSENT
            try:
                proof = None
                if not claimed:
                    proof = await self.fresh_compare(step.accepted.review)
                    require_current_preparation_proof(step.accepted, proof, self.clock())
                async with self.gateway(step.record, step.accepted) as (gateway, budget):
                    if not claimed:
                        await gateway.before_send(step.kind, budget)
                        if step.kind == ExternalCreateOperationKind.SUBSCRIPTION and not step.customer_created_here:
                            if await gateway.prior_subscription_conflict(budget):
                                await asyncio.to_thread(
                                    self._outcome,
                                    user_id,
                                    intent_id,
                                    step,
                                    reason="prior_subscription_conflict",
                                    manual=True,
                                )
                                return
                        discovered = await gateway.discover_before_send(step.kind, budget)
                        if discovered is not None and (
                            discovered.state != ProofState.COMPLETE_MATCH or discovered.value is None
                        ):
                            await asyncio.to_thread(
                                self._outcome,
                                user_id,
                                intent_id,
                                step,
                                reason=discovered.reason,
                                manual=True,
                                identity_conflict=discovered.state == ProofState.IDENTITY_CONFLICT,
                            )
                            return
                        budget.check()
                        assert proof is not None
                        claim = await asyncio.to_thread(self._claim, user_id, intent_id, step, proof)
                        if claim is None:
                            return
                        step = replace(step, state=ExternalCreateOperationState.POSSIBLE_SEND, claim=claim)
                        claimed = True
                        try:
                            object_id = (
                                discovered.value if discovered is not None else await gateway.create(step.kind, budget)
                            )
                        except CreateUncertain:
                            await asyncio.to_thread(self._outcome, user_id, intent_id, step, reason="create_uncertain")
                            return
                        except AppError:
                            await asyncio.to_thread(
                                self._outcome, user_id, intent_id, step, reason="definite_before_send", before_send=True
                            )
                            return
                        result = await gateway.prove(step.kind, object_id, budget)
                    else:
                        result = await gateway.recover(step.kind, budget)
                    if result.state != ProofState.COMPLETE_MATCH or result.value is None:
                        # A competing continuation can read an incomplete object
                        # before the original CREATE finishes. Keep its claim
                        # recoverable; only proven conflicts require review.
                        await asyncio.to_thread(
                            self._outcome,
                            user_id,
                            intent_id,
                            step,
                            reason=result.reason,
                            manual=result.state
                            in (ProofState.MISMATCH, ProofState.IDENTITY_CONFLICT, ProofState.OWNER_CONFLICT),
                            identity_conflict=result.state == ProofState.IDENTITY_CONFLICT,
                        )
                        return
                    if result.observed_facts is not None:
                        step = replace(
                            step,
                            record=self.decode_record(
                                json.dumps(
                                    {
                                        **step.record.storage_document(),
                                        "provider_observation": result.observed_facts,
                                    }
                                )
                            ),
                        )
                    if not await asyncio.to_thread(self._bind, user_id, intent_id, step, result.value):
                        return
            except IntegrityError:
                # A storage constraint failure needs review; it is not by
                # itself authoritative evidence of a foreign customer.
                await asyncio.to_thread(
                    self._outcome, user_id, intent_id, step, reason="binding_identity_conflict", manual=True
                )
                return
            except DBAPIError:
                # A lost commit acknowledgement cannot authorize POST. The next
                # invocation reads authoritative committed state in a new session.
                raise PurchaseRefused("purchase_commit_uncertain", 503) from None
            except AppError:
                if claimed:
                    await asyncio.to_thread(self._outcome, user_id, intent_id, step, reason="recovery_unavailable")
                    return
                raise

    def escalate_overdue(self, user_id: UUID, intent_id: UUID, *, principal: str) -> int:
        """Explicit operator invocation only; no timer executes this method."""
        return escalate_overdue(
            self.factory,
            user_id,
            intent_id,
            principal=principal,
            owned=self._owned,
            clock=self.clock,
            review=lambda db, operation, intent: self._review_operation(
                db, operation, intent, reason="external_create_unknown_overdue", principal=principal
            ),
        )
