from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session
from sqlalchemy.types import Enum as SqlAlchemyEnum
from sqlalchemy.types import Text

from app.core.database import Base
from app.domains.billing.enums import (
    EntitlementStatus as LegacyEntitlementStatus,
    PaymentStatus as LegacyPaymentStatus,
    SubscriptionRenewalMode as LegacySubscriptionRenewalMode,
    SubscriptionScopeType as LegacySubscriptionScopeType,
    SubscriptionStatus as LegacySubscriptionStatus,
    WebhookEventStatus,
)
from app.domains.legal.enums import AcceptanceKind as LegacyAcceptanceKind
from app.models import (
    AcceptanceKind,
    CheckoutSessionStatus,
    EntitlementStatus,
    OrderStatus,
    PaymentStatus,
    PaymentWebhookEvent,
    PaymentWebhookEventStatus,
    SubscriptionEvent,
    SubscriptionEventType,
    SubscriptionRenewalMode,
    SubscriptionScopeType,
    SubscriptionStatus,
)
from app.models._shared import PersistedEnumType
from app.models.commerce import EntrypointSession, Order
from app.models.enums import (
    BillingPeriod,
    BundleProductStatus,
    BundleStatus,
    LegalEntityStatus,
    LegalEntityType,
    MagicLinkPurpose,
    PlanLimitOveragePolicy,
    PlanLimitResetPolicy,
    PlanPriceComponentType,
    PlanStatus,
    ProductStatus,
    RefundStatus,
    RegionStatus,
    UserStatus,
)


def _values(enum_cls: type) -> set[str]:
    return {member.value for member in enum_cls}


def test_critical_persisted_enum_value_sets() -> None:
    assert _values(OrderStatus) == {
        "created",
        "requires_consents",
        "pending_payment",
        "paid",
        "payment_failed",
        "canceled",
        "expired",
        "refunded",
        "partially_refunded",
        "region_mismatch",
    }
    assert _values(PaymentStatus) == {
        "created",
        "requires_action",
        "authorized",
        "captured",
        "succeeded",
        "failed",
        "canceled",
        "refunded",
        "partially_refunded",
        "disputed",
    }
    assert _values(PaymentWebhookEventStatus) == {
        "received",
        "processing",
        "processed",
        "ignored",
        "duplicate",
        "failed",
    }
    assert _values(CheckoutSessionStatus) == {"created", "order_created"}
    assert _values(RefundStatus) == {"requested", "succeeded"}
    assert _values(SubscriptionScopeType) == {"product", "bundle", "all_access"}
    assert _values(SubscriptionRenewalMode) == {"manual", "automatic"}


def test_canonical_enum_layer_contains_locked_model_vocabularies() -> None:
    assert _values(ProductStatus) == {"active", "inactive"}
    assert _values(BundleStatus) == {"active", "inactive"}
    assert _values(BundleProductStatus) == {"active"}
    assert _values(PlanStatus) == {"active", "inactive"}
    assert _values(BillingPeriod) == {
        "day",
        "days",
        "week",
        "weeks",
        "month",
        "months",
        "year",
        "years",
        "annual",
        "yearly",
    }
    assert _values(PlanPriceComponentType) == {"product_plan"}
    assert _values(PlanLimitResetPolicy) == {"billing_period"}
    assert _values(PlanLimitOveragePolicy) == {"deny"}
    assert _values(EntitlementStatus) == {"active", "expired", "revoked", "superseded"}
    assert _values(RegionStatus) == {"active"}
    assert _values(UserStatus) == {"active"}
    assert _values(MagicLinkPurpose) == {"password_reset"}
    assert _values(LegalEntityStatus) == {"active"}
    assert _values(LegalEntityType) == {"individual_entrepreneur", "merchant_of_record", "company"}
    assert _values(AcceptanceKind) == {"privacy_consent", "terms_acceptance", "recurring_consent", "cookies"}
    assert _values(SubscriptionEventType) == {
        "trial_started",
        "paid_period_activated",
        "subscription_replaced",
        "automatic_renewal_enabled",
        "renewal_succeeded",
        "renewal_failed",
        "provider_subscription_state_applied",
        "cancellation_requested",
        "refund_applied",
        "partial_refund_applied",
        "subscription_expired",
    }


def test_subscription_status_live_values_are_preserved() -> None:
    assert SubscriptionStatus.live_values() == ("trialing", "active", "past_due", "paused")
    assert SubscriptionStatus.CANCELED.is_live is False


def test_compatibility_exports_reference_canonical_classes() -> None:
    assert LegacyEntitlementStatus is EntitlementStatus
    assert LegacyPaymentStatus is PaymentStatus
    assert LegacySubscriptionRenewalMode is SubscriptionRenewalMode
    assert LegacySubscriptionScopeType is SubscriptionScopeType
    assert LegacySubscriptionStatus is SubscriptionStatus
    assert WebhookEventStatus is PaymentWebhookEventStatus
    assert LegacyAcceptanceKind is AcceptanceKind


def test_persisted_enum_type_validates_and_serializes_values() -> None:
    enum_type = PersistedEnumType(PaymentStatus)

    assert enum_type.process_bind_param(PaymentStatus.SUCCEEDED, None) == "succeeded"
    assert enum_type.process_bind_param("succeeded", None) == "succeeded"
    assert enum_type.process_bind_param(None, None) is None
    assert enum_type.process_result_value("succeeded", None) is PaymentStatus.SUCCEEDED
    assert enum_type.process_result_value(None, None) is None

    with pytest.raises(ValueError):
        enum_type.process_bind_param("unknown", None)
    with pytest.raises(ValueError):
        enum_type.process_result_value("unknown", None)


def test_enum_backed_columns_use_text_storage() -> None:
    enum_columns = [
        column
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, PersistedEnumType)
    ]

    assert enum_columns
    assert all(isinstance(column.type.impl, Text) for column in enum_columns)
    assert all(not isinstance(column.type, SqlAlchemyEnum) for column in enum_columns)


def test_region_mismatch_statuses_remain_plain_text() -> None:
    assert isinstance(EntrypointSession.__table__.c.region_mismatch_status.type, Text)
    assert isinstance(Order.__table__.c.region_mismatch_status.type, Text)
    assert not isinstance(EntrypointSession.__table__.c.region_mismatch_status.type, PersistedEnumType)
    assert not isinstance(Order.__table__.c.region_mismatch_status.type, PersistedEnumType)


def test_public_openapi_enum_names_remain_stable() -> None:
    assert SubscriptionScopeType.__name__ == "SubscriptionScopeType"
    assert SubscriptionRenewalMode.__name__ == "SubscriptionRenewalMode"


def test_enum_backed_orm_round_trip_and_staged_string_binding() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        event = PaymentWebhookEvent(
            id=uuid.uuid4(),
            tenant_id="anytoolai",
            region="ru",
            provider="test",
            endpoint="pay",
            payload_hash="hash",
            raw_payload={},
            status=PaymentWebhookEventStatus.PROCESSED,
        )
        string_event = PaymentWebhookEvent(
            id=uuid.uuid4(),
            tenant_id="anytoolai",
            region="ru",
            provider="test",
            endpoint="pay",
            payload_hash="hash-2",
            raw_payload={},
            status="received",
        )
        session.add_all([event, string_event])
        session.commit()
        session.expire_all()

        assert session.get(PaymentWebhookEvent, event.id).status is PaymentWebhookEventStatus.PROCESSED
        assert session.get(PaymentWebhookEvent, string_event.id).status is PaymentWebhookEventStatus.RECEIVED

        invalid_event = PaymentWebhookEvent(
            id=uuid.uuid4(),
            tenant_id="anytoolai",
            region="ru",
            provider="test",
            endpoint="pay",
            payload_hash="hash-3",
            raw_payload={},
            status="not-a-status",
        )
        session.add(invalid_event)
        with pytest.raises(StatementError):
            session.commit()


def test_nullable_subscription_event_status_round_trip() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        event = SubscriptionEvent(
            id=uuid.uuid4(),
            subscription_id=uuid.uuid4(),
            event_type=SubscriptionEventType.TRIAL_STARTED,
            previous_status=None,
            next_status=SubscriptionStatus.TRIALING,
            occurred_at=datetime.now(timezone.utc),
            operation_idempotency_key="enum-round-trip",
        )
        session.add(event)
        session.commit()
        session.expire_all()

        loaded = session.get(SubscriptionEvent, event.id)
        assert loaded.previous_status is None
        assert loaded.next_status is SubscriptionStatus.TRIALING
