"""Synthetic authoritative proof shapes; no real source or legal approval."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.reconciliation_contracts import ReconciliationSubject
from app.domains.catalog.commercial_offer import (
    CommercialEvidenceMode,
    CommercialMoney,
    CommercialPeriod,
    CommercialQuantity,
)
from app.domains.catalog.product_link import CurrentOffer
from app.domains.purchases.contracts import AcceptedPurchase, Purchase, PurchaseMeaning
from app.integrations.lbx.customer import LbxUser
from app.integrations.lbx.dto import LbxRead, LbxTariff
from app.integrations.lbx.financial import Agreement, Subscription
from app.models import PurchaseIntentState
from apps.api.tests.support.any709_step1 import link_selection, step1_settings


def subject_factory() -> ReconciliationSubject:
    config = step1_settings()
    now = datetime.now(UTC)
    selection = link_selection()
    fingerprint = "sha256:" + "1" * 64
    offer = CurrentOffer(
        CommercialMoney("RUB", 2, Decimal(100), Decimal(0), Decimal(100), Decimal(0)),
        CommercialPeriod("month", 1, "instance_start", date(2026, 1, 1), None),
        CommercialQuantity("commercial_service", Decimal(1), 1, 1),
        701,
        1001,
        901,
        801,
        1101,
        True,
        True,
        30,
        CommercialEvidenceMode.CONFIGURED_SOURCE,
        now,
        fingerprint,
    )
    accepted = AcceptedPurchase(
        meaning=PurchaseMeaning(
            product_id=selection.product_id, revision_id=uuid4(), expected_fingerprint=fingerprint, documents=()
        ),
        selection=selection,
        offer=offer,
        documents=(),
        provider_origin=config.lbx_provider_origin,
        seller_id=21,
    )
    customer_id = uuid4()
    purchase = Purchase(
        uuid4(),
        uuid4(),
        customer_id,
        config.lbx_external_billing_account_id,
        PurchaseIntentState.LINKED,
        accepted,
        now,
        True,
        (),
    )
    return ReconciliationSubject(
        uuid4(),
        purchase,
        CustomerOpen(customer_id, uuid4(), uuid4(), "portal-test", "345"),
        "456",
        "portal-agreement",
        "567",
        str(uuid4()),
        1,
        now + timedelta(minutes=2),
        now,
    )


def user_factory() -> LbxUser:
    return LbxUser(user_id=345, outer_id="portal-test")


def agreement_factory() -> Agreement:
    return Agreement(
        agreement_id=456, user_id=345, organization_id=21, agreement_number="portal-agreement", is_offer=False
    )


def tariff_factory(subject: ReconciliationSubject) -> LbxRead[LbxTariff]:
    return LbxRead(
        subject.purchase.account_id,
        701,
        None,
        datetime.now(UTC),
        LbxTariff(
            tariff_id=701,
            currency_id=1,
            balance_blocks=1,
            payment_type=0,
            dynamic_rent=0,
            dynamic_rent_unblock_type=0,
            demo_period_length=0,
            proportional_rent=0,
            float_period=1,
        ),
    )


def subscription_factory() -> Subscription:
    return Subscription.model_validate(
        {
            "subscription_id": 567,
            "agreement_id": 456,
            "tariff_id": 701,
            "period_id": 901,
            "period_type": 3,
            "period_length": 1,
            "state": 2,
            "current_blocking": 0,
            "is_demo": False,
            "is_offer_agrm": False,
            "currency_symbol": "руб",
            "total_price": 100,
            "last_tariffication_period_start": "2026-10-01",
            "last_tariffication_period_end": "2026-11-01",
            "services": [
                {
                    "tariff_service_id": 1001,
                    "multiplicator": 1,
                    "price": 100,
                    "periodic_service": 1,
                    "bulk_service": False,
                }
            ],
        }
    )
