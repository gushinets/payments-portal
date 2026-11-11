"""Populated immutable history and synthetic non-Kernel purchases on real PostgreSQL."""

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import time
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition import purchases
from app.composition.catalog import catalog_preview
from app.composition.mapping_operator import fresh_link_evaluation
from app.composition.sources import TechnicalSourceRefused, source_resources
from app.domains.billing.paid_allowances import materialize_allowance
from app.domains.billing.paid_cycles import CalendarEvidence
from app.domains.billing.paid_policy import MeteringPolicy
from app.domains.catalog.commercial_offer import CommercialScope, canonical_document, commercial_digest
from app.domains.catalog.link_publication import publish_product_link, validate_product_link
from app.domains.catalog.mapping_evidence import MappingRefused
from app.domains.catalog.product_link import ProductLinkDocument
from app.domains.purchases.contracts import AcceptedPurchase
from app.domains.purchases.router import present_purchase
from app.models import (
    CommercialMappingRevision,
    ExternalBillingCustomer,
    ExternalSubscription,
    LegalAcceptanceEvent,
    PurchasedAllowance,
    PurchaseIntent,
    PurchaseIntentState,
    ExternalSubscriptionLifecycleStatus,
    ExternalSubscriptionFinancialAccessStatus,
    ExternalSubscriptionCommercialAccessStatus,
)
from apps.api.tests.factories.paid_access import reader_identity
from apps.api.tests.factories.purchase_terms import reviewed_meaning
from apps.api.tests.support.any709_step1 import link_selection
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.support.backend_consumers import backend_consumer, second_consumer
from apps.api.tests.test_any709_step2_postgres import TOKEN, seed
from apps.api.tests.test_any766_technical_sources import source_settings, summary_manifest, summary_offer

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
HISTORY = json.loads(
    (
        Path(__file__).resolve().parents[3] / "docs/contracts/portal-kernel-paid/fixtures/backend-history.json"
    ).read_text()
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def fixed_billing_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, tzinfo=UTC))


def cycle() -> CalendarEvidence:
    return CalendarEvidence(precision="date", start="2026-10-31", end="2026-11-29", anchor="2026-01-31")


@pytest.mark.parametrize("case", [row for row in HISTORY if row["kind"] == "purchase"], ids=lambda row: row["name"])
async def test_populated_old_links_consent_terms_and_allowances_are_never_converted(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    case: dict[str, object],
) -> None:
    factory = postgres_session_factory
    raw = json.loads(case["serialized"])
    accepted = AcceptedPurchase.model_validate(raw)
    assert canonical_document(accepted.model_dump(mode="json")) == case["serialized"]
    account = accepted.technical_terms.account_id if accepted.technical_terms else "synthetic-account"
    legacy_link = json.loads(
        next(
            row["serialized"]
            for row in HISTORY
            if row["name"]
            == (
                "configured-product-link-v3"
                if accepted.schema_version == "accepted-purchase:v3"
                else "legacy-product-link-v2"
            )
        )
    )
    # Set publication bookkeeping before seeding; it is outside identity_json.
    legacy_link["scope"]["external_billing_account_id"] = account
    legacy_link["product_revision_number"] = 1
    unchecked = ProductLinkDocument.model_validate_json(
        next(
            row["serialized"]
            for row in HISTORY
            if row["name"]
            == (
                "configured-product-link-v3"
                if accepted.schema_version == "accepted-purchase:v3"
                else "legacy-product-link-v2"
            )
        )
    )
    # A separate legacy simulated account needs its original identity hash.
    unchecked = unchecked.model_copy(update={"scope": CommercialScope("anytoolai", "ru", account)})
    legacy_link["identity_digest"] = commercial_digest(unchecked.identity_json())
    link = ProductLinkDocument.model_validate_json(json.dumps(legacy_link))
    user, auth = reader_identity(TOKEN)
    customer_id, purchase_id, event_id, subscription_id = (uuid4() for _ in range(4))
    seeded_allowance_id = uuid4()
    revision_id = accepted.meaning.revision_id
    now = datetime.now(UTC)
    with factory() as db:
        db.add(user)
        db.flush()
        db.add_all(
            [
                auth,
                ExternalBillingCustomer(
                    customer_id=customer_id,
                    user_id=user.id,
                    external_billing_account_id=account,
                    billing_customer_key="synthetic-history-customer",
                ),
                CommercialMappingRevision(
                    mapping_revision_id=revision_id,
                    external_billing_account_id=account,
                    billing_offer_id=accepted.selection.billing_offer_id,
                    revision_number=1,
                    manifest_version=link.manifest_version,
                    catalog_digest=link.identity_digest,
                    mapping_schema_version=link.schema_version,
                    mapping_document=legacy_link,
                    published_at=link.published_at,
                    published_by_principal=link.publisher_principal,
                ),
                LegalAcceptanceEvent(
                    id=event_id,
                    tenant_id="anytoolai",
                    region="ru",
                    user_id=user.id,
                    external_billing_account_id=account,
                    billing_offer_id=accepted.selection.billing_offer_id,
                    accepted_commercial_fingerprint=accepted.offer.fingerprint,
                ),
            ]
        )
        db.flush()
        db.add(
            PurchaseIntent(
                purchase_intent_id=purchase_id,
                user_id=user.id,
                customer_id=customer_id,
                external_billing_account_id=account,
                product_id="proposal_ai",
                billing_offer_id=accepted.selection.billing_offer_id,
                mapping_revision_id=revision_id,
                accepted_commercial_fingerprint=accepted.offer.fingerprint,
                client_idempotency_key="frozen-history",
                state=PurchaseIntentState.LINKED,
                accepted_snapshot_schema_version=accepted.schema_version,
                accepted_snapshot=raw,
                legal_acceptance_event_id=event_id,
            )
        )
        db.flush()
        sub = ExternalSubscription(
            subscription_id=subscription_id,
            user_id=user.id,
            customer_id=customer_id,
            external_billing_account_id=account,
            product_id="proposal_ai",
            purchase_intent_id=purchase_id,
            mapping_revision_id=revision_id,
            lifecycle_status=ExternalSubscriptionLifecycleStatus.ACTIVE,
            financial_access_status=ExternalSubscriptionFinancialAccessStatus.ALLOWED,
            commercial_access_status=ExternalSubscriptionCommercialAccessStatus.ELIGIBLE,
            last_authoritative_read_at=now,
            projection_valid_until=now + timedelta(hours=1),
        )
        db.add(sub)
        db.flush()
        if accepted.technical_terms is not None:
            technical = accepted.technical_terms
            db.add(
                PurchasedAllowance(
                    allowance_id=seeded_allowance_id,
                    subscription_id=subscription_id,
                    source_component_id=str(accepted.selection.tariff_service_id),
                    product_id="proposal_ai",
                    metric_key=technical.offer.metric_key,
                    unit=technical.offer.unit,
                    quantity=technical.offer.quantity,
                    provider_cycle_key="date:2026-10-31:2026-11-29",
                    cycle_schema_version="calendar:v1",
                    cycle_date_start=date(2026, 10, 31),
                    cycle_date_end=date(2026, 11, 29),
                    calendar_document=cycle().model_dump(mode="json"),
                    terms_document={"technical_terms": raw["technical_terms"], "period": raw["offer"]["period"]},
                )
            )
            db.flush()
        assert validate_product_link(db.get(CommercialMappingRevision, revision_id), scope=link.scope).document == link
        first = materialize_allowance(db, sub, accepted, cycle(), skew_seconds=10)
        if first is not None:
            assert first.allowance_id == str(seeded_allowance_id)
        db.commit()
    with factory() as db:
        baseline_terms = deepcopy(db.get(PurchasedAllowance, first.allowance_id).terms_document) if first else None
    # Reconfigured source ownership cannot change original replay or local allowance derivation.
    config = source_settings(backend_consumers=(second_consumer(allowed_products=["proposal_ai"]),))
    replay = await purchases.confirm_purchase(
        object(), config, factory=factory, token=TOKEN, key="frozen-history", meaning=accepted.meaning
    )
    assert replay.accepted.model_dump(mode="json") == raw
    assert (
        present_purchase(replay).accepted.expected_technical_terms_digest
        == accepted.meaning.expected_technical_terms_digest
    )
    with factory() as db:
        sub = db.get(ExternalSubscription, subscription_id)
        restored = materialize_allowance(db, sub, replay.accepted, cycle(), skew_seconds=20)
        later = materialize_allowance(
            db,
            sub,
            replay.accepted,
            cycle().model_copy(update={"start": "2026-11-30", "end": "2026-12-30"}),
            skew_seconds=10,
        )
        assert restored == first
        if first:
            assert restored.allowance_id == first.allowance_id and later.quantity == first.quantity == 100
            assert later.allowance_id != first.allowance_id
            assert db.get(PurchasedAllowance, first.allowance_id).terms_document == baseline_terms
            assert replay.accepted.technical_terms.ownership.backend_consumer_id == "platform-kernel"
            if accepted.technical_terms.provenance == "SIMULATED":
                assert not MeteringPolicy.for_environment("production").permits(accepted.technical_terms.provenance)
        else:
            assert later is None  # No inferred V1 quantity.
        db.commit()
    with factory() as db:
        saved = db.get(PurchaseIntent, purchase_id)
        assert canonical_document(saved.accepted_snapshot) == case["serialized"]
        assert hashlib.sha256(canonical_document(saved.accepted_snapshot).encode()).hexdigest() == case["sha256"]
        assert db.get(CommercialMappingRevision, revision_id).mapping_document == legacy_link


async def test_non_kernel_publication_purchase_send_replay_and_renewal_keep_owner_and_quantity(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    factory = postgres_session_factory
    seed(factory)
    config = source_settings()
    transport = PurchaseTransport()
    transport.pool = migrated_database.pool
    seen = []

    def manifest(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        assert request.url.host == "summary.example.test"
        return httpx.Response(200, json=summary_manifest())

    fresh = await fresh_link_evaluation(
        config,
        selection=link_selection(product_id="synthetic_summary"),
        technical_offer=summary_offer(),
        principal="os-euid:29001",
        kernel_transport=httpx.MockTransport(manifest),
        lbx_transport=httpx.MockTransport(transport.respond),
    )
    link = publish_product_link(
        factory,
        evaluation=fresh.document,
        expected_previous_revision=0,
        deadline=fresh.deadline,
        lock_timeout_seconds=1,
        provider_origin=config.lbx_provider_origin,
    ).stored
    async with source_resources(
        config, kernel_transport=httpx.MockTransport(manifest), lbx_transport=httpx.MockTransport(transport.respond)
    ) as sources:
        selected, offer, documents, terms = await purchases.review_purchase(
            sources, config, factory=factory, token=TOKEN, product_id="synthetic_summary"
        )
        purchase = await purchases.confirm_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            key="summary",
            meaning=reviewed_meaning(
                "synthetic_summary", selected.mapping_revision_id, offer.fingerprint, documents, terms
            ),
        )
        assert purchase.accepted.schema_version == "accepted-purchase:v4"
        assert terms.ownership == link.document.ownership
        assert terms.ownership.backend_consumer_id == "synthetic-summary"
        linked = await purchases.advance_purchase(
            sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id
        )
        assert linked.state == PurchaseIntentState.LINKED
    with factory() as db:
        sub = db.scalars(select(ExternalSubscription)).one()
        original = materialize_allowance(db, sub, linked.accepted, cycle(), skew_seconds=10)
        assert original.product_id == "synthetic_summary" and original.quantity == 13
        assert (
            db.get(PurchasedAllowance, original.allowance_id).terms_document["technical_terms"]["backend_consumer_id"]
            == "synthetic-summary"
        )
        db.commit()
    changed = await fresh_link_evaluation(
        config,
        selection=link_selection(product_id="synthetic_summary"),
        technical_offer=summary_offer(99),
        principal="os-euid:29001",
        kernel_transport=httpx.MockTransport(manifest),
        lbx_transport=httpx.MockTransport(transport.respond),
    )
    publish_product_link(
        factory,
        evaluation=changed.document,
        expected_previous_revision=1,
        deadline=changed.deadline,
        lock_timeout_seconds=1,
        provider_origin=config.lbx_provider_origin,
    )
    replay = await purchases.confirm_purchase(
        object(), config, factory=factory, token=TOKEN, key="summary", meaning=purchase.accepted.meaning
    )
    with factory() as db:
        sub = db.scalars(select(ExternalSubscription)).one()
        assert materialize_allowance(db, sub, replay.accepted, cycle(), skew_seconds=10) == original
        later = materialize_allowance(
            db,
            sub,
            replay.accepted,
            cycle().model_copy(update={"start": "2026-11-30", "end": "2026-12-30"}),
            skew_seconds=10,
        )
        assert later.quantity == 13 and later.allowance_id != original.allowance_id
        db.commit()
    assert seen and set(seen) == {"summary.example.test"}
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1
    # A different source/backend cannot take over the retained product head.
    foreign = changed.document.model_copy(update={"backend_consumer_id": "platform-kernel"})
    foreign = foreign.model_copy(update={"identity_digest": commercial_digest(foreign.identity_json())})
    with pytest.raises(MappingRefused, match="mapping_technical_owner_transfer_forbidden"):
        publish_product_link(
            factory,
            evaluation=foreign,
            expected_previous_revision=2,
            deadline=time.monotonic() + 5,
            lock_timeout_seconds=1,
            provider_origin=config.lbx_provider_origin,
        )
    wrong = source_settings(backend_consumers=(backend_consumer(allowed_products=["synthetic_summary"]),))
    async with source_resources(
        wrong, kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=summary_manifest()))
    ) as sources:
        # Select and refuse the persisted owner before any LBX read/new acceptance.
        with pytest.raises(TechnicalSourceRefused):
            await catalog_preview(sources, wrong, session_factory=factory, product_id="synthetic_summary")
