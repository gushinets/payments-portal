"""Transient publication leases across real PostgreSQL waits and rollback."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from queue import Queue

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.domains.catalog import publication
from app.domains.catalog.mapping_evidence import MappingRefused
from app.domains.catalog.publication import PublicationResult, StoredMapping
from app.infrastructure.persistence.commercial_mappings import MappingStorageDeadline, lock_mapping_scope
from app.models import CommercialMappingRevision
from apps.api.tests.support.commercial_mappings import SIMULATED_OFFER_ID, fresh_fixture, reviewed_fixture
from apps.api.tests.support.lbx_selected_offer import SelectedOfferRecording, simulated_inputs
from apps.api.tests.support.operator_processes import OperatorProcesses, processes as processes


pytestmark = [pytest.mark.postgres, pytest.mark.anyio, pytest.mark.usefixtures("mapping_clock")]
BEFORE_MIDNIGHT = datetime(2026, 10, 16, 20, 59, 59, tzinfo=UTC)
MIDNIGHT = datetime(2026, 10, 16, 21, tzinfo=UTC)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def assert_history_unchanged(factory: sessionmaker[Session], first: StoredMapping) -> None:
    assert (
        publication.query_mapping(
            factory, scope=first.document.material.scope, offer_id=SIMULATED_OFFER_ID, allow_simulated=True
        )
        == first
    )
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(CommercialMappingRevision)) == 1


@pytest.mark.parametrize("stage", ["before_database", "after_history", "after_flush"])
@pytest.mark.parametrize("expiring", ["account_day", "policy", "price"])
async def test_expiration_never_appends_or_changes_latest_revision(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    expiring: str,
) -> None:
    first_fresh = await fresh_fixture(await reviewed_fixture())
    first = publication.publish_mapping(
        postgres_session_factory,
        evaluation=first_fresh.document,
        deadline=first_fresh.deadline,
        evidence_valid_until=first_fresh.evidence_valid_until,
        expected_previous_revision=0,
        lock_timeout_seconds=0.2,
        allow_simulated=True,
    ).stored
    recording, inputs = SelectedOfferRecording(), simulated_inputs()
    assert inputs.policy is not None
    if expiring == "policy":
        inputs = inputs.model_copy(
            update={"policy": inputs.policy.model_copy(update={"valid_until": date(2026, 10, 17)})}
        )
    elif expiring == "price":
        recording.replace("prices", "2027-01-01", "2026-10-17")
    reviewed = await reviewed_fixture(allowance=26, revision="fixture-v2", recording=recording, source_inputs=inputs)
    instant = BEFORE_MIDNIGHT
    fresh = await fresh_fixture(reviewed, recording=recording, source_inputs=inputs, clock=lambda: instant)
    assert fresh.evidence_valid_until == MIDNIGHT
    factory = postgres_session_factory
    if stage == "before_database":
        instant = MIDNIGHT

        def forbidden_database() -> Session:
            raise AssertionError("expiry after cleanup must precede DB work")

        factory = forbidden_database
    elif stage == "after_history":
        history = publication.mapping_revision_history

        def expire_after_history(db: Session, *, account_id: str, offer_id: str) -> Iterator[CommercialMappingRevision]:
            nonlocal instant
            yield from history(db, account_id=account_id, offer_id=offer_id)
            instant = MIDNIGHT

        monkeypatch.setattr(publication, "mapping_revision_history", expire_after_history)
    else:

        class ExpireAfterFlush(Session):
            def flush(self, objects: object = None) -> None:
                nonlocal instant
                super().flush(objects)
                instant = MIDNIGHT

        factory = sessionmaker(bind=migrated_database, class_=ExpireAfterFlush, autoflush=False)
    with pytest.raises(MappingRefused, match="mapping_publication_evidence_expired"):
        publication.publish_mapping(
            factory,
            evaluation=fresh.document,
            deadline=fresh.deadline,
            evidence_valid_until=fresh.evidence_valid_until,
            expected_previous_revision=1,
            lock_timeout_seconds=0.2,
            allow_simulated=True,
            clock=lambda: instant,
        )
    assert_history_unchanged(postgres_session_factory, first)


async def test_real_advisory_lock_wait_crossing_midnight_refuses_publication(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = await reviewed_fixture()
    first_fresh = await fresh_fixture(reviewed)
    first = publication.publish_mapping(
        postgres_session_factory,
        evaluation=first_fresh.document,
        deadline=first_fresh.deadline,
        evidence_valid_until=first_fresh.evidence_valid_until,
        expected_previous_revision=0,
        lock_timeout_seconds=0.2,
        allow_simulated=True,
    ).stored
    instant = BEFORE_MIDNIGHT
    fresh = await fresh_fixture(await reviewed_fixture(allowance=26, revision="fixture-v2"), clock=lambda: instant)
    pids: Queue[int] = Queue()

    def observed_lock(db: Session, *, account_id: str, offer_id: str) -> None:
        pids.put(db.scalar(text("SELECT pg_backend_pid()")))
        lock_mapping_scope(db, account_id=account_id, offer_id=offer_id)

    monkeypatch.setattr(publication, "lock_mapping_scope", observed_lock)

    def contender() -> PublicationResult:
        return publication.publish_mapping(
            postgres_session_factory,
            evaluation=fresh.document,
            deadline=fresh.deadline,
            evidence_valid_until=fresh.evidence_valid_until,
            expected_previous_revision=1,
            lock_timeout_seconds=2,
            allow_simulated=True,
            clock=lambda: instant,
        )

    with ThreadPoolExecutor(max_workers=1) as pool, postgres_session_factory() as holder:
        lock_mapping_scope(
            holder, account_id=first.document.material.scope.external_billing_account_id, offer_id=SIMULATED_OFFER_ID
        )
        future = pool.submit(contender)
        try:
            pid = pids.get(timeout=2)
            end = time.monotonic() + 1
            while not holder.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid = :pid AND locktype = 'advisory' AND NOT granted)"
                ),
                {"pid": pid},
            ):
                assert time.monotonic() < end, "publisher never waited on PostgreSQL lock"
                time.sleep(0.01)
            instant = MIDNIGHT
        finally:
            holder.rollback()
        with pytest.raises(MappingRefused, match="mapping_publication_evidence_expired"):
            future.result(timeout=3)
    assert_history_unchanged(postgres_session_factory, first)


async def test_commit_before_boundary_and_identical_retry_preserve_original_row(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    fresh = await fresh_fixture(await reviewed_fixture(), clock=lambda: BEFORE_MIDNIGHT)

    def attempt(deadline: float) -> PublicationResult:
        return publication.publish_mapping(
            postgres_session_factory,
            evaluation=fresh.document,
            deadline=deadline,
            evidence_valid_until=fresh.evidence_valid_until,
            expected_previous_revision=0,
            lock_timeout_seconds=0.2,
            allow_simulated=True,
            clock=lambda: BEFORE_MIDNIGHT,
        )

    first, retry = attempt(fresh.deadline), attempt(fresh.deadline)
    assert first.inserted and not retry.inserted and retry.stored == first.stored
    assert first.stored.document.published_at == BEFORE_MIDNIGHT
    # A valid commercial lease never renews an expired monotonic work deadline.
    with pytest.raises(MappingStorageDeadline):
        attempt(replace(fresh, deadline=time.monotonic() - 1).deadline)
    with pytest.raises(MappingRefused, match="mapping_publication_evidence_expired"):
        publication.publish_mapping(
            postgres_session_factory,
            evaluation=fresh.document,
            deadline=fresh.deadline,
            evidence_valid_until=fresh.evidence_valid_until,
            expected_previous_revision=0,
            lock_timeout_seconds=0.2,
            allow_simulated=True,
            clock=lambda: MIDNIGHT,
        )
    assert_history_unchanged(postgres_session_factory, first.stored)


async def test_lost_commit_ack_recovery_returns_saved_revision_even_after_boundary(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    instant = BEFORE_MIDNIGHT
    commits = 0

    class LostAcknowledgement(Session):
        def commit(self) -> None:
            nonlocal instant, commits
            commits += 1
            super().commit()
            instant = MIDNIGHT
            raise OperationalError("COMMIT", None, RuntimeError("SIMULATED lost acknowledgement"))

    fresh = await fresh_fixture(await reviewed_fixture(), clock=lambda: instant)
    result = publication.publish_mapping(
        sessionmaker(bind=migrated_database, class_=LostAcknowledgement, autoflush=False),
        evaluation=fresh.document,
        deadline=fresh.deadline,
        evidence_valid_until=fresh.evidence_valid_until,
        expected_previous_revision=0,
        lock_timeout_seconds=0.2,
        allow_simulated=True,
        clock=lambda: instant,
    )
    assert result.recovered_commit and not result.inserted and commits == 1
    assert_history_unchanged(postgres_session_factory, result.stored)


@pytest.mark.skipif(os.name != "posix", reason="Operator flock requires Unix")
async def test_independent_query_reads_postgres_while_operator_lock_is_occupied(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    from app.infrastructure.operator_preflight import operator_preflight_lock
    from apps.api.tests.support.settings import DEFAULT_API_TEST_ENV

    fresh = await fresh_fixture(await reviewed_fixture())
    first = publication.publish_mapping(
        postgres_session_factory,
        evaluation=fresh.document,
        deadline=fresh.deadline,
        evidence_valid_until=fresh.evidence_valid_until,
        expected_previous_revision=0,
        lock_timeout_seconds=0.2,
        allow_simulated=True,
    ).stored
    path = tmp_path / "operator.lock"
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("MAPPING_", "KERNEL_", "LBX_", "PREFLIGHT_"))
    }
    environment.update(DEFAULT_API_TEST_ENV)
    environment.update(
        PYTHONPATH=".:apps/api",
        DATABASE_URL=migrated_database.url.render_as_string(hide_password=False),
        MAPPING_OPERATOR_UIDS=json.dumps([os.geteuid()]),
        MAPPING_ACCOUNT_ID=fresh.document.material.scope.external_billing_account_id,
        MAPPING_OPERATOR_LOCK_FILE=str(path),
        KERNEL_BASE_URL="",
        KERNEL_SERVICE_TOKEN="",
        LBX_BASE_URL="",
        LBX_EXTERNAL_BILLING_ACCOUNT_ID="",
        LBX_SERVER_USERNAME="",
        LBX_SERVER_PASSWORD="",
    )
    with operator_preflight_lock(path):
        result = subprocess.run(
            [sys.executable, "-m", "app.cli.commercial_mappings", "query", "--offer-id", SIMULATED_OFFER_ID],
            cwd=Path(__file__).resolve().parents[3],
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["mapping_revision_id"] == str(first.mapping_revision_id)
    assert output["revision_number"] == 1


@pytest.mark.skipif(os.name != "posix", reason="Operator flock requires Unix")
async def test_independent_publish_cli_saturates_then_retries_same_command_without_duplicate(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], processes: OperatorProcesses
) -> None:
    processes.environment["DATABASE_URL"] = migrated_database.url.render_as_string(hide_password=False)
    first = processes.start("publish")
    assert processes.entered.wait(10), "first publisher never reached Kernel"
    before = list(processes.requests)
    contender = processes.run("publish")
    assert contender.returncode == 1
    assert json.loads(contender.stderr) == {"detail": {"code": "preflight_saturated"}}
    assert processes.requests == before
    processes.release.set()
    output, error = first.communicate(timeout=15)
    assert first.returncode == 0, error
    saved = json.loads(output)
    assert saved["inserted"] and saved["revision_number"] == 1
    retry = processes.run("publish")
    assert retry.returncode == 0, retry.stderr
    repeated = json.loads(retry.stdout)
    assert not repeated["inserted"]
    assert repeated["mapping_revision_id"] == saved["mapping_revision_id"]
    with postgres_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(CommercialMappingRevision)) == 1
