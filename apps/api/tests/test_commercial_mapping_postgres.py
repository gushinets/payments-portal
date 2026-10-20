from __future__ import annotations

import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.cli import commercial_mappings as cli
from app.composition import mapping_operator
from app.composition.mapping_operator import FreshMappingEvaluation, fresh_mapping_evaluation
from app.core.settings import AppEnv, Settings
from app.domains.catalog.mapping_evidence import MappingDocument, MappingRefused
from app.domains.catalog.publication import (
    MappingCommitUncertain,
    MappingRevisionConflict,
    PublicationResult,
    StoredMapping,
    publish_mapping,
    query_mapping,
    validate_stored_mapping,
)
from app.infrastructure.persistence.commercial_mappings import (
    MappingStorageBusy,
    MappingStorageDeadline,
    lock_mapping_scope,
)
from app.infrastructure.preflight import PreflightAdmission, PreflightPolicy, PreflightSaturated
from app.integrations.kernel.client import KernelUnavailable
from app.models import CommercialMappingRevision
from apps.api.tests.support.commercial_mappings import (
    SIMULATED_OFFER_ID,
    SIMULATED_UID,
    fresh_fixture,
    operator_settings,
    reviewed_fixture,
)
from apps.api.tests.support.kernel import manifest_fixture, resign
from apps.api.tests.support.lbx import PASSWORD, USERNAME
from apps.api.tests.support.lbx import TOKEN as LBX_TOKEN
from apps.api.tests.support.lbx_selected_offer import SelectedOfferRecording, simulated_inputs, simulated_selection


pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def publish(factory: sessionmaker[Session], fresh: FreshMappingEvaluation, *, previous: int = 0) -> PublicationResult:
    return publish_mapping(
        factory,
        evaluation=fresh.document,
        expected_previous_revision=previous,
        deadline=fresh.deadline,
        lock_timeout_seconds=0.2,
        allow_simulated=True,
    )


async def test_real_clients_publish_queryable_immutable_simulated_row(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = await reviewed_fixture()
    fresh = await fresh_fixture(reviewed)
    result = publish(postgres_session_factory, fresh)
    assert result.inserted and result.stored.revision_number == 1
    scope = fresh.document.material.scope
    saved = query_mapping(postgres_session_factory, scope=scope, offer_id=SIMULATED_OFFER_ID, allow_simulated=True)
    assert saved == result.stored
    assert saved.document.publisher_principal == f"os-euid:{SIMULATED_UID}"
    assert saved.document.material.digest_scope == "selected_offer"
    assert saved.document.material.technical.allowance == 25
    assert saved.document.evidence_mode == saved.document.publication_state == "SIMULATED"

    # The actual CLI query dispatch works with neither source configured while a
    # completely full source owner rejects fresh work. No resource may be built.
    from app.core import database

    monkeypatch.setattr(database, "SessionLocal", postgres_session_factory)
    monkeypatch.setattr(mapping_operator.os, "geteuid", lambda: SIMULATED_UID)

    async def forbidden_sources(*args: object, **kwargs: object) -> FreshMappingEvaluation:
        raise AssertionError("DB-only query constructed source evaluation")

    monkeypatch.setattr(mapping_operator, "fresh_mapping_evaluation", forbidden_sources)
    offline = operator_settings(
        kernel_base_url="",
        kernel_service_token="",
        lbx_base_url="",
        lbx_external_billing_account_id="",
        lbx_server_username="",
        lbx_server_password="",
    )
    owner = PreflightAdmission(PreflightPolicy(10, 0.1, 1, 0))
    try:
        async with owner.operation():
            with pytest.raises(PreflightSaturated):
                async with owner.operation():
                    raise AssertionError("saturated admission unexpectedly allowed work")
            output = json.loads(
                cli.execute(cli.parser().parse_args(["query", "--offer-id", SIMULATED_OFFER_ID]), offline)
            )
            assert output["revision_number"] == 1
    finally:
        await owner.aclose()
    with pytest.raises(KernelUnavailable):
        await fresh_mapping_evaluation(
            operator_settings(),
            proposal=reviewed.proposal,
            approval=reviewed.approval,
            source_inputs=simulated_inputs(),
            principal=f"os-euid:{SIMULATED_UID}",
            kernel_transport=httpx.MockTransport(lambda request: httpx.Response(503)),
            lbx_transport=httpx.MockTransport(SelectedOfferRecording().respond),
        )
    assert (
        query_mapping(postgres_session_factory, scope=scope, offer_id=SIMULATED_OFFER_ID, allow_simulated=True) == saved
    )


async def test_identical_fresh_retry_returns_original_evidence(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    reviewed = await reviewed_fixture()
    first = publish(postgres_session_factory, await fresh_fixture(reviewed))
    payload = manifest_fixture()
    next(item for item in payload["products"] if item["product_id"] != "proposal_ai")["enabled"] = True
    second = publish(postgres_session_factory, await fresh_fixture(reviewed, manifest=resign(payload)), previous=0)
    assert not second.inserted
    assert second.stored == first.stored
    assert second.evaluation.evaluated_at != second.stored.document.evaluated_at
    assert second.evaluation.manifest_version != second.stored.document.manifest_version
    with postgres_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(CommercialMappingRevision)) == 1


async def test_two_services_in_one_tariff_have_independent_revision_histories(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TwoServicesRecording(SelectedOfferRecording):
        def __init__(self, default_component: int) -> None:
            super().__init__()
            # Extend the isolated recording without float-decoding fixture money
            # or changing Step 4's reader/normalizer or existing fixture owners.
            body = self.bodies["services"].rstrip()
            prefix = b'{"code":200,"response":['
            assert body.startswith(prefix) and body.endswith(b"]}")
            service = body[len(prefix) : -2].decode("utf-8")
            self.append_row(
                "services",
                service.replace('"tariff_service_id":1001', '"tariff_service_id":1002').replace(
                    '"enabled_by_default":1', f'"enabled_by_default":{int(default_component == 1002)}'
                ),
            )
            if default_component == 1002:
                # Change only the first row; the second default stays explicit.
                self.bodies["services"] = self.bodies["services"].replace(
                    b'"enabled_by_default":1', b'"enabled_by_default":0', 1
                )

        def respond(self, request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/services/1002/prices"):
                recorded_url = request.url.copy_with(
                    path=request.url.path.replace("/services/1002/prices", "/services/1001/prices")
                )
                response = super().respond(httpx.Request("GET", recorded_url, headers=request.headers))
                return httpx.Response(
                    200,
                    content=response.content.replace(b'"price_id":13', b'"price_id":23'),
                    headers={"Content-Type": "application/json"},
                )
            return super().respond(request)

    first_recording = TwoServicesRecording(1001)
    second_recording = TwoServicesRecording(1002)
    second_selection = simulated_selection().model_copy(update={"tariff_service_id": 1002})
    second_inputs = simulated_inputs()
    assert second_inputs.policy is not None
    second_inputs = second_inputs.model_copy(
        update={
            "policy": second_inputs.policy.model_copy(update={"tariff_service_id": 1002}),
        }
    )
    first = await reviewed_fixture(recording=first_recording)
    second = await reviewed_fixture(recording=second_recording, selection=second_selection, source_inputs=second_inputs)
    second_id = "selected-offer:v1:701:1002:901"
    # The provider can change its default between independent publications;
    # each publication still admits exactly its one selected default service.
    cases = (
        (first, first_recording, simulated_inputs(), SIMULATED_OFFER_ID),
        (second, second_recording, second_inputs, second_id),
    )
    saved: dict[str, StoredMapping] = {}
    for reviewed, recording, source_inputs, offer_id in cases:
        fresh = await fresh_fixture(reviewed, recording=recording, source_inputs=source_inputs)
        assert fresh.document.material.billing_offer_id == offer_id
        assert fresh.document.material.references.offer == "701"
        result = publish(postgres_session_factory, fresh, previous=0)
        assert result.inserted and result.stored.revision_number == 1
        saved[offer_id] = result.stored
    assert saved[SIMULATED_OFFER_ID].mapping_revision_id != saved[second_id].mapping_revision_id

    from app.core import database

    monkeypatch.setattr(database, "SessionLocal", postgres_session_factory)
    monkeypatch.setattr(mapping_operator.os, "geteuid", lambda: SIMULATED_UID)
    scope = first.approval.material.scope
    for reviewed, recording, source_inputs, offer_id in cases:
        assert (
            query_mapping(postgres_session_factory, scope=scope, offer_id=offer_id, allow_simulated=True)
            == saved[offer_id]
        )
        queried = json.loads(
            cli.execute(cli.parser().parse_args(["query", "--offer-id", offer_id]), operator_settings())
        )
        assert queried["billing_offer_id"] == offer_id
        assert queried["revision_number"] == 1
        fresh = await fresh_fixture(reviewed, recording=recording, source_inputs=source_inputs)
        repeated = publish(postgres_session_factory, fresh, previous=0)
        assert not repeated.inserted and repeated.stored == saved[offer_id]
    with postgres_session_factory() as db:
        rows = db.scalars(select(CommercialMappingRevision)).all()
        assert {(row.billing_offer_id, row.revision_number) for row in rows} == {
            (SIMULATED_OFFER_ID, 1),
            (second_id, 1),
        }
        assert len(rows) == 2


async def test_stored_mapping_rejects_tariff_only_offer_alias(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    result = publish(postgres_session_factory, await fresh_fixture(await reviewed_fixture()))
    with postgres_session_factory() as db:
        row = db.get(CommercialMappingRevision, result.stored.mapping_revision_id)
        assert row is not None
        # In-memory invalid input only; immutable history is never updated.
        row.billing_offer_id = row.mapping_document["material"]["references"]["offer"]
        with pytest.raises(MappingRefused, match="mapping_stored_scope_or_evidence_mismatch"):
            validate_stored_mapping(
                row, scope=result.stored.document.material.scope, offer_id="701", allow_simulated=True
            )


async def test_stale_changed_material_conflicts_then_separately_approved_revision_retains_history(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    original = await reviewed_fixture()
    first = publish(postgres_session_factory, await fresh_fixture(original))
    replacement = await reviewed_fixture(allowance=26, revision="fixture-v2")
    with pytest.raises(MappingRevisionConflict):
        publish(postgres_session_factory, await fresh_fixture(replacement), previous=0)
    second = publish(postgres_session_factory, await fresh_fixture(replacement), previous=1)
    assert second.stored.revision_number == 2
    assert second.stored.document.material.technical.allowance == 26
    old = query_mapping(
        postgres_session_factory,
        scope=first.stored.document.material.scope,
        offer_id=SIMULATED_OFFER_ID,
        revision=1,
        allow_simulated=True,
    )
    assert old == first.stored


async def test_changed_material_cannot_reuse_original_approval_revision(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    original = await reviewed_fixture()
    publish(postgres_session_factory, await fresh_fixture(original))
    # Even an edited approval artifact with a new matching material hash cannot
    # claim the unchanged immutable technical approval approved a new quantity.
    repackaged = await reviewed_fixture(allowance=26)
    with pytest.raises(MappingRefused, match="mapping_technical_reapproval_required"):
        publish(postgres_session_factory, await fresh_fixture(repackaged), previous=1)


async def test_changed_price_needs_legal_reapproval_before_append(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    original = await reviewed_fixture()
    first = publish(postgres_session_factory, await fresh_fixture(original))
    recording = SelectedOfferRecording()
    for name in ("services", "prices"):
        recording.replace(name, '"price":100.01', '"price":120.01')
    replacement = await reviewed_fixture(recording=recording, revision="fixture-v2")
    revisions = replacement.approval.revisions.model_copy(update={"legal": original.approval.revisions.legal})
    repackaged = replace(replacement, approval=replacement.approval.model_copy(update={"revisions": revisions}))
    with pytest.raises(MappingRefused, match="mapping_legal_reapproval_required"):
        publish(postgres_session_factory, await fresh_fixture(repackaged, recording=recording), previous=1)
    assert (
        query_mapping(
            postgres_session_factory,
            scope=first.stored.document.material.scope,
            offer_id=SIMULATED_OFFER_ID,
            allow_simulated=True,
        )
        == first.stored
    )
    second = publish(postgres_session_factory, await fresh_fixture(replacement, recording=recording), previous=1)
    assert second.inserted and second.stored.revision_number == 2
    assert second.stored.document.approvals.legal != first.stored.document.approvals.legal


@pytest.mark.parametrize("identical", [True, False])
async def test_competing_first_publishers_are_serialized_and_deterministic(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    identical: bool,
) -> None:
    reviewed = await reviewed_fixture()
    first = await fresh_fixture(reviewed)
    other = reviewed if identical else await reviewed_fixture(allowance=30, revision="other-review")
    second = await fresh_fixture(other)
    barrier = threading.Barrier(2)

    def contender(fresh: FreshMappingEvaluation) -> PublicationResult | MappingRevisionConflict:
        barrier.wait(timeout=2)
        try:
            return publish(postgres_session_factory, fresh)
        except MappingRevisionConflict as conflict:
            return conflict

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(contender, fresh) for fresh in (first, second)]
        results = [future.result(timeout=5) for future in futures]
    successes = [item for item in results if isinstance(item, PublicationResult)]
    assert sum(item.inserted for item in successes) == 1
    assert len(successes) == (2 if identical else 1)
    assert sum(isinstance(item, MappingRevisionConflict) for item in results) == (0 if identical else 1)
    with postgres_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(CommercialMappingRevision)) == 1


async def test_lock_wait_and_expired_preflight_are_bounded_without_insert(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    reviewed = await reviewed_fixture()
    fresh = await fresh_fixture(reviewed)
    with postgres_session_factory() as holder:
        lock_mapping_scope(
            holder, account_id=fresh.document.material.scope.external_billing_account_id, offer_id=SIMULATED_OFFER_ID
        )
        with pytest.raises(MappingStorageBusy):
            publish(postgres_session_factory, fresh)
        holder.rollback()
    with pytest.raises(MappingStorageDeadline):
        publish(postgres_session_factory, replace(fresh, deadline=time.monotonic() - 1))
    with postgres_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(CommercialMappingRevision)) == 0


async def test_failure_after_insert_rolls_back_without_losing_history(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    first = publish(postgres_session_factory, await fresh_fixture(await reviewed_fixture()))

    class FailAfterFlush(Session):
        def flush(self, objects: object = None) -> None:
            super().flush(objects)
            raise RuntimeError("SIMULATED: post-insert failure")

    factory = sessionmaker(bind=migrated_database, class_=FailAfterFlush, autoflush=False)
    replacement = await reviewed_fixture(allowance=26, revision="fixture-v2")
    with pytest.raises(RuntimeError, match="post-insert failure"):
        publish(factory, await fresh_fixture(replacement), previous=1)
    assert (
        query_mapping(
            postgres_session_factory,
            scope=first.stored.document.material.scope,
            offer_id=SIMULATED_OFFER_ID,
            allow_simulated=True,
        )
        == first.stored
    )


@pytest.mark.parametrize("mutation", ["update", "delete"])
async def test_existing_postgres_guards_reject_update_and_delete(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    mutation: str,
) -> None:
    first = publish(postgres_session_factory, await fresh_fixture(await reviewed_fixture()))
    with postgres_session_factory() as db:
        statement = (
            update(CommercialMappingRevision).values(mapping_document={})
            if mutation == "update"
            else delete(CommercialMappingRevision)
        )
        with pytest.raises(DBAPIError, match="commercial mapping revisions are immutable"):
            db.execute(
                statement.where(CommercialMappingRevision.mapping_revision_id == first.stored.mapping_revision_id)
            )
        db.rollback()
    assert (
        query_mapping(
            postgres_session_factory,
            scope=first.stored.document.material.scope,
            offer_id=SIMULATED_OFFER_ID,
            allow_simulated=True,
        )
        == first.stored
    )


async def test_simulation_remains_excluded_after_environment_or_endpoint_switch(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = await reviewed_fixture()
    fresh = await fresh_fixture(reviewed)
    first = publish(postgres_session_factory, fresh)
    switched_endpoint = await fresh_fixture(
        reviewed, configuration=operator_settings(kernel_base_url="http://compatible-local-source.test")
    )
    assert publish(postgres_session_factory, switched_endpoint).stored == first.stored
    with pytest.raises(MappingRefused, match="mapping_simulation_forbidden"):
        query_mapping(postgres_session_factory, scope=fresh.document.material.scope, offer_id=SIMULATED_OFFER_ID)
    from app.core import database

    monkeypatch.setattr(database, "SessionLocal", postgres_session_factory)
    monkeypatch.setattr(mapping_operator.os, "geteuid", lambda: SIMULATED_UID)
    switched = operator_settings(
        app_env=AppEnv.PRODUCTION,
        app_public_base_url="https://portal.example.com",
        cors_allow_origins=("https://portal.example.com",),
        kernel_base_url="",
        kernel_service_token="",
        lbx_base_url="",
        lbx_external_billing_account_id="",
        lbx_server_username="",
        lbx_server_password="",
    )
    with pytest.raises(MappingRefused, match="mapping_simulation_forbidden"):
        cli.execute(cli.parser().parse_args(["query", "--offer-id", SIMULATED_OFFER_ID]), switched)


@pytest.mark.parametrize("invalid", ["schema", "mode", "scope"])
async def test_invalid_latest_never_falls_back_but_explicit_history_is_queryable(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    invalid: str,
) -> None:
    fresh = await fresh_fixture(await reviewed_fixture())
    first = publish(postgres_session_factory, fresh)
    document = first.stored.document.model_dump(mode="json")
    if invalid == "schema":
        document["schema_version"] = "unsupported"
    elif invalid == "mode":
        document["evidence_mode"] = "UNKNOWN"
    else:
        document["material"]["scope"]["tenant_id"] = "foreign"
    with postgres_session_factory() as db:
        # Malformed row tests storage validation only. Positive rows above always
        # come through real source clients/evaluator/transaction, never hand SQL.
        db.add(
            CommercialMappingRevision(
                external_billing_account_id=fresh.document.material.scope.external_billing_account_id,
                billing_offer_id=SIMULATED_OFFER_ID,
                revision_number=2,
                manifest_version=fresh.document.manifest_version,
                catalog_digest=fresh.document.material.selected_evidence_digest,
                mapping_schema_version="approved-offer-v1",
                mapping_document=document,
                published_at=first.stored.document.published_at,
                published_by_principal=first.stored.document.publisher_principal,
            )
        )
        db.commit()
    with pytest.raises(MappingRefused):
        query_mapping(
            postgres_session_factory,
            scope=fresh.document.material.scope,
            offer_id=SIMULATED_OFFER_ID,
            allow_simulated=True,
        )
    assert (
        query_mapping(
            postgres_session_factory,
            scope=fresh.document.material.scope,
            offer_id=SIMULATED_OFFER_ID,
            revision=1,
            allow_simulated=True,
        )
        == first.stored
    )


@pytest.mark.parametrize("commit_reached_server", [True, False])
async def test_uncertain_commit_reads_authoritative_revision_without_replaying(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    commit_reached_server: bool,
) -> None:
    # sessionmaker creates a subclass of class_. Count attempts independently of
    # that generated class, including any sessions used for authoritative reads.
    commit_attempts = 0

    class LostAcknowledgement(Session):
        def commit(self) -> None:
            nonlocal commit_attempts
            commit_attempts += 1
            if commit_reached_server:
                super().commit()
            raise OperationalError("COMMIT", None, RuntimeError("SIMULATED lost acknowledgement"))

    factory = sessionmaker(bind=migrated_database, class_=LostAcknowledgement, autoflush=False)
    fresh = await fresh_fixture(await reviewed_fixture())
    if commit_reached_server:
        result = publish(factory, fresh)
        assert result.recovered_commit and result.stored.revision_number == 1
    else:
        with pytest.raises(MappingCommitUncertain):
            publish(factory, fresh)
    assert commit_attempts == 1
    with postgres_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(CommercialMappingRevision)) == int(commit_reached_server)


def test_cli_dry_run_publish_and_query_use_same_real_path(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # This synchronous test owns its fixture loop separately from the CLI's
    # process event loop. No sync SQLAlchemy call is delegated by production I/O.
    with asyncio.Runner() as runner:
        reviewed = runner.run(reviewed_fixture())
    proposal_path = tmp_path / "SIMULATED-proposal.json"
    approval_path = tmp_path / "SIMULATED-approval.json"
    inputs_path = tmp_path / "SIMULATED-source-inputs.json"
    proposal_path.write_text(reviewed.proposal.model_dump_json(), encoding="utf-8")
    approval_path.write_text(reviewed.approval.model_dump_json(), encoding="utf-8")
    inputs_path.write_text(simulated_inputs().model_dump_json(), encoding="utf-8")
    config = operator_settings(
        mapping_approval_file=approval_path,
        mapping_source_inputs_file=inputs_path,
        postgres_password="SIMULATED-db-output-canary",
        smtp_password="SIMULATED-mail-output-canary",
        database_url="postgresql+psycopg://SIMULATED-user:SIMULATED-url-output-canary@localhost/unused",
    )
    original = mapping_operator.fresh_mapping_evaluation
    recording = SelectedOfferRecording()
    # Valid but unselected provider text can contain PII. It must not become
    # part of the normalized mapping or the operator's stdout/stderr.
    recording.replace(
        "tariff",
        '"additional_fields":[]',
        '"additional_fields":[{"name":"contact","element_value":"unselected-person@example.invalid"}]',
    )
    kernel_requests: list[httpx.Request] = []

    def kernel_response(request: httpx.Request) -> httpx.Response:
        kernel_requests.append(request)
        return httpx.Response(200, json=manifest_fixture(), headers={"X-Private": "SIMULATED-header-output-canary"})

    async def configured_sources(*args: object, **kwargs: object) -> FreshMappingEvaluation:
        return await original(
            *args,
            **kwargs,
            kernel_transport=httpx.MockTransport(kernel_response),
            lbx_transport=httpx.MockTransport(recording.respond),
        )

    monkeypatch.setattr(mapping_operator, "fresh_mapping_evaluation", configured_sources)
    monkeypatch.setattr(mapping_operator.os, "geteuid", lambda: SIMULATED_UID)

    def configuration() -> Settings:
        return config

    monkeypatch.setattr(cli, "Settings", configuration)

    def run_operator(argv: list[str]) -> dict[str, Any]:
        assert cli.main(argv) == 0
        captured = capsys.readouterr()
        assert captured.err == ""
        assert all(
            marker not in captured.out
            for marker in (
                PASSWORD,
                LBX_TOKEN,
                USERNAME,
                "simulated-kernel-client-test-token",
                "SIMULATED-db-output-canary",
                "SIMULATED-mail-output-canary",
                "SIMULATED-url-output-canary",
                "SIMULATED-header-output-canary",
                "unselected-person@example.invalid",
            )
        )
        return json.loads(captured.out)

    from app.core import database

    def forbidden_database() -> Session:
        raise AssertionError("dry-run opened a DB session")

    monkeypatch.setattr(database, "SessionLocal", forbidden_database)
    dry_run = run_operator(["dry-run", "--proposal", str(proposal_path)])
    assert not dry_run["persisted"]
    monkeypatch.setattr(database, "SessionLocal", postgres_session_factory)
    result = run_operator(["publish", "--proposal", str(proposal_path), "--expected-previous-revision", "0"])
    assert result["inserted"] and result["revision_number"] == 1
    assert result["stored_document"]["material_fingerprint"] == dry_run["evaluation"]["material_fingerprint"]
    assert result["operator_audit"]["execution_principal"] == f"os-euid:{SIMULATED_UID}"
    assert len(kernel_requests) == 2
    assert recording.counts == {"tariff": 4, "periods": 4, "services": 4, "prices": 4}
    assert result["billing_offer_id"] == dry_run["billing_offer_id"] == SIMULATED_OFFER_ID
    queried = run_operator(["query", "--offer-id", SIMULATED_OFFER_ID])
    assert queried["billing_offer_id"] == SIMULATED_OFFER_ID
    assert queried["mapping_revision_id"] == result["mapping_revision_id"]
    # No redaction/reconstruction of immutable audit evidence to appease a
    # scanner: exact terms, scope, references, reason and principal survive.
    assert queried["document"] == result["stored_document"]
    document = MappingDocument.model_validate_json(json.dumps(queried["document"]))
    assert document.reason == reviewed.proposal.reason
    assert document.material == reviewed.approval.material
    assert document.approvals == reviewed.approval.revisions
    assert len(kernel_requests) == 2
