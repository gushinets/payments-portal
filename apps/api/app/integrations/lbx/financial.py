"""Narrow Swagger agreement/subscription contracts and accepted-term proof.

No balance, credit or payment eligibility is inferred. Missing effective facts
are incomplete proof; mutable outer_id and catalog tariff_price are not identity.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator

from app.domains.catalog.product_link import CurrentOffer, ProductLinkRequest
from app.integrations.lbx.customer import PrivateDto
from app.integrations.lbx.dto import ExactNumber
from app.integrations.lbx.errors import LbxResponseInvalid, LbxScopeMismatch
from app.models import (
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
)

Id = Annotated[int, Field(strict=True, gt=0)]
EMPTY_CALENDAR = {None, "", "0000-00-00", "0000-00-00 00:00:00", "1970-01-01", "1970-01-01 00:00:00"}


class Agreement(PrivateDto):
    agreement_id: Id
    user_id: Id
    organization_id: Id | None = None
    agreement_number: str | None = None
    is_offer: bool | None = None
    create_date: str | None = None
    close_date: str | None = None
    agreement_link: str | None = None


class SubscriptionService(PrivateDto):
    tariff_service_id: Id
    multiplicator: ExactNumber | None = None
    price: ExactNumber | None = None
    connection_price: ExactNumber | None = None
    bulk_price: ExactNumber | None = None
    bulk_include_amount: ExactNumber | None = None
    periodic_service: int | None = None
    bulk_service: bool | None = None


class Subscription(PrivateDto):
    subscription_id: Id
    agreement_id: Id
    tariff_id: Id
    period_id: Id | None = None
    period_type: int | None = None
    period_length: int | None = None
    state: int | None = None
    current_blocking: int | None = None
    is_demo: bool | None = None
    is_offer_agrm: bool | None = None
    currency_symbol: str | None = None
    total_price: ExactNumber | None = None
    services: list[SubscriptionService] | None = None
    subscription_start_date: str | None = None
    subscription_end_date: str | None = None
    subscription_instance_start_date: str | None = None
    subscription_instance_end_date: str | None = None
    last_tariffication_period_start: str | None = None
    last_tariffication_period_end: str | None = None

    @field_validator(
        "subscription_start_date",
        "subscription_end_date",
        "subscription_instance_start_date",
        "subscription_instance_end_date",
        "last_tariffication_period_start",
        "last_tariffication_period_end",
    )
    @classmethod
    def provider_calendar(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?: [0-9]{2}:[0-9]{2}:[0-9]{2})?", value):
            raise ValueError("invalid provider calendar evidence")
        return value


class AgreementReceipt(PrivateDto):
    agreement_id: Id


class SubscriptionReceipt(PrivateDto):
    subscription_id: Id


class AgreementCreated(PrivateDto):
    code: Literal[200, 201]
    response: AgreementReceipt


class SubscriptionCreated(PrivateDto):
    code: Literal[200, 201]
    response: SubscriptionReceipt


class NewAgreement(PrivateDto):
    user_id: Id
    organization_id: Id
    agreement_number: str
    create_date: date
    is_offer: Literal[False] = False

    def request_document(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class NewSubscription(PrivateDto):
    agreement_id: Id
    tariff_id: Id
    period_id: Id
    tariff_service_id: Id
    quantity: Id
    outer_id: str

    def request_document(self) -> dict[str, Any]:
        return {
            "agreement_id": self.agreement_id,
            "tariff_id": self.tariff_id,
            "period_id": self.period_id,
            "outer_id": self.outer_id,
            "activate_by_balance": True,
            "activate_manually": False,
            "demo_period_length": 0,
            "services": [{"tariff_service_id": self.tariff_service_id, "multiplicator": self.quantity}],
        }


def prove_agreement(point: Agreement, *, user_id: int, seller_id: int, number: str) -> None:
    if point.organization_id is None or point.agreement_number is None or point.is_offer is None:
        raise LbxResponseInvalid()
    if (point.user_id, point.organization_id, point.agreement_number, point.is_offer) != (
        user_id,
        seller_id,
        number,
        False,
    ):
        raise LbxScopeMismatch()


def agreement_is_closed(point: Agreement) -> bool:
    """Validate calendar evidence without assigning a timezone or an instant."""
    if point.close_date in EMPTY_CALENDAR:
        return False
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?: [0-9]{2}:[0-9]{2}:[0-9]{2})?", point.close_date):
        raise LbxResponseInvalid()
    try:
        datetime.fromisoformat(point.close_date)
    except ValueError:
        raise LbxResponseInvalid() from None
    return True


def subscription_lifecycle(point: Subscription) -> tuple[Lifecycle, Financial, str]:
    """Recognized canonical states; unknown codes never prove a negative."""
    states = {
        (-2, 0): (Lifecycle.INACTIVE, Financial.BLOCKED, "waiting"),
        (-1, 0): (Lifecycle.INACTIVE, Financial.BLOCKED, "inactive"),
        (0, 0): (Lifecycle.INACTIVE, Financial.BLOCKED, "inactive"),
        (2, 0): (Lifecycle.ACTIVE, Financial.ALLOWED, "active"),
        (2, 1): (Lifecycle.ACTIVE, Financial.BLOCKED, "financial_block"),
        (2, 3): (Lifecycle.ACTIVE, Financial.BLOCKED, "administrative_block"),
        (3, 0): (Lifecycle.ENDED, Financial.BLOCKED, "ended"),
        (3, 1): (Lifecycle.ENDED, Financial.BLOCKED, "ended"),
        (3, 3): (Lifecycle.ENDED, Financial.BLOCKED, "ended"),
    }
    result = states.get((point.state, point.current_blocking))
    if result is None:
        raise LbxResponseInvalid()
    return result


def require_preparable_agreement(point: Agreement) -> None:
    if agreement_is_closed(point):
        raise LbxResponseInvalid()


def require_payable_subscription(point: Subscription) -> None:
    if subscription_lifecycle(point)[0] == Lifecycle.ENDED:
        raise LbxResponseInvalid()


def prove_subscription(
    point: Subscription, *, agreement_id: int, selection: ProductLinkRequest, offer: CurrentOffer
) -> None:
    """Original effective-term proof is independent of current payability."""
    prove_effective_terms(point, agreement_id=agreement_id, selection=selection, offer=offer)


def prove_effective_terms(
    point: Subscription, *, agreement_id: int, selection: ProductLinkRequest, offer: CurrentOffer
) -> None:
    """Compare accepted effective terms, independently of lifecycle/calendar."""
    # Relationship contradictions are independent of commercial completeness.
    if point.agreement_id != agreement_id:
        raise LbxScopeMismatch()
    expected = (
        (point.agreement_id, agreement_id),
        (point.tariff_id, selection.tariff_id),
        (point.period_id, selection.period_id),
        (point.period_type, {"day": 1, "week": 2, "month": 3, "year": 4}[offer.period.unit]),
        (point.period_length, offer.period.length),
        (point.is_demo, False),
        (point.is_offer_agrm, False),
        (point.total_price, offer.money.recurring_amount),
    )
    required = (
        point.period_id,
        point.period_type,
        point.period_length,
        point.is_demo,
        point.is_offer_agrm,
        point.currency_symbol,
        point.total_price,
        point.services,
    )
    for service in point.services or ():
        required += (service.multiplicator, service.price, service.periodic_service, service.bulk_service)
        # Zero accepted connection charges need no unrelated optional field.
        if offer.money.connection_amount != 0:
            required += (service.connection_price,)
    if any(value is None for value in required):
        raise LbxResponseInvalid()
    # A known difference becomes COMPLETE_MISMATCH only after full material
    # reconstruction. Current catalog prices never substitute for these facts.
    if any(value != wanted for value, wanted in expected):
        raise LbxScopeMismatch()
    if offer.money.currency != "RUB" or point.currency_symbol.casefold() not in {"rub", "руб", "₽"}:
        raise LbxScopeMismatch()
    if len(point.services) != 1:
        raise LbxScopeMismatch()
    service = point.services[0]
    expected_service = (
        (service.tariff_service_id, selection.tariff_service_id),
        (service.multiplicator, Decimal(selection.quantity)),
        (service.price, offer.money.recurring_unit_amount),
        (service.periodic_service, 1),
        (service.bulk_service, False),
        (service.connection_price, offer.money.connection_unit_amount),
    )
    if (
        any(value is not None and value != wanted for value, wanted in expected_service)
        or service.bulk_price not in {None, Decimal(0)}
        or service.bulk_include_amount not in {None, Decimal(0)}
    ):
        raise LbxScopeMismatch()


def inventory_terminal(point: Subscription) -> bool:
    return subscription_lifecycle(point)[0] == Lifecycle.ENDED
