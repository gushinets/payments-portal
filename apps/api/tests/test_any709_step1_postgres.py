"""PostgreSQL history, populated upgrade and cross-offer product-head CAS."""

from __future__ import annotations

import time
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import func, select, text
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
from apps.api.tests.support.any709_step1 import link_document, link_selection, step1_settings
from app.composition.mapping_operator import configured_mapping_scope
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
    with pytest.raises(MappingRefused, match="mapping_existing_connection_scope_conflict"):
        query_product_link(postgres_session_factory, scope=foreign, product_id="proposal_ai")


def test_any709_step1_restart_and_credential_rotation_preserve_current_link_and_history(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    first = publish(postgres_session_factory, link_document()).stored
    rotated = configured_mapping_scope(step1_settings(lbx_server_username="rotated-user", lbx_server_password="new"))
    assert rotated == first.document.scope
    assert query_product_link(postgres_session_factory, scope=rotated, product_id="proposal_ai") == first
    retry = publish(postgres_session_factory, link_document(scope=rotated))
    assert not retry.inserted and retry.stored == first
    replacement = publish(
        postgres_session_factory, link_document(scope=rotated, selection=link_selection(tariff_id=702)), previous=1
    ).stored
    assert replacement.revision_number == 2
    assert (
        query_link_history(
            postgres_session_factory, scope=rotated, offer_id=first.document.selection.billing_offer_id, revision=1
        )
        == first
    )
    with postgres_session_factory() as db:
        assert db.get(
            CommercialMappingRevision, first.mapping_revision_id
        ).mapping_document == first.document.model_dump(mode="json")
        assert db.scalar(select(func.count()).select_from(CommercialProductHead)) == 1


def test_any709_step1_old_credential_scope_is_diagnosed_without_relabelling_history(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    import hashlib

    legacy_id = (
        "lbx-connection:v1:"
        + hashlib.sha256(
            json.dumps(["https://unknown-origin.test", "unknown-username"], separators=(",", ":")).encode()
        ).hexdigest()
    )
    legacy_scope = replace(link_document().scope, external_billing_account_id=legacy_id)
    first = publish(postgres_session_factory, link_document(scope=legacy_scope)).stored
    before = first.document.model_dump(mode="json")
    for configuration in (step1_settings(), step1_settings(lbx_server_username="rotated-user")):
        scope = configured_mapping_scope(configuration)
        with pytest.raises(MappingRefused, match="mapping_existing_connection_scope_conflict"):
            query_product_link(
                postgres_session_factory,
                scope=scope,
                product_id="proposal_ai",
                provider_origin=configuration.lbx_provider_origin,
                legacy_account_id=configuration.lbx_legacy_credential_scope,
            )
        with pytest.raises(MappingRefused, match="mapping_existing_connection_scope_conflict"):
            publish(postgres_session_factory, link_document(scope=scope))
    assert (
        query_link_history(
            postgres_session_factory,
            scope=link_document().scope,
            offer_id=first.document.selection.billing_offer_id,
            revision=1,
        )
        == first
    )
    with postgres_session_factory() as db:
        assert db.get(CommercialMappingRevision, first.mapping_revision_id).mapping_document == before
        assert db.scalar(select(func.count()).select_from(CommercialMappingRevision)) == 1


def test_any709_step1_multiple_proven_scopes_are_a_conflict_instead_of_an_arbitrary_alias(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    configuration = step1_settings()
    first = publish(postgres_session_factory, link_document()).stored
    other_scope = replace(first.document.scope, external_billing_account_id="other-real-binding")
    second = publish(
        postgres_session_factory,
        link_document(scope=other_scope, selection=link_selection(product_id="other-product")),
    ).stored
    with postgres_session_factory() as db:
        for stored in (first, second):
            db.get(
                CommercialProductHead,
                (stored.document.scope.external_billing_account_id, stored.document.selection.product_id),
            ).provider_origin = configuration.lbx_provider_origin
        db.commit()
    with pytest.raises(MappingRefused, match="mapping_existing_connection_scope_conflict"):
        query_product_link(
            postgres_session_factory,
            scope=first.document.scope,
            product_id="proposal_ai",
            provider_origin=configuration.lbx_provider_origin,
            legacy_account_id=configuration.lbx_legacy_credential_scope,
        )


@pytest.mark.parametrize("commit_reached_server", [True, False])
def test_any709_step1_origin_binding_lost_ack_never_replays_an_association(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    commit_reached_server: bool,
) -> None:
    first = publish(postgres_session_factory, link_document()).stored
    configuration = step1_settings()
    attempts = 0

    class LostAcknowledgement(Session):
        def commit(self) -> None:
            nonlocal attempts
            attempts += 1
            if commit_reached_server:
                super().commit()
            raise OperationalError("COMMIT", None, RuntimeError("Isolated lost origin-binding acknowledgement"))

    factory = sessionmaker(bind=migrated_database, class_=LostAcknowledgement, autoflush=False)
    with pytest.raises(MappingCommitUncertain):
        publish_product_link(
            factory,
            evaluation=link_document(),
            expected_previous_revision=1,
            deadline=time.monotonic() + 5,
            lock_timeout_seconds=1,
            provider_origin=configuration.lbx_provider_origin,
            legacy_account_id=configuration.lbx_legacy_credential_scope,
        )
    assert attempts == 1
    with postgres_session_factory() as db:
        head = db.get(CommercialProductHead, (first.document.scope.external_billing_account_id, "proposal_ai"))
        assert head.mapping_revision_id == first.mapping_revision_id and head.revision_number == 1
        assert head.provider_origin == (configuration.lbx_provider_origin if commit_reached_server else None)
        assert db.scalar(select(func.count()).select_from(CommercialMappingRevision)) == 1


def test_any709_step1_populated_upgrade_preserves_mapping_and_legacy_scope_through_rotation(
    postgres_engine: Engine,
    database_test_url: URL,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    reset_public_schema(postgres_engine)
    configuration = step1_settings()
    scope = replace(link_document().scope, external_billing_account_id=configuration.lbx_legacy_credential_scope)
    document = link_document(scope=scope, product_revision_number=1)
    revision_id = uuid4()
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "20261001_0002")
        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO commercial_mapping_revisions "
                    "(mapping_revision_id, external_billing_account_id, billing_offer_id, revision_number, manifest_version, "
                    "catalog_digest, mapping_schema_version, mapping_document, published_at, published_by_principal) "
                    "VALUES (:id, :account, :offer, 1, :manifest, :digest, 'product-link-v2', CAST(:document AS jsonb), :published, :principal)"
                ),
                {
                    "id": revision_id,
                    "account": scope.external_billing_account_id,
                    "offer": document.selection.billing_offer_id,
                    "manifest": document.manifest_version,
                    "digest": document.identity_digest,
                    "document": document.model_dump_json(),
                    "published": document.published_at,
                    "principal": document.publisher_principal,
                },
            )
        command.upgrade(config, "head")
        with postgres_engine.begin() as connection:
            # Consolidation must not adopt the immutable predecessor mapping.
            assert connection.execute(text("SELECT count(*) FROM commercial_product_heads")).scalar_one() == 0
            connection.execute(
                text(
                    "INSERT INTO commercial_product_heads (external_billing_account_id, product_id, mapping_revision_id, revision_number) "
                    "VALUES (:account, 'proposal_ai', :id, 1)"
                ),
                {"account": scope.external_billing_account_id, "id": revision_id},
            )
    with postgres_session_factory() as db:
        head = db.get(CommercialProductHead, (scope.external_billing_account_id, "proposal_ai"))
        assert head.provider_origin is None  # The migration guessed no provenance.
        before = db.get(CommercialMappingRevision, revision_id).mapping_document
    current_scope = configured_mapping_scope(configuration)
    known = query_product_link(
        postgres_session_factory,
        scope=current_scope,
        product_id="proposal_ai",
        provider_origin=configuration.lbx_provider_origin,
        legacy_account_id=configuration.lbx_legacy_credential_scope,
    )
    assert known.mapping_revision_id == revision_id and known.document.scope == scope
    result = publish_product_link(
        postgres_session_factory,
        evaluation=link_document(),
        expected_previous_revision=1,
        deadline=time.monotonic() + 5,
        lock_timeout_seconds=1,
        provider_origin=configuration.lbx_provider_origin,
        legacy_account_id=configuration.lbx_legacy_credential_scope,
    )
    assert not result.inserted and result.stored == known
    rotated = step1_settings(lbx_server_username="rotated-user", lbx_server_password="new-password")
    read = query_product_link(
        postgres_session_factory,
        scope=configured_mapping_scope(rotated),
        product_id="proposal_ai",
        provider_origin=rotated.lbx_provider_origin,
        legacy_account_id=rotated.lbx_legacy_credential_scope,
    )
    assert read == known
    retry = publish_product_link(
        postgres_session_factory,
        evaluation=link_document(scope=configured_mapping_scope(rotated)),
        expected_previous_revision=1,
        deadline=time.monotonic() + 5,
        lock_timeout_seconds=1,
        provider_origin=rotated.lbx_provider_origin,
        legacy_account_id=rotated.lbx_legacy_credential_scope,
    )
    assert not retry.inserted and retry.stored == known
    other = publish_product_link(
        postgres_session_factory,
        evaluation=link_document(selection=link_selection(product_id="other-product", tariff_id=702)),
        expected_previous_revision=0,
        deadline=time.monotonic() + 5,
        lock_timeout_seconds=1,
        provider_origin=rotated.lbx_provider_origin,
        legacy_account_id=rotated.lbx_legacy_credential_scope,
    )
    assert other.stored.document.scope == scope
    assert (
        query_link_history(
            postgres_session_factory, scope=current_scope, offer_id=document.selection.billing_offer_id, revision=1
        )
        == known
    )
    foreign = step1_settings(lbx_base_url="https://different-origin.test")
    with pytest.raises(MappingRefused, match="mapping_existing_connection_scope_conflict"):
        query_product_link(
            postgres_session_factory,
            scope=configured_mapping_scope(foreign),
            product_id="proposal_ai",
            provider_origin=foreign.lbx_provider_origin,
            legacy_account_id=foreign.lbx_legacy_credential_scope,
        )
    with postgres_session_factory() as db:
        assert db.get(CommercialMappingRevision, revision_id).mapping_document == before
        assert (
            db.get(CommercialProductHead, (scope.external_billing_account_id, "proposal_ai")).provider_origin
            == configuration.lbx_provider_origin
        )
        assert db.scalar(select(func.count()).select_from(CommercialProductHead)) == 2
        assert db.scalar(select(func.count()).select_from(CommercialMappingRevision)) == 2


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


def test_any709_step1_offer_cannot_have_two_current_products(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    first = publish(postgres_session_factory, link_document()).stored
    with pytest.raises(MappingRefused, match="mapping_offer_product_conflict"):
        publish(postgres_session_factory, link_document(selection=link_selection(product_id="other_product")))
    with postgres_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(CommercialProductHead)) == 1
        assert db.scalar(select(func.count()).select_from(CommercialMappingRevision)) == 1
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
    assert dry["operator_audit"]["execution_principal"] == "os-euid:29001"
    assert dry["evaluation"]["publisher_principal"] == "os-euid:29001"
    monkeypatch.setattr(database, "SessionLocal", postgres_session_factory)
    result = cli.execute(
        cli.parser().parse_args(["publish", *args, "--expected-previous-revision", "0"]), configuration
    )
    assert json.loads(result)["inserted"]
    assert json.loads(result)["operator_audit"]["execution_principal"] == "os-euid:29001"
    assert json.loads(result)["document"]["publisher_principal"] == "os-euid:29001"
    assert all(secret not in result for secret in (PASSWORD, USERNAME, "isolated-test-widget-secret"))
    monkeypatch.setattr(mapping_operator.os, "geteuid", lambda: 42)
    offline = step1_settings(
        lbx_server_username="", lbx_server_password="", kernel_base_url="", kernel_service_token=""
    )
    queried = json.loads(cli.execute(cli.parser().parse_args(["query", "--product-id", "proposal_ai"]), offline))
    assert queried["mapping_revision_id"] == json.loads(result)["mapping_revision_id"]
    assert queried["revision_number"] == 1 and queried["document"]["schema_version"] == "product-link-v2"
    assert queried["operator_audit"]["execution_principal"] == "os-euid:42"
    assert queried["document"]["publisher_principal"] == "os-euid:29001"
    rotated = step1_settings(
        lbx_server_username="rotated-user",
        lbx_server_password="rotated-password",
        mapping_operator_lock_file=tmp_path / "operator.lock",
    )
    repeated = json.loads(
        cli.execute(cli.parser().parse_args(["publish", *args, "--expected-previous-revision", "1"]), rotated)
    )
    assert repeated["inserted"] is False and repeated["mapping_revision_id"] == queried["mapping_revision_id"]
    history = json.loads(
        cli.execute(
            cli.parser().parse_args(["query", "--offer-id", repeated["billing_offer_id"], "--revision", "1"]), rotated
        )
    )
    assert history["mapping_revision_id"] == queried["mapping_revision_id"]
    assert repeated["operator_audit"]["execution_principal"] == "os-euid:42"
    assert history["operator_audit"]["execution_principal"] == "os-euid:42"
    assert history["document"] == queried["document"]
