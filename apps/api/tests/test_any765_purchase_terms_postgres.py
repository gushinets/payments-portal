"""Real isolated PostgreSQL acceptance with synthetic provider reads only."""

from datetime import UTC, datetime
from copy import deepcopy
import json
from pathlib import Path
import time

from fastapi import FastAPI
import httpx
import pytest
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition import purchase_terms
from app.composition.purchases import advance_purchase, confirm_purchase, review_purchase
from app.composition.sources import source_resources
from app.core.settings import Settings
from app.domains.catalog.link_publication import publish_product_link
from app.domains.purchases import router as routes, service
from app.domains.purchases.contracts import PurchaseRefused
from app.http.dependencies import get_session_factory
from app.models import (
    AccessInvalidationOutbox,
    BillingProductAccessScope,
    DocumentAcceptance,
    LegalAcceptanceEvent,
    PaidAccessState,
    PurchaseIntent,
    PurchasedAllowance,
)
from apps.api.tests.factories.purchase_terms import SOURCE_PATH, reviewed_meaning
from apps.api.tests.support.any709_step1 import link_document, link_selection, step1_settings
from apps.api.tests.support.kernel import manifest_fixture, resign
from apps.api.tests.test_any709_step2_postgres import TOKEN
from apps.api.tests.test_any709_step3_postgres import setup_purchase

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def fixed_billing_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.lbx import current_offer

    monkeypatch.setattr(current_offer, "utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))


@pytest.fixture
def terms_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    target = tmp_path / "terms.json"
    target.write_bytes(SOURCE_PATH.read_bytes())
    monkeypatch.setattr(purchase_terms, "TEST_TERMS_PATH", target)
    return target


def portal_app(factory: sessionmaker[Session], configuration: Settings, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(routes, "settings", configuration)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_session_factory] = lambda: factory
    return app


def assert_no_paid_state(factory: sessionmaker[Session]) -> None:
    with factory() as db:
        for model in (PaidAccessState, PurchasedAllowance, BillingProductAccessScope, AccessInvalidationOutbox):
            assert db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize("stage", ["before_agreement", "before_subscription"])
@pytest.mark.parametrize("fault", [None, "disabled", "missing", "unit", "owner", "unrelated", "quantity"])
async def test_new_financial_send_rechecks_accepted_capability_without_repricing_or_breaking_recovery(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    terms_file: Path,
    stage: str,
    fault: str | None,
) -> None:
    factory = postgres_session_factory
    config = step1_settings(purchase_test_terms_enabled=True)
    transport = setup_purchase(factory)
    changed = False

    def kernel(request: httpx.Request) -> httpx.Response:
        manifest = deepcopy(manifest_fixture())
        if changed and (stage == "before_agreement" or transport.creates("/agreements")):
            metric = manifest["usage_metrics"][0]
            if fault == "disabled":
                metric["enabled"] = False
            elif fault == "missing":
                manifest["usage_metrics"].pop(0)
            elif fault == "unit":
                metric["unit"] = "different_unit"
            elif fault == "owner":
                metric["product_id"] = "brief_decoder"
            elif fault == "unrelated":
                manifest["usage_metrics"][1]["enabled"] = False
        return httpx.Response(200, json=resign(manifest))

    async with source_resources(
        config, kernel_transport=httpx.MockTransport(kernel), lbx_transport=httpx.MockTransport(transport.respond)
    ) as sources:
        link, offer, documents, terms = await review_purchase(
            sources, config, factory=factory, token=TOKEN, product_id="proposal_ai"
        )
        purchase = await confirm_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            key="accepted-capability-before-create",
            meaning=reviewed_meaning("proposal_ai", link.mapping_revision_id, offer.fingerprint, documents, terms),
        )
        changed = True
        if fault == "quantity":
            terms_file.write_text(terms_file.read_text().replace('"quantity": 100', '"quantity": 50'))
        rejected = fault in {"disabled", "missing", "unit", "owner"}
        if rejected:
            with pytest.raises(PurchaseRefused, match="purchase_technical_terms_unavailable"):
                await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
            assert transport.creates("/agreements") == int(stage == "before_subscription")
            assert transport.creates("/subscriptions") == 0
            saved = service.read_purchase(factory, purchase.user_id, purchase.id)
            assert saved.held and saved.accepted == purchase.accepted
            changed = False  # Restore the accepted capability and resume this purchase.
        result = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert result.state == "linked" and result.accepted.technical_terms.offer.quantity == 100
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1
        # Once linked, current metric changes cannot revoke or reprice history.
        changed = True
        assert (
            await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        ).accepted == purchase.accepted
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1


@pytest.mark.parametrize("product,quantity", [("proposal_ai", 100), ("brief_decoder", 300)])
async def test_http_accepts_exact_terms_and_replays_saved_history_after_source_changes(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    terms_file: Path,
    product: str,
    quantity: int,
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings(purchase_test_terms_enabled=True)
    if product == "brief_decoder":
        for selection, previous in (
            (link_selection(tariff_id=702), 1),
            (link_selection(product_id=product), 0),
        ):
            publish_product_link(
                factory,
                evaluation=link_document(selection=selection),
                expected_previous_revision=previous,
                deadline=time.monotonic() + 5,
                lock_timeout_seconds=1,
                provider_origin=config.lbx_provider_origin,
            )
    app = portal_app(factory, config, monkeypatch)
    headers = {"Authorization": "Bearer " + TOKEN, "Idempotency-Key": "metered"}
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        app.state.sources = sources
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as client:
            review = await client.post("/api/purchases/review", json={"product_id": product}, headers=headers)
            assert review.status_code == 200 and review.headers["cache-control"] == "no-store"
            displayed = review.json()
            technical = displayed["technical_terms"]
            assert technical["offer"]["quantity"] == quantity and technical["provenance"] == "SIMULATED"
            meaning = {
                key: displayed[key]
                for key in ("product_id", "revision_id", "expected_fingerprint", "expected_technical_terms_digest")
            }
            meaning["documents"] = [
                {key: doc[key] for key in ("document_version_id", "acceptance_text_hash")}
                for doc in displayed["documents"]
            ]
            confirmed = await client.post("/api/purchase-intents", json=meaning, headers=headers)
            assert confirmed.status_code == 200 and confirmed.json()["accepted"] == displayed
            assert not confirmed.json()["paid_access_granted"]
            assert confirmed.headers["cache-control"] == "no-store"
            with factory() as db:
                row = db.scalar(select(PurchaseIntent))
                assert row.accepted_snapshot_schema_version == "accepted-purchase:v2"
                saved = service.accepted(row)
                assert saved.technical_terms.offer.quantity == quantity
                assert saved.technical_terms.selection == saved.selection
                assert saved.technical_terms.account_id == row.external_billing_account_id
                assert db.scalar(select(func.count()).select_from(LegalAcceptanceEvent)) == 1
                assert db.scalar(select(func.count()).select_from(DocumentAcceptance)) >= 3
            terms_file.write_text(terms_file.read_text().replace('"quantity": 100', '"quantity": 999'))
            app.state.sources = object()
            changed_fixture_replay = await client.post("/api/purchase-intents", json=meaning, headers=headers)
            assert changed_fixture_replay.json() == confirmed.json()
            terms_file.unlink()
            monkeypatch.setattr(routes, "settings", step1_settings(purchase_test_terms_enabled=False))
            app.state.sources = object()  # Replay and owned reads must not consult sources.
            replay = await client.post("/api/purchase-intents", json=meaning, headers=headers)
            assert replay.status_code == 200 and replay.json() == confirmed.json()
            status = await client.get(
                "/api/purchase-intents/" + confirmed.json()["purchase_intent_id"], headers=headers
            )
            assert status.json() == confirmed.json()
            changed = {**meaning, "expected_technical_terms_digest": "sha256:" + "0" * 64}
            conflict = await client.post("/api/purchase-intents", json=changed, headers=headers)
            assert conflict.status_code == 409
            assert conflict.json()["detail"]["code"] == "purchase_idempotency_conflict"
    assert not any(req.method == "POST" for req in transport.requests)
    assert_no_paid_state(factory)


@pytest.mark.parametrize("change", ["quantity", "disabled", "omitted_digest", "pin_without_terms"])
async def test_confirmation_revalidates_new_acceptance_and_refuses_without_writes(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    terms_file: Path,
    change: str,
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings(purchase_test_terms_enabled=True)
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        link, offer, documents, terms = await review_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            product_id="proposal_ai",
        )
        meaning = reviewed_meaning("proposal_ai", link.mapping_revision_id, offer.fingerprint, documents, terms)
        if change == "quantity":
            terms_file.write_text(terms_file.read_text().replace('"quantity": 100', '"quantity": 101'))
        elif change == "disabled":
            config = step1_settings(purchase_test_terms_enabled=False)
        else:
            meaning = meaning.model_copy(update={"expected_technical_terms_digest": None})
        with pytest.raises(PurchaseRefused, match="terms_changed"):
            if change == "pin_without_terms":
                # Internal callers cannot bypass enabled-source policy with an
                # absent digest/terms pair, even before any customer reservation.
                service.pin_purchase(factory, config, TOKEN, "race", meaning, link, offer, documents)
            else:
                await confirm_purchase(sources, config, factory=factory, token=TOKEN, key="race", meaning=meaning)
        with factory() as db:
            for model in (PurchaseIntent, LegalAcceptanceEvent, DocumentAcceptance):
                assert db.scalar(select(func.count()).select_from(model)) == 0
    assert_no_paid_state(factory)
    assert not any(req.method == "POST" for req in transport.requests)


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "other_metric_disabled",
        "other_quantity",
        "source_version",
        "selected_quantity",
        "selected_metric_disabled",
    ],
)
async def test_http_confirmation_compares_selected_meaning_and_keeps_full_audit_evidence(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    terms_file: Path,
    change: str,
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings(purchase_test_terms_enabled=True)
    changed = False

    def kernel(request: httpx.Request) -> httpx.Response:
        document = deepcopy(manifest_fixture())
        if changed and change in {"other_metric_disabled", "selected_metric_disabled"}:
            product = "brief_decoder" if change == "other_metric_disabled" else "proposal_ai"
            next(metric for metric in document["usage_metrics"] if metric["product_id"] == product)["enabled"] = False
        return httpx.Response(200, json=resign(document))

    app = portal_app(factory, config, monkeypatch)
    headers = {"Authorization": "Bearer " + TOKEN, "Idempotency-Key": "selected-meaning"}
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        app.state.sources = sources
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as client:
            review = await client.post("/api/purchases/review", json={"product_id": "proposal_ai"}, headers=headers)
            assert review.status_code == 200
            displayed = review.json()
            meaning = {
                key: displayed[key]
                for key in ("product_id", "revision_id", "expected_fingerprint", "expected_technical_terms_digest")
            }
            meaning["documents"] = [
                {key: doc[key] for key in ("document_version_id", "acceptance_text_hash")}
                for doc in displayed["documents"]
            ]
            changed = True
            if change in {"other_quantity", "selected_quantity", "source_version"}:
                payload = json.loads(terms_file.read_text())
                if change == "source_version":
                    payload["source_version"] += ":updated"
                else:
                    product = "brief_decoder" if change == "other_quantity" else "proposal_ai"
                    next(item for item in payload["offers"] if item["product_id"] == product)["quantity"] += 1
                terms_file.write_text(json.dumps(payload))
            confirmed = await client.post("/api/purchase-intents", json=meaning, headers=headers)
            if change in {"selected_quantity", "selected_metric_disabled"}:
                expected = "terms_changed" if change == "selected_quantity" else "purchase_technical_terms_unavailable"
                assert confirmed.status_code == (409 if change == "selected_quantity" else 503)
                assert confirmed.json()["detail"]["code"] == expected
                with factory() as db:
                    for model in (PurchaseIntent, LegalAcceptanceEvent, DocumentAcceptance):
                        assert db.scalar(select(func.count()).select_from(model)) == 0
            else:
                assert confirmed.status_code == 200
                accepted = confirmed.json()["accepted"]
                assert accepted["expected_technical_terms_digest"] == meaning["expected_technical_terms_digest"]
                assert accepted["technical_terms"]["offer"] == displayed["technical_terms"]["offer"]
                with factory() as db:
                    saved = service.accepted(db.scalars(select(PurchaseIntent)).one())
                    assert saved.technical_terms.offer.quantity == 100
                    if change != "none":
                        assert saved.technical_terms.digest != displayed["technical_terms"]["digest"]
                    if change == "other_metric_disabled":
                        assert saved.technical_terms.kernel_manifest_version != manifest_fixture()["manifest_version"]
                    elif change in {"other_quantity", "source_version"}:
                        assert saved.technical_terms.source_digest != displayed["technical_terms"]["source_digest"]
                app.state.sources = object()
                replay = await client.post("/api/purchase-intents", json=meaning, headers=headers)
                assert replay.json() == confirmed.json()
    assert_no_paid_state(factory)
    assert not any(req.method == "POST" for req in transport.requests)


async def test_historical_v2_full_digest_preserves_exact_replay(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    terms_file: Path,
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings(purchase_test_terms_enabled=True)

    def historical_insert(db: Session, flush_context: object, instances: object) -> None:
        for row in db.new:
            if isinstance(row, PurchaseIntent):
                row.accepted_snapshot["meaning"]["expected_technical_terms_digest"] = row.accepted_snapshot[
                    "technical_terms"
                ]["digest"]

    event.listen(Session, "before_flush", historical_insert)
    try:
        async with source_resources(
            config,
            kernel_transport=httpx.MockTransport(transport.kernel),
            lbx_transport=httpx.MockTransport(transport.respond),
        ) as sources:
            link, offer, documents, terms = await review_purchase(
                sources, config, factory=factory, token=TOKEN, product_id="proposal_ai"
            )
            original = await confirm_purchase(
                sources,
                config,
                factory=factory,
                token=TOKEN,
                key="historical-v2",
                meaning=reviewed_meaning("proposal_ai", link.mapping_revision_id, offer.fingerprint, documents, terms),
            )
    finally:
        event.remove(Session, "before_flush", historical_insert)
    assert original.accepted.meaning.expected_technical_terms_digest == terms.digest
    terms_file.unlink()
    replay = await confirm_purchase(
        object(), config, factory=factory, token=TOKEN, key="historical-v2", meaning=original.accepted.meaning
    )
    assert replay == original
    presented = routes.present_purchase(replay)
    assert presented.accepted.expected_technical_terms_digest == terms.digest
    assert presented.accepted.technical_terms.digest == terms.digest
    assert_no_paid_state(factory)


async def test_legacy_v1_same_key_replay_never_attaches_new_test_terms(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()

    def historical_insert(db: Session, flush_context: object, instances: object) -> None:
        for row in db.new:
            if isinstance(row, PurchaseIntent):
                snapshot = row.accepted_snapshot
                snapshot["schema_version"] = "accepted-purchase:v1"
                snapshot.pop("technical_terms")
                snapshot["meaning"].pop("expected_technical_terms_digest")
                row.accepted_snapshot_schema_version = "accepted-purchase:v1"

    # Simulate an insert by the historical v1 writer; never update immutable history.
    event.listen(Session, "before_flush", historical_insert)
    try:
        async with source_resources(
            config,
            kernel_transport=httpx.MockTransport(transport.kernel),
            lbx_transport=httpx.MockTransport(transport.respond),
        ) as sources:
            link, offer, documents, terms = await review_purchase(
                sources,
                config,
                factory=factory,
                token=TOKEN,
                product_id="proposal_ai",
            )
            meaning = reviewed_meaning("proposal_ai", link.mapping_revision_id, offer.fingerprint, documents, terms)
            original = await confirm_purchase(
                sources, config, factory=factory, token=TOKEN, key="legacy", meaning=meaning
            )
    finally:
        event.remove(Session, "before_flush", historical_insert)
    replay = await confirm_purchase(
        object(),
        step1_settings(purchase_test_terms_enabled=True),
        factory=factory,
        token=TOKEN,
        key="legacy",
        meaning=meaning,
    )
    assert replay == original and replay.accepted.schema_version == "accepted-purchase:v1"
    assert replay.accepted.technical_terms is None
    assert_no_paid_state(factory)
