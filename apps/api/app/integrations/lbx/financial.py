"""Narrow Swagger agreement/subscription contracts and accepted-term proof.

No balance, credit or payment eligibility is inferred. Missing effective facts
are incomplete proof; mutable outer_id and catalog tariff_price are not identity.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator

from app.domains.catalog.product_link import CurrentOffer, ProductLinkRequest
from app.integrations.lbx.customer import PrivateDto
from app.integrations.lbx.dto import ExactNumber
from app.integrations.lbx.errors import LbxResponseInvalid, LbxScopeMismatch

Id = Annotated[int, Field(strict=True, gt=0)]


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
    if point.close_date not in {None, "", "0000-00-00", "0000-00-00 00:00:00", "1970-01-01", "1970-01-01 00:00:00"}:
        raise LbxScopeMismatch()


def prove_subscription(
    point: Subscription, *, agreement_id: int, selection: ProductLinkRequest, offer: CurrentOffer
) -> None:
    # Preparation deliberately excludes terminal subscriptions. Lifecycle reads
    # share the effective-term proof below without inheriting this restriction.
    if point.state is None or point.current_blocking is None:
        raise LbxResponseInvalid()
    if point.state not in {-2, -1, 0, 2} or point.current_blocking not in {0, 1, 3}:
        raise LbxScopeMismatch()
    prove_effective_terms(point, agreement_id=agreement_id, selection=selection, offer=offer)


def prove_effective_terms(
    point: Subscription, *, agreement_id: int, selection: ProductLinkRequest, offer: CurrentOffer
) -> None:
    """Compare accepted effective terms, independently of lifecycle/calendar."""
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
    if any(value is None for value in required):
        raise LbxResponseInvalid()
    if len(point.services) == 1 and any(
        value is None
        for value in (
            point.services[0].multiplicator,
            point.services[0].price,
            point.services[0].periodic_service,
            point.services[0].bulk_service,
        )
    ):
        raise LbxResponseInvalid()
    if (
        point.agreement_id != agreement_id
        or point.tariff_id != selection.tariff_id
        or point.period_id != selection.period_id
    ):
        raise LbxScopeMismatch()
    if (point.period_type, point.period_length) != (
        {"day": 1, "week": 2, "month": 3, "year": 4}[offer.period.unit],
        offer.period.length,
    ):
        raise LbxScopeMismatch()
    if point.is_demo or point.is_offer_agrm:
        raise LbxScopeMismatch()
    if (
        offer.money.currency != "RUB"
        or point.currency_symbol.casefold() not in {"rub", "руб", "₽"}
        or point.total_price != offer.money.recurring_amount
    ):
        raise LbxScopeMismatch()
    if len(point.services) != 1:
        raise LbxScopeMismatch()
    service = point.services[0]
    if (
        service.tariff_service_id != selection.tariff_service_id
        or service.multiplicator != Decimal(selection.quantity)
        or service.price != offer.money.recurring_unit_amount
        or service.bulk_price not in {None, Decimal(0)}
        or service.bulk_include_amount not in {None, Decimal(0)}
        or service.periodic_service != 1
        or service.bulk_service
    ):
        raise LbxScopeMismatch()
    # Swagger's effective service projection does not promise connection_price.
    # A nonzero accepted connection charge needs explicit effective evidence.
    if service.connection_price is None and offer.money.connection_amount != 0:
        raise LbxResponseInvalid()
    if service.connection_price is not None and service.connection_price != offer.money.connection_unit_amount:
        raise LbxScopeMismatch()
