"""Narrow Swagger agreement/subscription contracts and accepted-term proof.

No balance, credit or payment eligibility is inferred. Missing effective facts
are incomplete proof; mutable outer_id and catalog tariff_price are not identity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
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


def agreement_closed(point: Agreement) -> bool:
    if point.close_date in {None, "", "0000-00-00", "0000-00-00 00:00:00", "1970-01-01", "1970-01-01 00:00:00"}:
        return False
    try:
        if len(point.close_date) not in {10, 19}:
            raise ValueError("invalid calendar shape")
        datetime.fromisoformat(point.close_date)
    except ValueError:
        raise LbxResponseInvalid() from None
    return True


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
    agreement_closed(point)  # Calendar validity; terminal state is an admission decision.


def prove_subscription(
    point: Subscription,
    *,
    agreement_id: int,
    selection: ProductLinkRequest,
    offer: CurrentOffer,
) -> None:
    if point.agreement_id != agreement_id:
        raise LbxScopeMismatch()
    lifecycle = classify_lifecycle(point)
    if lifecycle.lifecycle is None:
        raise LbxResponseInvalid()
    prove_effective_terms(point, agreement_id=agreement_id, selection=selection, offer=offer)


@dataclass(frozen=True)
class MaterialInspection:
    """Incomplete interpretation and known differences are independent facts."""

    incomplete_fields: tuple[str, ...]
    differing_fields: tuple[str, ...]


def inspect_effective_terms(
    point: Subscription, *, selection: ProductLinkRequest, offer: CurrentOffer
) -> MaterialInspection:
    """Inspect every applicable material field without granting admission."""
    incomplete: list[str] = []
    differences: list[str] = []

    def compare(field: str, value: object, wanted: object) -> None:
        if value is None:
            incomplete.append(field)
        elif value != wanted:
            differences.append(field)

    for field, wanted in (
        ("tariff_id", selection.tariff_id),
        ("period_id", selection.period_id),
        ("period_length", offer.period.length),
        ("is_demo", False),
        ("is_offer_agrm", False),
        ("total_price", offer.money.recurring_amount),
    ):
        compare(field, getattr(point, field), wanted)
    if point.period_type not in {1, 2, 3, 4}:
        incomplete.append("period_type")
    else:
        compare("period_type", point.period_type, {"day": 1, "week": 2, "month": 3, "year": 4}[offer.period.unit])
    # Only the supported ruble aliases have established money meaning here.
    # An arbitrary symbol cannot prove another ISO currency.
    if point.currency_symbol is None or point.currency_symbol.casefold() not in {"rub", "руб", "₽"}:
        incomplete.append("currency_symbol")
    else:
        compare("currency", "RUB", offer.money.currency)
        compare("decimal_places", 2, offer.money.decimal_places)
    if point.services is None:
        incomplete.append("services")
    else:
        if len(point.services) != 1:
            differences.append("services")
        for index, service in enumerate(point.services):
            prefix = f"services[{index}]."
            for field, wanted in (
                ("tariff_service_id", selection.tariff_service_id),
                ("multiplicator", Decimal(selection.quantity)),
                ("price", offer.money.recurring_unit_amount),
                ("bulk_service", False),
            ):
                compare(prefix + field, getattr(service, field), wanted)
            if service.periodic_service not in {0, 1}:
                incomplete.append(prefix + "periodic_service")
            else:
                compare(prefix + "periodic_service", service.periodic_service, 1)
            # Swagger does not promise these fields for the supported zero
            # charges. A nonzero accepted connection charge needs explicit proof.
            if service.connection_price is not None or offer.money.connection_amount != 0:
                compare(prefix + "connection_price", service.connection_price, offer.money.connection_unit_amount)
            for field in ("bulk_price", "bulk_include_amount"):
                if getattr(service, field) not in {None, Decimal(0)}:
                    differences.append(prefix + field)
    return MaterialInspection(tuple(incomplete), tuple(differences))


def prove_effective_terms(
    point: Subscription, *, agreement_id: int, selection: ProductLinkRequest, offer: CurrentOffer
) -> None:
    """Strict purpose-specific admission; lifecycle/calendar are independent."""
    if point.agreement_id != agreement_id:
        raise LbxScopeMismatch()
    inspection = inspect_effective_terms(point, selection=selection, offer=offer)
    if inspection.incomplete_fields:
        raise LbxResponseInvalid()
    if inspection.differing_fields:
        raise LbxScopeMismatch()


@dataclass(frozen=True)
class LifecycleInspection:
    lifecycle: Lifecycle | None
    financial: Financial | None
    reason: str


def classify_lifecycle(point: Subscription) -> LifecycleInspection:
    """One interpretation for reconciliation, preparation and inventory."""
    states = {
        -2: (Lifecycle.INACTIVE, "waiting"),
        -1: (Lifecycle.INACTIVE, "inactive"),
        0: (Lifecycle.INACTIVE, "inactive"),
        2: (Lifecycle.ACTIVE, "active"),
        3: (Lifecycle.ENDED, "ended"),
    }
    blocks = {0: "active", 1: "financial_block", 3: "administrative_block"}
    if point.state not in states or point.current_blocking not in blocks:
        return LifecycleInspection(None, None, "lifecycle_unknown")
    lifecycle, reason = states[point.state]
    if lifecycle == Lifecycle.ACTIVE:
        return LifecycleInspection(
            lifecycle,
            Financial.ALLOWED if point.current_blocking == 0 else Financial.BLOCKED,
            blocks[point.current_blocking],
        )
    return LifecycleInspection(lifecycle, Financial.BLOCKED, reason)


def inventory_terminal(point: Subscription, agreement: Agreement) -> bool:
    lifecycle = classify_lifecycle(point)
    if lifecycle.lifecycle is None:
        raise LbxResponseInvalid()
    return lifecycle.lifecycle == Lifecycle.ENDED or agreement_closed(agreement)
