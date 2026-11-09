"""Purchased production-shaped terms on isolated PostgreSQL and synthetic sources.

CONFIGURED_SOURCE here exercises the non-mock adapter policy, not live sales.
All HTTP is intercepted by MockTransport; quantities approve no real offer.
"""

from copy import deepcopy
from datetime import UTC, datetime

from fastapi import FastAPI
import httpx
from pydantic import ValidationError
import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition import purchases
from app.composition.mapping_operator import fresh_link_evaluation
from app.composition.sources import source_resources
from app.domains.billing.paid_allowances import materialize_allowance
from app.domains.billing.paid_cycles import CalendarEvidence
from app.domains.billing.paid_router import PaidAccessAllowanceResponse
from app.domains.catalog.admission import SelectedCapabilityUnavailable
from app.domains.catalog.link_publication import (
    StoredProductLink,
    publish_product_link,
    query_link_history,
    MappingRevisionConflict,
)
from app.domains.catalog.mapping_evidence import MappingRefused
from app.domains.catalog.technical_offer import TechnicalOffer
from app.domains.purchases import router, service
from app.domains.purchases.contracts import AcceptedPurchase, PurchaseRefused
from app.domains.purchases.technical_terms import AcceptedTechnicalTerms
from app.http.dependencies import get_session_factory
from app.models import CommercialMappingRevision, ExternalSubscription, LegalAcceptanceEvent, PurchaseIntent
from apps.api.tests.factories.purchase_terms import reviewed_meaning
from apps.api.tests.support.any709_step1 import link_selection, step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.support.kernel import manifest_fixture, resign
from apps.api.tests.test_any709_step2_postgres import TOKEN, seed

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def fixed_billing_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, tzinfo=UTC))


def configured_manifest() -> dict[str, object]:
    document = manifest_fixture()
    document["usage_metrics"].append(
        {
            "product_id": "proposal_ai",
            "metric_key": "proposal_ai.generations",
            "unit": "generation",
            "enabled": True,
        }
    )
    return resign(document)


def technical_offer(quantity: object = 7) -> TechnicalOffer:
    return TechnicalOffer.model_validate(
        {
            "product_id": "proposal_ai",
            "metric_key": "proposal_ai.generations",
            "unit": "generation",
            "quantity": quantity,
            "quantity_mode": "fixed_per_cycle",
        }
    )


async def publish(
    factory: sessionmaker[Session],
    transport: PurchaseTransport,
    *,
    quantity: int = 7,
    previous: int = 0,
) -> StoredProductLink:
    fresh = await fresh_link_evaluation(
        step1_settings(kernel_mock_enabled=False),
        selection=link_selection(),
        principal="os-euid:29001",
        technical_offer=technical_offer(quantity),
        kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=configured_manifest())),
        lbx_transport=httpx.MockTransport(transport.respond),
    )
    return publish_product_link(
        factory,
        evaluation=fresh.document,
        expected_previous_revision=previous,
        deadline=fresh.deadline,
        lock_timeout_seconds=1,
        provider_origin=step1_settings().lbx_provider_origin,
    ).stored


@pytest.mark.parametrize("quantity", [True, False, 1.0, 0.5, -1, 2**53, "7"])
def test_technical_quantity_is_strict_and_lossless(quantity: object) -> None:
    with pytest.raises(ValidationError):
        technical_offer(quantity)


@pytest.mark.parametrize("quantity", [0, 7, 2**53 - 1])
async def test_http_pins_exact_published_quantity_and_replays_before_source_io(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    quantity: int,
) -> None:
    factory = postgres_session_factory
    seed(factory)
    transport = PurchaseTransport()
    transport.pool = migrated_database.pool
    link = await publish(factory, transport, quantity=quantity)
    config = step1_settings(
        app_env="production",
        app_public_base_url="https://portal.example.test",
        cors_allow_origins=("https://portal.example.test",),
        kernel_base_url="https://kernel.example.test",
        kernel_mock_enabled=False,
    )
    monkeypatch.setattr(router, "settings", config)
    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[get_session_factory] = lambda: factory
    headers = {"Authorization": "Bearer " + TOKEN, "Idempotency-Key": "published-terms"}
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=configured_manifest())),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        app.state.sources = sources
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as client:
            response = await client.post("/api/purchases/review", headers=headers, json={"product_id": "proposal_ai"})
            assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
            review = response.json()
            assert review["technical_terms"]["provenance"] == "CONFIGURED_SOURCE"
            assert review["technical_terms"]["offer"]["quantity"] == quantity
            assert review["terms"]["commercial_quantity"] == "1"
            meaning = {
                key: review[key]
                for key in (
                    "product_id",
                    "revision_id",
                    "expected_fingerprint",
                    "expected_technical_terms_digest",
                )
            }
            meaning["documents"] = [
                {key: doc[key] for key in ("document_version_id", "acceptance_text_hash")}
                for doc in review["documents"]
            ]
            confirmed = await client.post("/api/purchase-intents", headers=headers, json=meaning)
            assert confirmed.status_code == 200 and confirmed.json()["accepted"] == review
            assert confirmed.headers["cache-control"] == "no-store"
            with factory() as db:
                row = db.scalars(select(PurchaseIntent)).one()
                saved = service.accepted(row)
                terms = saved.technical_terms
                assert saved.schema_version == row.accepted_snapshot_schema_version == "accepted-purchase:v3"
                assert terms.schema_version == "purchased-technical-terms:v2"
                assert terms.mapping_digest == link.document.identity_digest
                assert terms.offer == technical_offer(quantity) and terms.selection.quantity == 1
                assert terms.account_id == row.external_billing_account_id
                assert (
                    PaidAccessAllowanceResponse(
                        allowance_id="synthetic",
                        product_id="proposal_ai",
                        metric_key=terms.offer.metric_key,
                        unit=terms.offer.unit,
                        quantity=quantity,
                        provenance=terms.provenance,
                    ).provenance
                    == "CONFIGURED_SOURCE"
                )
            # Publish a different quantity and remove all I/O resources. Replay
            # and owned read must still return the exact originally accepted DTO.
            await publish(factory, transport, quantity=quantity - 1 if quantity else 1, previous=1)
            app.state.sources = object()
            replay = await client.post("/api/purchase-intents", headers=headers, json=meaning)
            assert replay.status_code == 200 and replay.json() == confirmed.json()
            status = await client.get(
                "/api/purchase-intents/" + confirmed.json()["purchase_intent_id"], headers=headers
            )
            assert status.json() == confirmed.json()
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(LegalAcceptanceEvent)) == 1
    assert all(request.method == "GET" for request in transport.requests if not request.url.path.endswith("/auth"))


async def test_quantity_publication_changes_identity_cas_and_requires_fresh_consent(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    factory = postgres_session_factory
    seed(factory)
    transport = PurchaseTransport()
    original = await publish(factory, transport)
    assert await publish(factory, transport, previous=0) == original  # Idempotent publication.
    config = step1_settings(kernel_mock_enabled=False)
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=configured_manifest())),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        link, offer, documents, terms = await purchases.review_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            product_id="proposal_ai",
        )
        meaning = reviewed_meaning("proposal_ai", link.mapping_revision_id, offer.fingerprint, documents, terms)
        with pytest.raises(MappingRevisionConflict):
            await publish(factory, transport, quantity=8, previous=0)
        updated = await publish(factory, transport, quantity=8, previous=1)
        assert updated.document.identity_digest != original.document.identity_digest
        assert (
            query_link_history(
                factory,
                scope=original.document.scope,
                offer_id=original.document.selection.billing_offer_id,
                revision=1,
            )
            == original
        )
        # The final transaction, after preflight, must independently fence a publication race.
        with pytest.raises(PurchaseRefused, match="terms_changed"):
            service.pin_purchase(factory, config, TOKEN, "cas", meaning, link, offer, documents, terms)
        with pytest.raises(PurchaseRefused, match="terms_changed"):
            await purchases.confirm_purchase(sources, config, factory=factory, token=TOKEN, key="cas", meaning=meaning)
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(PurchaseIntent)) == 0
            assert db.scalar(select(func.count()).select_from(LegalAcceptanceEvent)) == 0
        new_link, new_offer, new_documents, new_terms = await purchases.review_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            product_id="proposal_ai",
        )
        assert new_offer.fingerprint == offer.fingerprint  # LBX quantity/price is unchanged.
        assert new_terms.confirmation_digest() != terms.confirmation_digest()
        purchase = await purchases.confirm_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            key="cas",
            meaning=reviewed_meaning(
                "proposal_ai", new_link.mapping_revision_id, new_offer.fingerprint, new_documents, new_terms
            ),
        )
        assert purchase.accepted.technical_terms.offer.quantity == 8


@pytest.mark.parametrize("fault", ["missing", "disabled", "owner", "unit", "product_disabled", "simulated"])
async def test_publication_and_new_purchase_require_selected_enabled_capability(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    fault: str,
) -> None:
    factory = postgres_session_factory
    seed(factory)
    transport = PurchaseTransport()
    await publish(factory, transport)
    manifest = configured_manifest()
    metric = manifest["usage_metrics"][-1]
    if fault == "missing":
        manifest["usage_metrics"].pop()
    elif fault == "disabled":
        metric["enabled"] = False
    elif fault == "owner":
        metric["product_id"] = "brief_decoder"
    elif fault == "unit":
        metric["unit"] = "analysis"
    elif fault == "product_disabled":
        next(product for product in manifest["products"] if product["product_id"] == "proposal_ai")["enabled"] = False
    config = step1_settings(kernel_mock_enabled=fault == "simulated")
    kernel = httpx.MockTransport(lambda request: httpx.Response(200, json=resign(manifest)))
    # A disabled product is handled by existing catalog discovery, before terms.
    from app.domains.catalog.preview import CatalogProductNotFound

    with pytest.raises((SelectedCapabilityUnavailable, MappingRefused, CatalogProductNotFound)):
        await fresh_link_evaluation(
            config,
            selection=link_selection(),
            principal="os-euid:29001",
            technical_offer=technical_offer(),
            kernel_transport=kernel,
            lbx_transport=httpx.MockTransport(transport.respond),
        )
    async with source_resources(
        config, kernel_transport=kernel, lbx_transport=httpx.MockTransport(transport.respond)
    ) as sources:
        with pytest.raises((PurchaseRefused, CatalogProductNotFound)):
            await purchases.review_purchase(sources, config, factory=factory, token=TOKEN, product_id="proposal_ai")
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(CommercialMappingRevision)) == 1
        assert db.scalar(select(func.count()).select_from(PurchaseIntent)) == 0


async def test_global_manifest_changes_preserve_selected_consent_and_full_audit_identity(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    factory = postgres_session_factory
    seed(factory)
    transport = PurchaseTransport()
    original = await publish(factory, transport)
    config = step1_settings(kernel_mock_enabled=False)
    manifest = configured_manifest()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=resign(manifest))),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        link, offer, documents, terms = await purchases.review_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            product_id="proposal_ai",
        )
        meaning = reviewed_meaning("proposal_ai", link.mapping_revision_id, offer.fingerprint, documents, terms)
        next(metric for metric in manifest["usage_metrics"] if metric["product_id"] == "brief_decoder")["enabled"] = (
            False
        )
        manifest["generated_at"] = "2026-11-09T00:00:00Z"
        purchase = await purchases.confirm_purchase(
            sources, config, factory=factory, token=TOKEN, key="unchanged-selection", meaning=meaning
        )
        accepted = purchase.accepted.technical_terms
        assert accepted.confirmation_digest() == terms.confirmation_digest()
        assert accepted.digest != terms.digest and accepted.kernel_manifest_version != terms.kernel_manifest_version
        assert (
            accepted.source_digest == terms.source_digest
            and accepted.mapping_digest == original.document.identity_digest
        )


async def test_existing_subscription_keeps_quantity_through_republication_and_renewal(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    factory = postgres_session_factory
    seed(factory)
    transport = PurchaseTransport()
    transport.pool = migrated_database.pool
    await publish(factory, transport)
    config = step1_settings(kernel_mock_enabled=False)
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=configured_manifest())),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        link, offer, documents, terms = await purchases.review_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            product_id="proposal_ai",
        )
        purchase = await purchases.confirm_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            key="retained",
            meaning=reviewed_meaning("proposal_ai", link.mapping_revision_id, offer.fingerprint, documents, terms),
        )
        await publish(factory, transport, quantity=8, previous=1)
        linked = await purchases.advance_purchase(
            sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id
        )
        assert linked.accepted == purchase.accepted and linked.state == "linked"
        cycle = CalendarEvidence(precision="date", start="2026-10-31", end="2026-11-29", anchor="2026-01-31")
        with factory() as db:
            sub = db.scalars(select(ExternalSubscription)).one()
            first = materialize_allowance(db, sub, linked.accepted, cycle, skew_seconds=10)
            db.commit()
        with factory() as db:
            sub = db.scalars(select(ExternalSubscription)).one()
            same = materialize_allowance(
                db, sub, service.read_purchase(factory, purchase.user_id, purchase.id).accepted, cycle, skew_seconds=10
            )
            later = materialize_allowance(
                db,
                sub,
                linked.accepted,
                cycle.model_copy(
                    update={
                        "start": "2026-11-30",
                        "end": "2026-12-30",
                    }
                ),
                skew_seconds=10,
            )
            assert same.allowance_id == first.allowance_id
            assert later.allowance_id != first.allowance_id and later.quantity == first.quantity == 7
            db.commit()
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1


async def test_configured_documents_reject_relabeling_and_broken_mapping_binding(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    factory = postgres_session_factory
    seed(factory)
    transport = PurchaseTransport()
    await publish(factory, transport)
    config = step1_settings(kernel_mock_enabled=False)
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=configured_manifest())),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        link, offer, documents, terms = await purchases.review_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            product_id="proposal_ai",
        )
        meaning = reviewed_meaning("proposal_ai", link.mapping_revision_id, offer.fingerprint, documents, terms)
        for change in ({"mapping_digest": "sha256:" + "0" * 64}, {"offer": technical_offer(8)}):
            invalid = terms.model_copy(update=change)
            with pytest.raises(PurchaseRefused, match="terms_changed"):
                service.pin_purchase(factory, config, TOKEN, "invalid", meaning, link, offer, documents, invalid)
        for field, value in (("provenance", "SIMULATED"), ("schema_version", "purchased-technical-terms:v1")):
            payload = terms.model_dump(mode="json")
            payload[field] = value
            with pytest.raises(ValidationError):
                AcceptedTechnicalTerms.model_validate(payload)
        purchase = await purchases.confirm_purchase(
            sources, config, factory=factory, token=TOKEN, key="valid", meaning=meaning
        )
        old = deepcopy(purchase.accepted.model_dump(mode="json"))
        old["schema_version"] = "accepted-purchase:v2"
        with pytest.raises(ValidationError):
            AcceptedPurchase.model_validate(old)


async def test_uncertain_original_subscription_recovers_before_new_sale_io(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    factory = postgres_session_factory
    seed(factory)
    transport = PurchaseTransport()
    await publish(factory, transport)
    config = step1_settings(kernel_mock_enabled=False)
    recovering = False

    def kernel(request: httpx.Request) -> httpx.Response:
        assert not recovering, "original recovery attempted new-sale Kernel I/O"
        return httpx.Response(200, json=configured_manifest())

    async with source_resources(
        config, kernel_transport=httpx.MockTransport(kernel), lbx_transport=httpx.MockTransport(transport.respond)
    ) as sources:
        link, offer, documents, terms = await purchases.review_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            product_id="proposal_ai",
        )
        purchase = await purchases.confirm_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            key="uncertain-original",
            meaning=reviewed_meaning("proposal_ai", link.mapping_revision_id, offer.fingerprint, documents, terms),
        )
        transport.fail_create = "/subscriptions"
        transport.hide.add("/subscriptions")
        pending = await purchases.advance_purchase(
            sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id
        )
        assert pending.state == "awaiting_external_result"
        await publish(factory, transport, quantity=8, previous=1)
        recovering = True
        transport.hide.clear()
        recovered = await purchases.advance_purchase(
            sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id
        )
        assert recovered.state == "linked" and recovered.accepted == purchase.accepted
        assert recovered.accepted.technical_terms.offer.quantity == 7
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1
