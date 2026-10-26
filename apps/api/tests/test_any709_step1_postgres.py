"""PostgreSQL history, populated upgrade and cross-offer product-head CAS."""

from __future__ import annotations

import time
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import func, select
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.domains.catalog.link_publication import (
    LinkPublicationResult,
    publish_product_link,
    query_link_history,
    query_product_link,
)
from app.domains.catalog.mapping_evidence import MappingRefused
from app.domains.catalog.product_link import ProductLinkDocument
from app.domains.catalog.publication import MappingCommitUncertain, MappingRevisionConflict, publish_mapping
from app.models import (
    CommercialMappingRevision,
    CommercialProductHead,
    ExternalBillingCustomer,
    PurchaseIntent,
    ExternalSubscription,
)
from apps.api.tests.support.any709_step1 import link_document, link_selection
from apps.api.tests.support.commercial_mappings import fresh_fixture, reviewed_fixture
from apps.api.tests.support.postgres import alembic_test_config, reset_public_schema


pytestmark = [pytest.mark.postgres, pytest.mark.anyio, pytest.mark.usefixtures("mapping_clock")]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def publish(factory: sessionmaker[Session], document: ProductLinkDocument, previous: int = 0) -> LinkPublicationResult:
    return publish_product_link(
        factory,
        evaluation=document,
        expected_previous_revision=previous,
        deadline=time.monotonic() + 5,
        lock_timeout_seconds=1,
    )


def test_any709_step1_publish_query_identical_retry_and_retarget_preserve_pins(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    first = publish(postgres_session_factory, link_document()).stored
    retry = publish(postgres_session_factory, link_document())
    assert not retry.inserted and retry.stored == first
    next_document = link_document(selection=link_selection(tariff_id=702))
    with pytest.raises(MappingRevisionConflict):
        publish(postgres_session_factory, next_document)
    second = publish(postgres_session_factory, next_document, previous=1).stored
    assert second.revision_number == 2 and second.mapping_revision_id != first.mapping_revision_id
    assert query_product_link(postgres_session_factory, scope=second.document.scope, product_id="proposal_ai") == second
    old = query_link_history(
        postgres_session_factory,
        scope=first.document.scope,
        offer_id=first.document.selection.billing_offer_id,
        revision=first.offer_revision_number,
    )
    assert old == first
    # Retargeting back appends a new pin. It does not reuse/rewrite an old row.
    third = publish(postgres_session_factory, link_document(), previous=2).stored
    assert third.revision_number == 3 and third.offer_revision_number == 2
    with postgres_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(CommercialProductHead)) == 1
        assert db.scalar(select(func.count()).select_from(CommercialMappingRevision)) == 3
        for model in (ExternalBillingCustomer, PurchaseIntent, ExternalSubscription):
            assert db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize("identical", [True, False])
def test_any709_step1_concurrent_first_publication_is_product_scoped(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    identical: bool,
) -> None:
    first = link_document()
    second = first if identical else link_document(selection=link_selection(tariff_id=702))

    def attempt(document: ProductLinkDocument) -> LinkPublicationResult | MappingRevisionConflict:
        try:
            return publish(postgres_session_factory, document)
        except MappingRevisionConflict as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (first, second)))
    successes = [result for result in results if isinstance(result, LinkPublicationResult)]
    assert len(successes) == (2 if identical else 1)
    assert sum(result.inserted for result in successes) == 1
    with postgres_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(CommercialProductHead)) == 1
        assert db.scalar(select(func.count()).select_from(CommercialMappingRevision)) == 1


def test_any709_step1_product_head_unique_and_foreign_account_pin_refused(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    stored = publish(postgres_session_factory, link_document()).stored
    with postgres_session_factory() as db:
        db.add(
            CommercialProductHead(
                external_billing_account_id="other-connection",
                product_id="proposal_ai",
                mapping_revision_id=stored.mapping_revision_id,
                revision_number=1,
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    foreign = replace(stored.document.scope, external_billing_account_id="another-proven-connection")
    with pytest.raises(MappingRefused, match="mapping_existing_connection_scope_conflict"):
        publish(postgres_session_factory, link_document(scope=foreign))


async def test_any709_step1_populated_baseline_upgrade_preserves_v1_without_synthetic_promotion(
    postgres_engine: Engine,
    database_test_url: URL,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    reset_public_schema(postgres_engine)
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "20261001_0002")
    fresh = await fresh_fixture(await reviewed_fixture())
    old = publish_mapping(
        postgres_session_factory,
        evaluation=fresh.document,
        expected_previous_revision=0,
        deadline=fresh.deadline,
        evidence_valid_until=fresh.evidence_valid_until,
        lock_timeout_seconds=1,
        allow_simulated=True,
    ).stored
    before = old.document.model_dump(mode="json")
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "head")
    with postgres_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(CommercialProductHead)) == 0
        assert db.get(CommercialMappingRevision, old.mapping_revision_id).mapping_document == before
    read = query_link_history(
        postgres_session_factory,
        scope=old.document.material.scope,
        offer_id=old.document.material.billing_offer_id,
        revision=old.revision_number,
    )
    assert read == old
    assert (
        query_product_link(postgres_session_factory, scope=old.document.material.scope, product_id="proposal_ai")
        is None
    )
    new = publish(postgres_session_factory, link_document()).stored
    assert new.revision_number == 1 and new.offer_revision_number == 2
    assert new.document.lbx_evidence_mode == "CONFIGURED_SOURCE"
    assert old.document.evidence_mode == "SIMULATED"
    assert (
        query_link_history(
            postgres_session_factory,
            scope=old.document.material.scope,
            offer_id=old.document.material.billing_offer_id,
            revision=1,
        )
        == old
    )


def test_any709_step1_two_products_can_share_offer_without_head_or_revision_collision(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    first = publish(postgres_session_factory, link_document()).stored
    other = publish(
        postgres_session_factory, link_document(selection=link_selection(product_id="other_product"))
    ).stored
    assert first.offer_revision_number == 1 and other.offer_revision_number == 2
    assert first.revision_number == other.revision_number == 1
    assert query_product_link(postgres_session_factory, scope=first.document.scope, product_id="proposal_ai") == first


@pytest.mark.parametrize("commit_reached_server", [True, False])
def test_any709_step1_lost_commit_acknowledgement_reads_without_replaying(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    commit_reached_server: bool,
) -> None:
    attempts = 0

    class LostAcknowledgement(Session):
        def commit(self) -> None:
            nonlocal attempts
            attempts += 1
            if commit_reached_server:
                super().commit()
            raise OperationalError("COMMIT", None, RuntimeError("Isolated lost acknowledgement"))

    factory = sessionmaker(bind=migrated_database, class_=LostAcknowledgement, autoflush=False)
    if commit_reached_server:
        result = publish(factory, link_document())
        assert result.recovered_commit
        assert (
            query_product_link(postgres_session_factory, scope=result.stored.document.scope, product_id="proposal_ai")
            == result.stored
        )
    else:
        with pytest.raises(MappingCommitUncertain):
            publish(factory, link_document())
    assert attempts == 1
    with postgres_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(CommercialProductHead)) == int(commit_reached_server)
        assert db.scalar(select(func.count()).select_from(CommercialMappingRevision)) == int(commit_reached_server)


def test_any709_step1_direct_cli_dry_run_publish_query_and_secret_redaction(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import httpx
    from datetime import UTC, datetime

    from app.cli import commercial_mappings as cli
    from app.composition import mapping_operator
    from app.composition.mapping_operator import FreshLinkEvaluation
    from app.core import database
    from apps.api.tests.support.any709_step1 import recording, step1_settings
    from apps.api.tests.support.kernel import manifest_fixture
    from apps.api.tests.support.lbx import PASSWORD, USERNAME

    configuration = step1_settings(mapping_operator_lock_file=tmp_path / "operator.lock")
    source = recording()
    original = mapping_operator.fresh_link_evaluation

    async def configured(*args: object, **kwargs: object) -> FreshLinkEvaluation:
        return await original(
            *args,
            **kwargs,
            kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=manifest_fixture())),
            lbx_transport=httpx.MockTransport(source.respond),
        )

    monkeypatch.setattr(cli, "fresh_link_evaluation", configured)
    monkeypatch.setattr(mapping_operator.os, "geteuid", lambda: 29001)
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 26, tzinfo=UTC))
    args = ["--product-id", "proposal_ai", "--tariff-id", "701", "--tariff-service-id", "1001", "--period-id", "901"]

    def no_database() -> Session:
        raise AssertionError("dry-run opened a database")

    monkeypatch.setattr(database, "SessionLocal", no_database)
    dry = json.loads(cli.execute(cli.parser().parse_args(["dry-run", *args]), configuration))
    assert dry["persisted"] is False and dry["current_offer"]["money"]["recurring_amount"] == "100.01"
    monkeypatch.setattr(database, "SessionLocal", postgres_session_factory)
    result = cli.execute(
        cli.parser().parse_args(["publish", *args, "--expected-previous-revision", "0"]), configuration
    )
    assert json.loads(result)["inserted"]
    assert all(secret not in result for secret in (PASSWORD, USERNAME, "isolated-test-widget-secret"))
    offline = step1_settings(lbx_server_password="", kernel_base_url="", kernel_service_token="")
    queried = json.loads(cli.execute(cli.parser().parse_args(["query", "--product-id", "proposal_ai"]), offline))
    assert queried["mapping_revision_id"] == json.loads(result)["mapping_revision_id"]
    assert queried["revision_number"] == 1 and queried["document"]["schema_version"] == "product-link-v2"
