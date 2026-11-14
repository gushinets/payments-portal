"""Exhaustion is an immutable reconciliation hint, never paid or financial authority."""

from datetime import datetime
import re
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.core.backend_consumers import BackendConsumer
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import lock_user
from app.domains.billing.paid_contracts import EffectiveState
from app.domains.billing.work import enroll_subscription, finish, verify_claim
from app.domains.billing.work_contracts import WorkClaim
from app.domains.catalog.publication import SessionFactory
from app.domains.catalog.technical_source import TechnicalOwnership
from app.domains.identity.services.auth import as_utc
from app.domains.billing.paid_allowances import allowance_ownership
from app.infrastructure.persistence.billing_work import RECURRING_INDEX
from app.infrastructure.queries import paid_read
from app.infrastructure.queries.backend_policies import BackendPolicyConflict, require_current_policy
from app.infrastructure.queries.billing_reconciliation import database_now
from app.models import (
    BillingWorkItem,
    BillingWorkKind,
    BillingWorkScope,
    BillingWorkState,
    ExternalSubscription,
    PurchasedAllowance,
    User,
)

KIND = BillingWorkKind.ALLOWANCE_EXHAUSTION
WireId = Annotated[str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]


def _version_one(value: object) -> object:
    if type(value) is not int or value != 1:
        raise ValueError("Expected integer version 1")
    return value


def _utc_timestamp(value: object) -> object:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)", value) is None
    ):
        raise ValueError("Expected RFC3339 UTC timestamp")
    return value


class AllowanceExhaustion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    schema_version: Annotated[Literal[1], BeforeValidator(_version_one)]
    event_type: Literal["allowance_exhausted"]
    tenant_id: str = Field(min_length=1)
    region: str = Field(min_length=1)
    user_id: WireId
    allowance_id: WireId
    product_id: str = Field(min_length=1)
    metric_key: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    quantity: int = Field(strict=True, ge=0, le=2**53 - 1)
    occurred_at: Annotated[datetime, BeforeValidator(_utc_timestamp)]


def accept_exhaustion(factory: SessionFactory, consumer: BackendConsumer, event: AllowanceExhaustion) -> None:
    try:
        with factory() as db:
            require_current_policy(db, consumer)
            receive_exhaustion(db, consumer, event)
            db.commit()
    except (SQLAlchemyError, BackendPolicyConflict):
        raise BillingRefused("allowance_exhaustion_unavailable", 503) from None


def receive_exhaustion(db: Session, consumer: BackendConsumer, event: AllowanceExhaustion) -> None:
    if (event.tenant_id, event.region) != (
        consumer.tenant_id,
        consumer.region,
    ) or event.product_id not in consumer.allowed_products:
        raise BillingRefused("allowance_exhaustion_forbidden", 403)
    issued = db.execute(
        select(PurchasedAllowance, ExternalSubscription)
        .join(ExternalSubscription, ExternalSubscription.subscription_id == PurchasedAllowance.subscription_id)
        .join(User, User.id == ExternalSubscription.user_id)
        .where(
            PurchasedAllowance.allowance_id == UUID(event.allowance_id),
            User.id == UUID(event.user_id),
            User.tenant_id == event.tenant_id,
            User.region == event.region,
        )
    ).one_or_none()
    if issued is None:
        raise BillingRefused("allowance_binding_conflict", 409)
    allowance, _ = issued
    if allowance_ownership(allowance) != TechnicalOwnership(consumer.technical_source_id, consumer.consumer_id):
        raise BillingRefused("allowance_exhaustion_forbidden", 403)
    if (allowance.product_id, allowance.metric_key, allowance.unit, allowance.quantity) != (
        event.product_id,
        event.metric_key,
        event.unit,
        event.quantity,
    ):
        raise BillingRefused("allowance_binding_conflict", 409)
    # A conflict is a no-op even after completion. Ordinary coalescing would revive
    # completed work and replace the immutable first event (including occurred_at).
    db.execute(
        insert(BillingWorkItem)
        .values(
            work_item_id=uuid4(),
            work_kind=KIND,
            scope_kind=BillingWorkScope.ALLOWANCE,
            scope_reference=event.allowance_id,
            coalescing_key=f"{event.tenant_id}:{event.region}:{event.user_id}:{event.allowance_id}:{event.event_type}",
            payload_schema_version="allowance-exhaustion:v1",
            payload_document=event.model_dump(mode="json"),
            priority=1,
            next_attempt_at=as_utc(database_now(db)),
            work_state=BillingWorkState.PENDING,
            enqueue_generation=0,
            attempt_count=0,
        )
        .on_conflict_do_nothing(index_elements=["work_kind", "coalescing_key"], index_where=text(RECURRING_INDEX))
    )


def process_exhaustion(factory: SessionFactory, claim: WorkClaim) -> None:
    with factory() as db:
        # Locate before locking the queue; preserve User -> business -> queue order.
        initial = db.get(BillingWorkItem, claim.id)
        event = AllowanceExhaustion.model_validate(initial.payload_document)
        user = lock_user(db, UUID(event.user_id))
        state = paid_read.state(db, user.id, event.tenant_id, event.region)
        document = EffectiveState.model_validate(state.effective_state_document) if state else EffectiveState()
        if any(item.allowance_id == event.allowance_id for item in document.allowances):
            allowance = db.get(PurchasedAllowance, UUID(event.allowance_id))
            subscription = db.get(ExternalSubscription, allowance.subscription_id)
            # Only existing GET-only reconciliation is scheduled. Its normal provenance,
            # source configuration and claims still gate every external request.
            enroll_subscription(db, subscription, hint=True)
        row = verify_claim(db, claim)
        finish(db, row, claim, due=None)
        db.commit()
