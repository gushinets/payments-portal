"""Issuance bounds, independent retention, migration and lock-race evidence."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import event, inspect, text
from sqlalchemy.orm import Session

from app.composition.delegation_cleanup import delegation_cleanup_resources
from app.domains.identity.services import backend_delegation as delegation
from app.domains.identity.services import delegation_cleanup as cleanup
from app.models import AuthSession, BackendCodeIssuanceBudget, BackendSessionDelegation, User, UserStatus
from apps.api.tests.support.postgres import alembic_test_config
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_kernel_session_delegation_postgres import (
    DelegatedParent,
    PARENT_TOKEN,
    VERIFIER,
    delegated_parent as delegated_parent,
    parent_identity as parent_identity,
)

pytestmark = pytest.mark.postgres


def issue(db: Session, token: str = PARENT_TOKEN, consumer: str = "platform-kernel") -> delegation.DelegationCode:
    return delegation.issue_code(
        db,
        token=token,
        tenant_id="anytoolai",
        region="ru",
        code_challenge=delegation.pkce_challenge(VERIFIER),
        consumer_id=consumer,
    )


def exchange(db: Session, code: str) -> delegation.DelegationToken:
    return delegation.exchange_code(
        db, code=code, verifier=VERIFIER, tenant_id="anytoolai", region="ru", consumer_id="platform-kernel"
    )


def test_completed_authorizations_are_bounded_across_parent_sessions(delegated_parent: DelegatedParent) -> None:
    factory, _, user_id, first_code = delegated_parent
    with factory() as db:
        first = exchange(db, first_code)
        db.add(
            AuthSession(
                user_id=user_id,
                tenant_id="anytoolai",
                region="ru",
                token_hash=delegation.credential_hash("second-parent"),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        db.commit()
        for _ in range(59):
            exchange(db, issue(db, "second-parent").code)
        with pytest.raises(delegation.CodeIssuanceRateLimited):
            issue(db)
        db.rollback()
        assert db.query(BackendSessionDelegation).count() == 60
        assert (
            delegation.introspect_token(
                db,
                token=first.access_token,
                tenant_id="anytoolai",
                region="ru",
                consumer_id="platform-kernel",
                clock_skew_seconds=5,
            ).user_id
            == user_id
        )
        # A different consumer has an independent budget.
        issue(db, consumer="removed-consumer")


def test_parallel_issuance_has_one_last_slot(delegated_parent: DelegatedParent) -> None:
    factory, _, _, _ = delegated_parent
    with factory.begin() as db:
        db.query(BackendCodeIssuanceBudget).one().issued_count = 59

    def attempt(_: int) -> bool:
        with factory() as db:
            try:
                issue(db)
                return True
            except delegation.CodeIssuanceRateLimited:
                return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(attempt, range(4))).count(True) == 1
    with factory() as db:
        assert db.query(BackendCodeIssuanceBudget).one().issued_count == 60
        assert db.query(BackendSessionDelegation).count() == 2


def test_failed_insertion_rolls_back_budget(delegated_parent: DelegatedParent) -> None:
    factory, _, _, _ = delegated_parent

    def fail(db: Session, flush_context: object, instances: object) -> None:
        if any(isinstance(row, BackendSessionDelegation) for row in db.new):
            raise RuntimeError("synthetic code insertion failure")

    with factory() as db:
        event.listen(db, "before_flush", fail)
        with pytest.raises(RuntimeError, match="synthetic code insertion failure"):
            issue(db)
        db.rollback()
    with factory() as db:
        assert db.query(BackendCodeIssuanceBudget).one().issued_count == 1
        assert db.query(BackendSessionDelegation).count() == 1


def test_cleanup_does_not_delete_budget_renewed_after_candidate_read(delegated_parent: DelegatedParent) -> None:
    factory, _, _, _ = delegated_parent
    with factory.begin() as db:
        db.query(BackendCodeIssuanceBudget).one().window_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    selected, resume = Event(), Event()
    engine = factory.kw["bind"]

    def pause(
        connection: object, cursor: object, statement: str, parameters: object, context: object, many: bool
    ) -> None:
        if "backend_code_issuance_budgets" in statement and "LIMIT" in statement:
            selected.set()
            assert resume.wait(5)

    event.listen(engine, "after_cursor_execute", pause)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(cleanup.cleanup_batch, factory, tenant_id="anytoolai", region="ru")
            try:
                assert selected.wait(5)
                with factory() as db:
                    issue(db)
            finally:
                resume.set()
            future.result(timeout=5)
    finally:
        event.remove(engine, "after_cursor_execute", pause)
    with factory() as db:
        assert db.query(BackendCodeIssuanceBudget).one().issued_count == 1
        assert delegation.as_utc(db.query(BackendCodeIssuanceBudget).one().window_expires_at) > datetime.now(UTC)


def test_cleanup_preserves_exchange_committed_while_waiting_for_user(
    delegated_parent: DelegatedParent, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, _, _, code = delegated_parent
    exchanging, cleaning = Event(), Event()
    now = datetime.now(UTC)
    monkeypatch.setattr(cleanup, "utc_now", lambda: now + timedelta(seconds=61))

    def before_commit(db: Session) -> None:
        exchanging.set()
        assert cleaning.wait(5)

    def before_lock(
        connection: object, cursor: object, statement: str, parameters: object, context: object, many: bool
    ) -> None:
        if statement.startswith("SELECT users.") and "FOR UPDATE" in statement:
            cleaning.set()

    def exchanging_first() -> delegation.DelegationToken:
        with factory() as db:
            event.listen(db, "before_commit", before_commit, once=True)
            return exchange(db, code)

    engine = factory.kw["bind"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(exchanging_first)
        assert exchanging.wait(5)
        event.listen(engine, "before_cursor_execute", before_lock)
        try:
            second = pool.submit(cleanup.cleanup_batch, factory, tenant_id="anytoolai", region="ru")
            token = first.result(timeout=10)
            second.result(timeout=10)
        finally:
            event.remove(engine, "before_cursor_execute", before_lock)
    with factory() as db:
        assert db.query(BackendSessionDelegation).one().token_hash == delegation.credential_hash(token.access_token)


@pytest.mark.parametrize("expired_token", [False, True])
def test_cleanup_is_batched_and_retains_token_evidence(
    delegated_parent: DelegatedParent, monkeypatch: pytest.MonkeyPatch, expired_token: bool
) -> None:
    factory, parent_id, user_id, code = delegated_parent
    now = datetime.now(UTC)
    with factory() as db:
        token = exchange(db, code)
        if expired_token:
            db.query(BackendSessionDelegation).one().token_expires_at = now - timedelta(seconds=1)
        # Removed consumers and inactive users must not strand expired credentials.
        db.get(User, user_id).status = UserStatus.INACTIVE
        old_parent = AuthSession(
            user_id=user_id,
            tenant_id="anytoolai",
            region="ru",
            token_hash=delegation.credential_hash("old-parent"),
            expires_at=now - timedelta(days=1),
        )
        db.add(old_parent)
        db.flush()
        for i in range(205):
            db.add(
                BackendCodeIssuanceBudget(
                    tenant_id="anytoolai",
                    region="ru",
                    user_id=user_id,
                    consumer_id=f"removed-{i}",
                    issued_count=60,
                    window_expires_at=now - timedelta(seconds=1),
                )
            )
            db.add(
                BackendSessionDelegation(
                    auth_session_id=old_parent.id,
                    consumer_id="removed-consumer",
                    code_hash=delegation.credential_hash(f"old-{i}"),
                    code_challenge=delegation.pkce_challenge(VERIFIER),
                    code_expires_at=now + timedelta(seconds=60),
                )
            )
        db.query(BackendCodeIssuanceBudget).one().window_expires_at = now - timedelta(seconds=1)
        db.commit()
    monkeypatch.setattr(cleanup, "utc_now", lambda: now)
    assert cleanup.cleanup_batch(factory, tenant_id="anytoolai", region="ru")
    with factory() as db:
        assert db.query(BackendSessionDelegation).count() == 106
        assert db.query(BackendCodeIssuanceBudget).count() == 106
    assert cleanup.cleanup_batch(factory, tenant_id="anytoolai", region="ru")
    assert not cleanup.cleanup_batch(factory, tenant_id="anytoolai", region="ru")
    with factory() as db:
        assert db.query(BackendCodeIssuanceBudget).count() == 0
        assert db.query(BackendSessionDelegation).count() == 1
        db.get(User, user_id).status = UserStatus.ACTIVE
        db.commit()
        if expired_token:
            with pytest.raises(delegation.InvalidDelegationError) as expired:
                delegation.introspect_token(
                    db,
                    token=token.access_token,
                    tenant_id="anytoolai",
                    region="ru",
                    consumer_id="platform-kernel",
                    clock_skew_seconds=5,
                )
            assert expired.value.code == delegation.DelegationRefusal.EXPIRED
        else:
            assert (
                delegation.introspect_token(
                    db,
                    token=token.access_token,
                    tenant_id="anytoolai",
                    region="ru",
                    consumer_id="platform-kernel",
                    clock_skew_seconds=5,
                ).user_id
                == user_id
            )
        db.get(AuthSession, parent_id).revoked_at = now
        db.commit()
    assert not cleanup.cleanup_batch(factory, tenant_id="anytoolai", region="ru")
    with factory() as db:
        assert db.query(BackendSessionDelegation).count() == 0
        with pytest.raises(delegation.InvalidDelegationError) as invalid:
            delegation.introspect_token(
                db,
                token=token.access_token,
                tenant_id="anytoolai",
                region="ru",
                consumer_id="platform-kernel",
                clock_skew_seconds=5,
            )
        assert invalid.value.code == delegation.DelegationRefusal.PARENT_INVALID


def test_cleanup_cannot_cross_tenant_scope(delegated_parent: DelegatedParent) -> None:
    factory, _, _, _ = delegated_parent
    now = datetime.now(UTC)
    with factory.begin() as db:
        foreign = User(
            tenant_id="other-tenant",
            region="ru",
            email="foreign@example.test",
            email_normalized="foreign@example.test",
            status=UserStatus.INACTIVE,
        )
        db.add(foreign)
        db.flush()
        parent = AuthSession(
            user_id=foreign.id,
            tenant_id=foreign.tenant_id,
            region=foreign.region,
            token_hash=delegation.credential_hash("foreign-parent"),
            expires_at=now - timedelta(days=1),
        )
        db.add(parent)
        db.flush()
        foreign_id = uuid4()
        db.add(
            BackendSessionDelegation(
                id=foreign_id,
                auth_session_id=parent.id,
                consumer_id="removed-consumer",
                code_hash=delegation.credential_hash("foreign-code"),
                code_challenge=delegation.pkce_challenge(VERIFIER),
                code_expires_at=now - timedelta(days=1),
            )
        )
        db.add(
            BackendCodeIssuanceBudget(
                tenant_id=foreign.tenant_id,
                region=foreign.region,
                user_id=foreign.id,
                consumer_id="removed-consumer",
                issued_count=60,
                window_expires_at=now - timedelta(days=1),
            )
        )
    cleanup.cleanup_batch(factory, tenant_id="anytoolai", region="ru")
    with factory() as db:
        assert db.get(BackendSessionDelegation, foreign_id) is not None
        assert db.query(BackendCodeIssuanceBudget).filter_by(tenant_id="other-tenant").one().issued_count == 60


@pytest.mark.anyio
async def test_cleanup_runs_without_billing_or_further_logins_and_after_restart(
    delegated_parent: DelegatedParent,
) -> None:
    factory, parent_id, _, _ = delegated_parent
    config = step1_settings(billing_worker_enabled=False)
    for _ in range(2):
        with factory.begin() as db:
            db.query(BackendSessionDelegation).update({"code_expires_at": datetime.now(UTC) - timedelta(seconds=1)})
        async with delegation_cleanup_resources(config, factory=factory):
            async with asyncio.timeout(5):
                while True:
                    with factory() as db:
                        if db.query(BackendSessionDelegation).count() == 0:
                            break
                    await asyncio.sleep(0.01)
        with factory.begin() as db:
            db.add(
                BackendSessionDelegation(
                    auth_session_id=parent_id,
                    consumer_id="removed-consumer",
                    code_hash=delegation.credential_hash(str(uuid4())),
                    code_challenge=delegation.pkce_challenge(VERIFIER),
                    code_expires_at=datetime.now(UTC),
                )
            )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_budget_migration_refuses_reset_and_preserves_history(delegated_parent: DelegatedParent) -> None:
    factory, _, _, _ = delegated_parent
    engine = factory.kw["bind"]
    with factory() as db:
        before = db.scalar(text("SELECT to_jsonb(b) FROM backend_code_issuance_budgets b"))
    with alembic_test_config(engine.url) as config:
        with pytest.raises(RuntimeError, match="Code issuance budgets require the new writer"):
            command.downgrade(config, "20261113_0012")
    with factory() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "20261113_0013"
        assert db.scalar(text("SELECT to_jsonb(b) FROM backend_code_issuance_budgets b")) == before
        constraints = inspect(engine).get_foreign_keys("backend_code_issuance_budgets")
        assert constraints[0]["options"]["ondelete"] == "CASCADE"


@pytest.mark.parametrize("expired", [False, True])
def test_exchange_rereads_code_after_concurrent_cleanup(
    delegated_parent: DelegatedParent,
    monkeypatch: pytest.MonkeyPatch,
    expired: bool,
) -> None:
    factory, _, _, code = delegated_parent
    if expired:
        with factory.begin() as db:
            db.query(BackendSessionDelegation).one().code_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    read = Event()
    resume = Event()
    original = delegation.read_delegation

    def pause_after_read(
        db: Session,
        *,
        credential_hash: str,
        by_code: bool,
    ) -> tuple[BackendSessionDelegation, AuthSession, User] | None:
        found = original(db, credential_hash=credential_hash, by_code=by_code)
        read.set()
        assert resume.wait(10)
        return found

    monkeypatch.setattr(delegation, "read_delegation", pause_after_read)

    def exchange_waiting() -> delegation.DelegationToken | delegation.DelegationRefusal:
        with factory() as db:
            try:
                return exchange(db, code)
            except delegation.InvalidDelegationError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(exchange_waiting)
        try:
            assert read.wait(10)
            cleanup.cleanup_batch(factory, tenant_id="anytoolai", region="ru")
        finally:
            resume.set()
        result = future.result(timeout=10)
    with factory() as db:
        if expired:
            assert result == delegation.DelegationRefusal.CODE_INVALID
            assert db.query(BackendSessionDelegation).count() == 0
        else:
            assert isinstance(result, delegation.DelegationToken)
            assert db.query(BackendSessionDelegation).count() == 1
