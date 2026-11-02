"""Final-review regressions: retained scopes, exclusive current offers and history."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing import bootstrap_account
from app.composition.catalog import catalog_preview
from app.composition.purchases import advance_purchase, confirm_purchase, review_purchase
from app.composition.sources import source_resources
from app.domains.catalog.commercial_offer import CommercialScope
from app.domains.catalog.link_publication import (
    StoredProductLink,
    publish_product_link,
    query_link_history,
    query_product_link,
    validate_product_link,
)
from app.domains.catalog.mapping_evidence import MappingRefused
from app.domains.catalog.product_link import LINK_SCHEMA
from app.domains.purchases import service
from app.domains.purchases.contracts import LegalSelection, PurchaseMeaning
from app.models import CommercialMappingRevision, CommercialProductHead, PurchaseIntent, PurchaseIntentState
from apps.api.tests.support.any709_step1 import link_document, link_selection, step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.test_any709_step2_postgres import seed, TOKEN
from apps.api.tests.test_any709_step3_postgres import accept

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def fixed_billing_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))


def publish(
    factory: sessionmaker[Session],
    product: str = "proposal_ai",
    *,
    revision: int = 0,
    tariff: int = 701,
    scope: CommercialScope | None = None,
) -> StoredProductLink:
    document = link_document(selection=link_selection(product_id=product, tariff_id=tariff))
    if scope is not None:
        document = link_document(selection=document.selection, scope=scope)
    return publish_product_link(
        factory,
        evaluation=document,
        expected_previous_revision=revision,
        deadline=time.monotonic() + 10,
        lock_timeout_seconds=5,
        provider_origin=step1_settings().lbx_provider_origin,
    ).stored


def retain_conflicting_head(factory: sessionmaker[Session], original: StoredProductLink) -> StoredProductLink:
    """Seed valid historical rows allowed by the previous publisher, never live data."""
    document = link_document(
        selection=link_selection(product_id="brief_decoder"),
        scope=original.document.scope,
        product_revision_number=1,
    )
    with factory() as db:
        row = CommercialMappingRevision(
            mapping_revision_id=uuid4(),
            external_billing_account_id=document.scope.external_billing_account_id,
            billing_offer_id=document.selection.billing_offer_id,
            revision_number=2,
            manifest_version=document.manifest_version,
            catalog_version=None,
            catalog_digest=document.identity_digest,
            mapping_schema_version=LINK_SCHEMA,
            mapping_document=document.model_dump(mode="json"),
            published_at=document.published_at,
            published_by_principal=document.publisher_principal,
        )
        db.add(row)
        db.flush()
        db.add(
            CommercialProductHead(
                external_billing_account_id=document.scope.external_billing_account_id,
                product_id="brief_decoder",
                provider_origin=step1_settings().lbx_provider_origin,
                mapping_revision_id=row.mapping_revision_id,
                revision_number=1,
            )
        )
        stored = validate_product_link(row, scope=document.scope)
        db.commit()
        return stored


@pytest.mark.parametrize("legacy_scope", [False, True])
@pytest.mark.parametrize("rotate_username", [False, True])
@pytest.mark.parametrize("change_price", [False, True])
async def test_retained_scope_preserves_consent_and_only_real_price_changes_block(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    legacy_scope: bool,
    rotate_username: bool,
    change_price: bool,
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    account = config.lbx_legacy_credential_scope if legacy_scope else config.lbx_external_billing_account_id
    assert account is not None
    link = publish(factory, scope=replace(link_document().scope, external_billing_account_id=account))
    transport = PurchaseTransport()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
    if rotate_username:
        config = config.model_copy(update={"lbx_server_username": SecretStr("rotated-synthetic-user")})
    if change_price:
        transport.change_price()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        result = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
    assert result.state == (
        PurchaseIntentState.FAILED_BEFORE_EXTERNAL_EFFECT if change_price else PurchaseIntentState.LINKED
    )
    assert result.accepted == purchase.accepted and result.account_id == account
    assert [operation.id for operation in result.operations] == [operation.id for operation in purchase.operations]
    assert [transport.creates(path) for path in ("/agreements", "/subscriptions")] == (
        [0, 0] if change_price else [1, 1]
    )
    with factory() as db:
        row = db.get(PurchaseIntent, purchase.id)
        assert row.mapping_revision_id == link.mapping_revision_id
        assert row.external_billing_account_id == account
        assert row.accepted_commercial_fingerprint == purchase.accepted.meaning.expected_fingerprint


def test_concurrent_products_cannot_claim_the_same_offer(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    def attempt(product: str) -> str:
        try:
            publish(postgres_session_factory, product)
            return "published"
        except MappingRefused as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, ["proposal_ai", "brief_decoder"]))
    assert sorted(results) == ["mapping_offer_product_conflict", "published"]
    with postgres_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(CommercialProductHead)) == 1
        assert db.scalar(select(func.count()).select_from(CommercialMappingRevision)) == 1


def test_offer_reuse_after_retarget_preserves_its_original_revision(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    factory = postgres_session_factory
    original = publish(factory)
    moved = publish(factory, revision=1, tariff=702)
    reused = publish(factory, "brief_decoder")
    assert moved.revision_number == 2 and reused.offer_revision_number == 2
    assert (
        query_link_history(
            factory, scope=original.document.scope, offer_id=original.document.selection.billing_offer_id, revision=1
        )
        == original
    )


async def test_retained_conflict_blocks_new_admission_but_operator_can_retarget(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    original = publish(factory)
    transport = PurchaseTransport()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        link, offer, documents = await review_purchase(
            sources, config, factory=factory, token=TOKEN, product_id="proposal_ai"
        )
        meaning = PurchaseMeaning(
            product_id="proposal_ai",
            revision_id=link.mapping_revision_id,
            expected_fingerprint=offer.fingerprint,
            documents=tuple(
                LegalSelection(
                    document_version_id=doc.document_version_id, acceptance_text_hash=doc.acceptance_text_hash
                )
                for doc in documents
            ),
        )
        conflicting = retain_conflicting_head(factory, original)
        for product in ("proposal_ai", "brief_decoder"):
            assert query_product_link(factory, scope=original.document.scope, product_id=product) is not None
        with pytest.raises(MappingRefused, match="mapping_offer_product_conflict"):
            publish(factory, revision=1)
        with pytest.raises(MappingRefused, match="mapping_offer_product_conflict"):
            await catalog_preview(sources, config, session_factory=factory, product_id="proposal_ai")
        with pytest.raises(MappingRefused, match="mapping_offer_product_conflict"):
            service.pin_purchase(factory, config, TOKEN, "new-request", meaning, link, offer, documents)
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(PurchaseIntent)) == 0
        publish(factory, "brief_decoder", revision=1, tariff=702)
        assert (await catalog_preview(sources, config, session_factory=factory, product_id="proposal_ai"))[0].offer
        assert (
            query_link_history(
                factory,
                scope=conflicting.document.scope,
                offer_id=conflicting.document.selection.billing_offer_id,
                revision=2,
            )
            == conflicting
        )
    assert not [request for request in transport.requests if request.method == "POST"]


async def test_retained_conflict_does_not_block_original_purchase_manage_or_replay(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    original = publish(factory)
    transport = PurchaseTransport()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        retain_conflicting_head(factory, original)
        widget = await bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        replay = await confirm_purchase(
            sources, config, factory=factory, token=TOKEN, key="one-request", meaning=purchase.accepted.meaning
        )
        assert widget.purchase_id == purchase.id and replay.accepted == purchase.accepted
    assert [transport.creates(path) for path in ("/users", "/agreements", "/subscriptions")] == [1, 1, 1]
