"""Connection admission interleavings; no immutable identity relabelling or live HTTP."""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from threading import Event, current_thread
from uuid import UUID
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from app.core.settings import Settings
from app.domains.catalog import link_publication as links
from app.domains.catalog.commercial_offer import CommercialScope
from app.domains.catalog.link_publication import LinkPublicationResult
from app.domains.catalog.mapping_evidence import MappingRefused
from app.domains.catalog.product_link import ProductLinkDocument

import asyncio
import time
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.domains.billing.contracts import BillingRefused
from sqlalchemy import func
from app.models import ExternalCreateOperation
from app.composition.billing import AccountWidget, bootstrap_account
from app.composition.mapping_operator import configured_mapping_scope
from app.composition.sources import source_resources
from app.domains.catalog.link_publication import publish_product_link, query_product_link
from app.domains.billing.customers import (
    reserve_customer,
    claim_customer_send,
    record_customer_receipt,
    apply_customer_read,
)
from app.models import (
    CommercialMappingRevision,
    CommercialProductHead,
    ExternalBillingCustomer,
    User,
    ExternalBillingCustomerBindingState,
)
from apps.api.tests.support.any709_step1 import link_document, link_selection, step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.test_any709_step2_postgres import TOKEN, seed

pytestmark = pytest.mark.postgres


def publish(
    factory: sessionmaker[Session], configuration: Settings, *, product: str = "proposal_ai", previous: int = 1
) -> LinkPublicationResult:
    return publish_product_link(
        factory,
        evaluation=link_document(selection=link_selection(product_id=product)),
        expected_previous_revision=previous,
        deadline=time.monotonic() + 10,
        lock_timeout_seconds=1,
        provider_origin=configuration.lbx_provider_origin,
        legacy_account_id=configuration.lbx_legacy_credential_scope,
    )


@pytest.mark.parametrize("origin_already_bound", [False, True])
def test_account_open_preserves_retained_link_publication(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], origin_already_bound: bool
) -> None:
    factory = postgres_session_factory
    configuration = step1_settings()
    seed(factory)
    legacy_scope = replace(
        configured_mapping_scope(configuration), external_billing_account_id=configuration.lbx_legacy_credential_scope
    )
    document = link_document(scope=legacy_scope, product_revision_number=1)
    revision_id = uuid4()
    with factory() as db:
        db.add(
            CommercialMappingRevision(
                mapping_revision_id=revision_id,
                external_billing_account_id=legacy_scope.external_billing_account_id,
                billing_offer_id=document.selection.billing_offer_id,
                revision_number=1,
                manifest_version=document.manifest_version,
                catalog_version=None,
                catalog_digest=document.identity_digest,
                mapping_schema_version=document.schema_version,
                mapping_document=document.model_dump(mode="json"),
                published_at=document.published_at,
                published_by_principal=document.publisher_principal,
            )
        )
        db.flush()
        db.add(
            CommercialProductHead(
                external_billing_account_id=legacy_scope.external_billing_account_id,
                product_id=document.selection.product_id,
                mapping_revision_id=revision_id,
                revision_number=1,
                provider_origin=configuration.lbx_provider_origin if origin_already_bound else None,
            )
        )
        db.commit()
    known = query_product_link(
        factory,
        scope=configured_mapping_scope(configuration),
        product_id=document.selection.product_id,
        provider_origin=configuration.lbx_provider_origin,
        legacy_account_id=configuration.lbx_legacy_credential_scope,
    )
    assert known.document.scope == legacy_scope
    transport = PurchaseTransport()

    async def open_account() -> AccountWidget:
        async with source_resources(configuration, lbx_transport=httpx.MockTransport(transport.respond)) as sources:
            return await bootstrap_account(sources, configuration, factory=factory, token=TOKEN)

    if not origin_already_bound:
        with pytest.raises(BillingRefused, match="billing_connection_conflict"):
            asyncio.run(open_account())
        assert transport.creates("/users") == 0
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(ExternalBillingCustomer)) == 0
            assert db.scalar(select(func.count()).select_from(ExternalCreateOperation)) == 0
        proof = publish(factory, configuration)
        assert not proof.inserted and proof.stored == known
    assert asyncio.run(open_account()).credential
    assert transport.creates("/users") == 1
    # No competing identity was created before privileged origin proof; the
    # completed proof enables the same ordinary opening at the original scope.
    result = publish(factory, configuration)
    assert not result.inserted and result.stored == known
    with factory() as db:
        customer = db.scalar(select(ExternalBillingCustomer))
        assert customer.provider_origin == configuration.lbx_provider_origin
        assert customer.external_billing_account_id == legacy_scope.external_billing_account_id


@pytest.mark.parametrize("retained_legacy", [False, True])
def test_customer_only_binding_scope_is_reused_for_first_link(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], retained_legacy: bool
) -> None:
    factory = postgres_session_factory
    configuration = step1_settings()
    seed(factory)
    if retained_legacy:
        # Insert retained pre-v2 identity at its original scope. No immutable
        # record is relabelled and no trigger/constraint is bypassed.
        with factory() as db:
            user = db.scalar(select(User))
            db.add(
                ExternalBillingCustomer(
                    customer_id=uuid4(),
                    external_billing_account_id=configuration.lbx_legacy_credential_scope,
                    user_id=user.id,
                    provider_origin=configuration.lbx_provider_origin,
                    billing_customer_key="synthetic-original-customer-key",
                    binding_state=ExternalBillingCustomerBindingState.UNBOUND,
                )
            )
            db.commit()
    original = reserve_customer(factory, configuration, TOKEN)
    claimed = claim_customer_send(factory, configuration, TOKEN, original)
    received = record_customer_receipt(factory, claimed, 345)
    bound = apply_customer_read(factory, received, provider_id="345", outer_key=original.outer_key)
    again = reserve_customer(factory, configuration, TOKEN)
    assert again.customer_id == bound.customer_id and again.provider_id == "345"
    expected_scope = (
        configuration.lbx_legacy_credential_scope if retained_legacy else configuration.lbx_external_billing_account_id
    )
    with factory() as db:
        assert db.get(ExternalBillingCustomer, bound.customer_id).external_billing_account_id == expected_scope
    transport = PurchaseTransport()
    transport.customer = {"user_id": 345, "outer_id": original.outer_key}

    async def reopen_account() -> AccountWidget:
        async with source_resources(configuration, lbx_transport=httpx.MockTransport(transport.respond)) as sources:
            return await bootstrap_account(sources, configuration, factory=factory, token=TOKEN)

    assert asyncio.run(reopen_account()).credential
    assert transport.creates("/users") == 0
    # Customer identity is already proven for this configured origin, even
    # though the user has never had a product link or purchase.
    result = publish(factory, configuration, product="new-product", previous=0)
    assert result.stored.document.scope.external_billing_account_id == expected_scope


def head(
    factory: sessionmaker[Session],
    config: Settings,
    *,
    legacy: bool = False,
    proven: bool = True,
    corrupt: bool = False,
) -> tuple[UUID, ProductLinkDocument]:
    scope = configured_mapping_scope(config)
    if legacy:
        scope = replace(scope, external_billing_account_id=config.lbx_legacy_credential_scope)
    document = link_document(scope=scope, product_revision_number=1)
    revision_id = uuid4()
    with factory() as db:
        db.add(
            CommercialMappingRevision(
                mapping_revision_id=revision_id,
                external_billing_account_id=scope.external_billing_account_id,
                billing_offer_id=document.selection.billing_offer_id,
                revision_number=1,
                manifest_version=document.manifest_version,
                catalog_version=None,
                catalog_digest="sha256:" + "0" * 64 if corrupt else document.identity_digest,
                mapping_schema_version=document.schema_version,
                mapping_document=document.model_dump(mode="json"),
                published_at=document.published_at,
                published_by_principal=document.publisher_principal,
            )
        )
        db.flush()
        db.add(
            CommercialProductHead(
                external_billing_account_id=scope.external_billing_account_id,
                product_id=document.selection.product_id,
                mapping_revision_id=revision_id,
                revision_number=1,
                provider_origin=config.lbx_provider_origin if proven else None,
            )
        )
        db.commit()
    return revision_id, document


def publish_existing(factory: sessionmaker[Session], config: Settings) -> LinkPublicationResult:
    return links.publish_product_link(
        factory,
        evaluation=link_document(),
        expected_previous_revision=1,
        deadline=time.monotonic() + 10,
        lock_timeout_seconds=1,
        provider_origin=config.lbx_provider_origin,
        legacy_account_id=config.lbx_legacy_credential_scope,
    )


def open_account(factory: sessionmaker[Session], config: Settings, transport: PurchaseTransport) -> AccountWidget:
    async def run() -> AccountWidget:
        async with source_resources(config, lbx_transport=httpx.MockTransport(transport.respond)) as sources:
            return await bootstrap_account(sources, config, factory=factory, token=TOKEN)

    return asyncio.run(run())


def test_bound_account_is_independent_of_unrelated_invalid_product_link(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    transport = PurchaseTransport()
    assert open_account(factory, config, transport).credential
    head(factory, config, corrupt=True)
    assert open_account(factory, config, transport).credential
    assert transport.creates("/users") == 1
    # Product-link corruption is still rejected by its own owner.
    with pytest.raises(MappingRefused):
        links.query_product_link(
            factory,
            scope=configured_mapping_scope(config),
            product_id="proposal_ai",
            provider_origin=config.lbx_provider_origin,
            legacy_account_id=config.lbx_legacy_credential_scope,
        )


def test_widget_overlaps_privileged_origin_proof_without_competing_identity(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    revision_id, document = head(factory, config, legacy=True, proven=False)
    transport = PurchaseTransport()
    entered, release = Event(), Event()
    original = links.require_compatible_connection

    def paused(db: Session, *, scope: CommercialScope, product_id: str, deadline: float | None = None) -> None:
        if current_thread().name.startswith("origin-proof"):
            entered.set()
            assert release.wait(5)
        return original(db, scope=scope, product_id=product_id, deadline=deadline)

    monkeypatch.setattr(links, "require_compatible_connection", paused)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="origin-proof") as executor:
        pending = executor.submit(publish_existing, factory, config)
        try:
            assert entered.wait(5)
            # Publication owns origin; a bounded waiter is temporary, not a
            # permanent identity conflict or permission to create another slot.
            with pytest.raises(BillingRefused, match="billing_busy"):
                open_account(factory, config, transport)
            assert transport.creates("/users") == 0
            with factory() as db:
                assert db.scalar(select(func.count()).select_from(ExternalBillingCustomer)) == 0
        finally:
            release.set()
        result = pending.result(timeout=5)
    assert not result.inserted and result.stored.mapping_revision_id == revision_id
    assert open_account(factory, config, transport).credential
    assert transport.creates("/users") == 1
    with factory() as db:
        customer = db.scalar(select(ExternalBillingCustomer))
        assert customer.external_billing_account_id == config.lbx_legacy_credential_scope
        assert db.get(CommercialMappingRevision, revision_id).mapping_document == document.model_dump(mode="json")
        assert db.scalar(select(func.count()).select_from(CommercialMappingRevision)) == 1


def test_real_ambiguous_scope_still_refuses_open_and_publication(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    transport = PurchaseTransport()
    assert open_account(factory, config, transport).credential
    head(factory, config, legacy=True, proven=True)
    with pytest.raises(BillingRefused, match="billing_connection_conflict"):
        open_account(factory, config, transport)
    with pytest.raises(MappingRefused, match="mapping_existing_connection_scope_conflict"):
        publish_existing(factory, config)
    assert transport.creates("/users") == 1
