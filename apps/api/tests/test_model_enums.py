from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session
from sqlalchemy.types import Enum as SqlAlchemyEnum
from sqlalchemy.types import Text

import app.models as models
import app.models.enums as model_enums
from app.core.database import Base
from app.models import (
    AcceptanceKind,
    LegalEntityStatus,
    LegalEntityType,
    MagicLinkPurpose,
    Region,
    RegionStatus,
    UserStatus,
)
from app.models._shared import PersistedEnumType


def _values(enum_cls: type) -> set[str]:
    return {member.value for member in enum_cls}


def test_canonical_enum_layer_contains_only_retained_vocabularies() -> None:
    assert _values(RegionStatus) == {"active"}
    assert _values(UserStatus) == {"active"}
    assert _values(MagicLinkPurpose) == {"password_reset"}
    assert _values(LegalEntityStatus) == {"active"}
    assert _values(LegalEntityType) == {
        "individual_entrepreneur",
        "merchant_of_record",
        "company",
    }
    assert _values(AcceptanceKind) == {
        "privacy_consent",
        "terms_acceptance",
        "recurring_consent",
        "cookies",
    }
    assert set(model_enums.__all__) == {
        "AcceptanceKind",
        "LegalEntityStatus",
        "LegalEntityType",
        "MagicLinkPurpose",
        "RegionStatus",
        "UserStatus",
    }


def test_legacy_commercial_models_and_enums_are_not_public() -> None:
    removed_symbols = {
        "Product",
        "Plan",
        "Order",
        "Payment",
        "Subscription",
        "Entitlement",
        "EntrypointSession",
        "PaymentProviderAccount",
        "PaymentStatus",
        "SubscriptionStatus",
    }

    assert removed_symbols.isdisjoint(models.__all__)
    assert removed_symbols.isdisjoint(model_enums.__all__)


def test_user_status_vocabulary_requires_explicit_auth_semantics() -> None:
    assert _values(UserStatus) == {"active"}


def test_persisted_enum_type_validates_and_serializes_values() -> None:
    enum_type = PersistedEnumType(RegionStatus)

    assert enum_type.process_bind_param(RegionStatus.ACTIVE, None) == "active"
    assert enum_type.process_bind_param(None, None) is None
    assert enum_type.process_result_value("active", None) is RegionStatus.ACTIVE
    assert enum_type.process_result_value(None, None) is None

    with pytest.raises(TypeError):
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


def test_persisted_enum_type_rejects_plain_strings() -> None:
    enum_type = PersistedEnumType(RegionStatus)

    with pytest.raises(TypeError, match="expected RegionStatus or None, got str"):
        enum_type.process_bind_param("active", None)


def test_enum_backed_orm_round_trip_and_rejects_plain_string_binding() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        region = Region(
            code="ru",
            name="Russia",
            residency_zone="ru",
            default_currency="RUB",
            default_locale="ru-RU",
            status=RegionStatus.ACTIVE,
        )
        session.add(region)
        session.commit()
        session.expire_all()

        assert session.get(Region, "ru").status is RegionStatus.ACTIVE

        invalid_region = Region(
            code="invalid",
            name="Invalid",
            residency_zone="invalid",
            default_currency="INV",
            default_locale="invalid",
            status="not-a-status",
        )
        session.add(invalid_region)
        with pytest.raises(StatementError, match="expected RegionStatus or None, got str"):
            session.commit()
