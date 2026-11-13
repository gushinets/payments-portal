"""Real migration, cascade and security-write concurrency evidence."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from uuid import UUID
from sqlalchemy.engine import Connection, Engine, ExceptionContext, ExecutionContext

import pytest
from alembic import command
from sqlalchemy import event, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy import inspect
from sqlalchemy.orm import Session, sessionmaker

from app.domains.identity.services import backend_delegation as delegation
from app.domains.identity.services import password_reset
from app.domains.identity.errors import InvalidOrExpiredResetTokenError
from app.domains.identity.passwords import hash_password, verify_password
from app.models import AuthSession, BackendSessionDelegation, MagicLinkPurpose, MagicLinkToken, User, UserStatus
from apps.api.tests.support.postgres import alembic_test_config

VERIFIER = "synthetic-verifier-" + "v" * 32
PARENT_TOKEN = "synthetic-parent-" + "p" * 32
DelegatedParent = tuple[sessionmaker[Session], UUID, UUID, str]
RESET_TOKENS = ("synthetic-first-reset-token", "synthetic-second-reset-token")
RESET_PASSWORD = "Changed-password-123!"


@pytest.fixture
def delegated_parent(migrated_database: Engine, postgres_session_factory: sessionmaker[Session]) -> DelegatedParent:
    with postgres_session_factory() as db:
        user = User(
            tenant_id="anytoolai",
            region="ru",
            email="synthetic@example.com",
            email_normalized="synthetic@example.com",
            status=UserStatus.ACTIVE,
            email_verified_at=datetime.now(UTC),
        )
        db.add(user)
        db.flush()
        parent = AuthSession(
            user_id=user.id,
            tenant_id=user.tenant_id,
            region=user.region,
            token_hash=delegation.credential_hash(PARENT_TOKEN),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db.add(parent)
        db.commit()
        parent_id, user_id = parent.id, user.id
        code = delegation.issue_code(
            db,
            token=PARENT_TOKEN,
            tenant_id="anytoolai",
            region="ru",
            code_challenge=delegation.pkce_challenge(VERIFIER),
            consumer_id="platform-kernel",
        ).code
    return postgres_session_factory, parent_id, user_id, code


def test_migrated_shape_and_single_use_race(delegated_parent: DelegatedParent, monkeypatch: pytest.MonkeyPatch) -> None:
    factory, _, _, code = delegated_parent
    barrier = Barrier(2)
    original = delegation.read_delegation

    def read_together(
        db: Session, *, credential_hash: str, by_code: bool
    ) -> tuple[BackendSessionDelegation, AuthSession, User] | None:
        result = original(db, credential_hash=credential_hash, by_code=by_code)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(delegation, "read_delegation", read_together)

    def exchange_once() -> delegation.DelegationToken | str:
        with factory() as db:
            try:
                return delegation.exchange_code(
                    db, code=code, verifier=VERIFIER, tenant_id="anytoolai", region="ru", consumer_id="platform-kernel"
                )
            except delegation.InvalidDelegationError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: exchange_once(), range(2)))
    assert sum(isinstance(item, delegation.DelegationToken) for item in results) == 1
    assert results.count("backend_session_code_invalid") == 1
    with factory() as db:
        row = db.query(BackendSessionDelegation).one()
        assert row.token_hash and row.exchanged_at and row.token_expires_at
        constraints = inspect(db.bind).get_foreign_keys("backend_session_delegations")
        assert constraints[0]["options"]["ondelete"] == "CASCADE"


def test_parent_deletion_cascades_and_old_token_is_refused(delegated_parent: DelegatedParent) -> None:
    factory, parent_id, _, code = delegated_parent
    with factory() as db:
        token = delegation.exchange_code(
            db, code=code, verifier=VERIFIER, tenant_id="anytoolai", region="ru", consumer_id="platform-kernel"
        ).access_token
        db.delete(db.get(AuthSession, parent_id))
        db.commit()
        assert db.query(BackendSessionDelegation).count() == 0
        with pytest.raises(delegation.InvalidDelegationError, match="backend_parent_authority_invalid"):
            delegation.introspect_token(
                db, token=token, tenant_id="anytoolai", region="ru", clock_skew_seconds=5, consumer_id="platform-kernel"
            )


@pytest.mark.parametrize("change", ["revoke", "expire", "deactivate", "delete"])
def test_parent_change_while_exchange_waits_cannot_mint_authority(
    delegated_parent: DelegatedParent, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    factory, parent_id, user_id, code = delegated_parent
    reached = Barrier(2)
    original = delegation.lock_active_user_by_id_and_scope

    def lock_after_read(db: Session, *, user_id: UUID, tenant_id: str, region: str) -> User | None:
        reached.wait(timeout=10)
        return original(db, user_id=user_id, tenant_id=tenant_id, region=region)

    monkeypatch.setattr(delegation, "lock_active_user_by_id_and_scope", lock_after_read)

    def exchange_waiting() -> str:
        with factory() as db:
            try:
                delegation.exchange_code(
                    db, code=code, verifier=VERIFIER, tenant_id="anytoolai", region="ru", consumer_id="platform-kernel"
                )
            except delegation.InvalidDelegationError as error:
                return error.code
        return "unexpected-success"

    with factory() as writer, ThreadPoolExecutor(max_workers=1) as pool:
        user = writer.query(User).filter(User.id == user_id).with_for_update().one()
        parent = writer.query(AuthSession).filter(AuthSession.id == parent_id).with_for_update().one()
        future = pool.submit(exchange_waiting)
        reached.wait(timeout=10)
        if change == "revoke":
            parent.revoked_at = datetime.now(UTC)
        elif change == "expire":
            parent.expires_at = datetime.now(UTC)
        elif change == "deactivate":
            user.status = UserStatus.INACTIVE
        else:
            writer.delete(parent)
        writer.commit()
        assert future.result(timeout=10) == "backend_parent_authority_invalid"


def test_foreign_scope_and_verifier_do_not_consume_code(delegated_parent: DelegatedParent) -> None:
    factory, _, user_id, code = delegated_parent
    with factory() as db:
        with pytest.raises(delegation.InvalidDelegationError):
            delegation.exchange_code(
                db, code=code, verifier=VERIFIER, tenant_id="foreign", region="ru", consumer_id="platform-kernel"
            )
        db.rollback()
        with pytest.raises(delegation.InvalidDelegationError, match="backend_session_code_invalid"):
            delegation.exchange_code(
                db, code=code, verifier="x" * 43, tenant_id="anytoolai", region="ru", consumer_id="platform-kernel"
            )
        db.rollback()
        result = delegation.exchange_code(
            db, code=code, verifier=VERIFIER, tenant_id="anytoolai", region="ru", consumer_id="platform-kernel"
        )
        assert result.identity.user_id == user_id


def test_migration_round_trip_preserves_parent_and_rejects_partial_exchange(
    delegated_parent: DelegatedParent,
    database_test_url: URL,
) -> None:
    factory, parent_id, _, _ = delegated_parent
    with factory() as db:
        before = db.execute(
            text("SELECT to_jsonb(s) FROM auth_sessions s WHERE id = :id"), {"id": parent_id}
        ).scalar_one()
        db.query(BackendSessionDelegation).one().token_hash = "partial-exchange-hash"
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    with alembic_test_config(database_test_url) as config:
        command.downgrade(config, "20261031_0006")
        with factory() as db:
            assert "backend_session_delegations" not in inspect(db.bind).get_table_names()
            assert (
                db.execute(
                    text("SELECT to_jsonb(s) FROM auth_sessions s WHERE id = :id"), {"id": parent_id}
                ).scalar_one()
                == before
            )
        command.upgrade(config, "head")
    with factory() as db:
        assert db.query(BackendSessionDelegation).count() == 0
        assert (
            db.execute(text("SELECT to_jsonb(s) FROM auth_sessions s WHERE id = :id"), {"id": parent_id}).scalar_one()
            == before
        )


@pytest.fixture
def reset_tokens(delegated_parent: DelegatedParent) -> tuple[str, str]:
    factory, _, user_id, _ = delegated_parent
    with factory() as db:
        user = db.get(User, user_id)
        user.password_hash = hash_password("Original-password-123!")
        for raw in RESET_TOKENS:
            db.add(
                MagicLinkToken(
                    user_id=user.id,
                    tenant_id=user.tenant_id,
                    region=user.region,
                    email_normalized=user.email_normalized,
                    purpose=MagicLinkPurpose.PASSWORD_RESET,
                    token_hash=delegation.credential_hash(raw),
                    expires_at=datetime.now(UTC) + timedelta(minutes=5),
                )
            )
        db.commit()
    return RESET_TOKENS


@pytest.mark.parametrize("first", ["exchange", "reset"])
def test_password_reset_and_exchange_share_user_first_lock_order(
    delegated_parent: DelegatedParent,
    reset_tokens: tuple[str, str],
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    first: str,
) -> None:
    factory, parent_id, user_id, code = delegated_parent
    holder_ready, waiter_ready = Event(), Event()
    backend_errors: list[str | None] = []
    original_parent_lock = delegation.lock_parent_session

    def before_parent(db: Session, session_id: UUID) -> AuthSession | None:
        if first == "exchange":
            holder_ready.set()
            assert waiter_ready.wait(10), "Reset did not reach its User/session lock"
        return original_parent_lock(db, session_id)

    def before_sql(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: ExecutionContext,
        executemany: bool,
    ) -> None:
        role = context.execution_options.get("rev3_role")
        if role != first and "FROM users" in statement and "FOR UPDATE" in statement:
            waiter_ready.set()

    def after_sql(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: ExecutionContext,
        executemany: bool,
    ) -> None:
        if context.execution_options.get("rev3_role") != "reset" or not statement.startswith("UPDATE auth_sessions"):
            return
        if first == "reset":
            holder_ready.set()
            assert waiter_ready.wait(10), "Exchange did not reach its User lock"
        else:
            # The former reset path reached AuthSession without a User lock.
            # Releasing exchange here deterministically exposes that inversion.
            waiter_ready.set()

    def record_error(context: ExceptionContext) -> None:
        backend_errors.append(getattr(context.original_exception, "sqlstate", None))

    def run_exchange() -> delegation.DelegationToken | str:
        if first != "exchange":
            assert holder_ready.wait(10)
        with factory() as db:
            db.connection(execution_options={"rev3_role": "exchange"})
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            try:
                return delegation.exchange_code(
                    db, code=code, verifier=VERIFIER, tenant_id="anytoolai", region="ru", consumer_id="platform-kernel"
                )
            except delegation.InvalidDelegationError as error:
                return error.code

    def run_reset() -> None:
        if first != "reset":
            assert holder_ready.wait(10)
        with factory() as db:
            db.connection(execution_options={"rev3_role": "reset"})
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            password_reset.confirm_password_reset(
                db,
                token=reset_tokens[0],
                password=RESET_PASSWORD,
                tenant_id="anytoolai",
                region="ru",
            )

    monkeypatch.setattr(delegation, "lock_parent_session", before_parent)
    listeners = [
        ("before_cursor_execute", before_sql),
        ("after_cursor_execute", after_sql),
        ("handle_error", record_error),
    ]
    for name, listener in listeners:
        event.listen(postgres_engine, name, listener)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            exchange = pool.submit(run_exchange)
            reset = pool.submit(run_reset)
            result = exchange.result(timeout=20)
            assert reset.result(timeout=20) is None
    finally:
        for name, listener in listeners:
            event.remove(postgres_engine, name, listener)
    assert backend_errors == []
    with factory() as db:
        assert verify_password(RESET_PASSWORD, db.get(User, user_id).password_hash)
        assert db.get(AuthSession, parent_id).revoked_at is not None
        assert all(row.used_at is not None for row in db.query(MagicLinkToken).all())
        if first == "exchange":
            assert isinstance(result, delegation.DelegationToken)
            with pytest.raises(delegation.InvalidDelegationError, match="backend_parent_authority_invalid"):
                delegation.introspect_token(
                    db,
                    token=result.access_token,
                    tenant_id="anytoolai",
                    region="ru",
                    clock_skew_seconds=5,
                    consumer_id="platform-kernel",
                )
        else:
            assert result == "backend_parent_authority_invalid"
            assert db.query(BackendSessionDelegation).one().exchanged_at is None


def test_concurrent_distinct_password_reset_tokens_have_one_winner(
    delegated_parent: DelegatedParent,
    reset_tokens: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, parent_id, user_id, _ = delegated_parent
    both_read = Barrier(2)
    original_read = password_reset.get_magic_link_token_by_hash_and_purpose

    def read_together(db: Session, *, token_hash: str, purpose: MagicLinkPurpose) -> MagicLinkToken | None:
        result = original_read(db, token_hash=token_hash, purpose=purpose)
        both_read.wait(timeout=10)
        return result

    def reset_once(token: str) -> str:
        with factory() as db:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            try:
                password_reset.confirm_password_reset(
                    db, token=token, password=RESET_PASSWORD, tenant_id="anytoolai", region="ru"
                )
            except InvalidOrExpiredResetTokenError:
                return "invalidated"
        return "committed"

    monkeypatch.setattr(password_reset, "get_magic_link_token_by_hash_and_purpose", read_together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reset_once, reset_tokens))
    assert sorted(results) == ["committed", "invalidated"]
    with factory() as db:
        assert verify_password(RESET_PASSWORD, db.get(User, user_id).password_hash)
        assert db.get(AuthSession, parent_id).revoked_at is not None
        assert all(row.used_at is not None for row in db.query(MagicLinkToken).all())


def test_password_reset_rechecks_token_expiry_after_user_lock_wait(
    delegated_parent: DelegatedParent,
    reset_tokens: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, parent_id, user_id, _ = delegated_parent
    attempting_user_lock = Event()
    original_lock = password_reset.lock_active_user_by_id_and_scope

    def signal_user_lock(db: Session, *, user_id: UUID, tenant_id: str, region: str) -> User | None:
        attempting_user_lock.set()
        return original_lock(db, user_id=user_id, tenant_id=tenant_id, region=region)

    def reset_waiting() -> str:
        with factory() as db:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            try:
                password_reset.confirm_password_reset(
                    db,
                    token=reset_tokens[0],
                    password=RESET_PASSWORD,
                    tenant_id="anytoolai",
                    region="ru",
                )
            except InvalidOrExpiredResetTokenError:
                return "expired"
        return "unexpected-commit"

    monkeypatch.setattr(password_reset, "lock_active_user_by_id_and_scope", signal_user_lock)
    with factory() as writer, ThreadPoolExecutor(max_workers=1) as pool:
        writer.query(User).filter(User.id == user_id).with_for_update().one()
        future = pool.submit(reset_waiting)
        assert attempting_user_lock.wait(10)
        after_expiry = datetime.now(UTC) + timedelta(minutes=6)
        monkeypatch.setattr(password_reset, "utc_now", lambda: after_expiry)
        writer.commit()
        assert future.result(timeout=20) == "expired"
    with factory() as db:
        assert verify_password("Original-password-123!", db.get(User, user_id).password_hash)
        assert db.get(AuthSession, parent_id).revoked_at is None
        assert all(row.used_at is None for row in db.query(MagicLinkToken).all())


def test_populated_step8_forward_migration_preserves_delegations_and_parent_state(
    delegated_parent: DelegatedParent,
    database_test_url: URL,
) -> None:
    factory, _, _, code = delegated_parent
    with factory() as db:
        delegation.exchange_code(
            db, code=code, verifier=VERIFIER, tenant_id="anytoolai", region="ru", consumer_id="platform-kernel"
        )
        delegation.issue_code(
            db,
            token=PARENT_TOKEN,
            tenant_id="anytoolai",
            region="ru",
            code_challenge=delegation.pkce_challenge(VERIFIER),
            consumer_id="platform-kernel",
        )
    with alembic_test_config(database_test_url) as config:
        command.downgrade(config, "20261110_0008")
        with factory() as db:
            before = (
                db.execute(text("SELECT to_jsonb(d) FROM kernel_session_delegations d ORDER BY code_hash"))
                .scalars()
                .all()
            )
            parents = db.execute(text("SELECT to_jsonb(s) FROM auth_sessions s ORDER BY id")).scalars().all()
            assert len(before) == 2 and sum(row["exchanged_at"] is not None for row in before) == 1
        command.upgrade(config, "head")
    with factory() as db:
        after = (
            db.execute(text("SELECT to_jsonb(d) FROM backend_session_delegations d ORDER BY code_hash")).scalars().all()
        )
        assert after == [
            {**{key: value for key, value in row.items() if key != "audience"}, "consumer_id": row["audience"]}
            for row in before
        ]
        assert {row["consumer_id"] for row in after} == {"platform-kernel"}
        assert db.execute(text("SELECT to_jsonb(s) FROM auth_sessions s ORDER BY id")).scalars().all() == parents
        exchanged = next(row for row in after if row["exchanged_at"] is not None)
        assert exchanged["token_hash"] and exchanged["auth_session_id"]


@pytest.mark.parametrize(
    "change",
    [
        {"allowed_products": ["proposal_ai"]},
        {"permissions": ["backend-session:exchange", "backend-session:introspect"]},
        {"technical_source_id": "replacement-source"},
    ],
)
def test_concurrent_stale_installation_cannot_restore_old_consumer_policy(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    change: dict,
) -> None:
    from app.composition.backend_consumers import initialize_backend_consumers
    from app.core.settings import Settings
    from app.infrastructure.queries.backend_policies import (
        BackendPolicyConflict,
        install_policy,
        require_current_policy,
    )
    from app.models import BackendConsumerPolicy
    from apps.api.tests.support.backend_consumers import backend_consumer, second_consumer

    old = backend_consumer()
    newer = backend_consumer(consumer_policy_revision=2, **change)
    factory = postgres_session_factory
    configuration = Settings(backend_consumers=(old, second_consumer()))
    initialize_backend_consumers(configuration, factory)
    # Registry installation first retires recipients. A reused-P digest conflict
    # must roll that retirement back too, including the omitted second consumer.
    with pytest.raises(BackendPolicyConflict):
        initialize_backend_consumers(
            configuration.model_copy(update={"backend_consumers": (backend_consumer(**change),)}), factory
        )
    with factory() as db:
        assert all(row.snapshot_delivery_enabled for row in db.query(BackendConsumerPolicy).all())
        require_current_policy(db, old)
    started = Event()

    def stale_installation() -> str:
        with factory.begin() as db:
            started.set()
            try:
                install_policy(db, old)
            except BackendPolicyConflict:
                return "refused"
        return "unexpected-success"

    with factory.begin() as writer, ThreadPoolExecutor(max_workers=1) as pool:
        install_policy(writer, newer)
        future = pool.submit(stale_installation)
        assert started.wait(10)
        writer.commit()
        assert future.result(timeout=10) == "refused"
    with factory() as db:
        saved = db.get(BackendConsumerPolicy, (old.consumer_id, old.tenant_id, old.region))
        assert (saved.consumer_policy_revision, saved.policy_digest) == (2, newer.policy_digest)
        with pytest.raises(BackendPolicyConflict):
            require_current_policy(db, old)


def test_forward_migration_refuses_to_adopt_foreign_historical_audience(
    delegated_parent: DelegatedParent,
    database_test_url: URL,
) -> None:
    factory, _, _, _ = delegated_parent
    with alembic_test_config(database_test_url) as config:
        command.downgrade(config, "20261110_0008")
        with factory.begin() as db:
            db.execute(text("UPDATE kernel_session_delegations SET audience = 'synthetic-summary'"))
        with pytest.raises(RuntimeError, match="Unexpected historical delegation audience"):
            command.upgrade(config, "head")
        with factory() as db:
            assert (
                db.execute(text("SELECT audience FROM kernel_session_delegations")).scalar_one() == "synthetic-summary"
            )
            assert db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20261110_0008"


@pytest.mark.parametrize("retained", ["policy", "foreign_delegation"])
def test_consumer_downgrade_refuses_history_without_changing_schema_or_data(
    delegated_parent: DelegatedParent, database_test_url: URL, retained: str,
) -> None:
    from app.infrastructure.queries.backend_policies import BackendPolicyConflict, install_policy
    from app.models import BackendConsumerPolicy
    from apps.api.tests.support.backend_consumers import backend_consumer

    factory, _, _, _ = delegated_parent
    current = backend_consumer(consumer_policy_revision=2)
    with factory.begin() as db:
        if retained == "policy":
            install_policy(db, current)
            db.query(BackendConsumerPolicy).one().snapshot_delivery_enabled = False
        else:
            db.query(BackendSessionDelegation).one().consumer_id = "synthetic-summary"

    tables = ("auth_sessions", "backend_session_delegations", "backend_consumer_policies", "alembic_version")

    def snapshot() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        with factory() as db:
            schema = {
                name: [column["name"] for column in inspect(db.bind).get_columns(name)]
                for name in inspect(db.bind).get_table_names()
            }
            rows = {
                name: list(db.scalars(text(f"SELECT to_jsonb(t)::text FROM {name} t ORDER BY to_jsonb(t)::text")))
                for name in tables
            }
            return schema, rows

    before = snapshot()
    with alembic_test_config(database_test_url) as config:
        with pytest.raises(RuntimeError, match="Consumer .*downgrade is unsafe"):
            command.downgrade(config, "20261110_0008")
    assert snapshot() == before
    if retained == "policy":
        for stale in (backend_consumer(), backend_consumer(consumer_policy_revision=2, allowed_products=["proposal_ai"])):
            with factory.begin() as db, pytest.raises(BackendPolicyConflict):
                install_policy(db, stale)


def test_issuance_cleans_delegations_with_large_expired_parent_history(delegated_parent: DelegatedParent) -> None:
    factory, _, user_id, _ = delegated_parent
    now = datetime.now(UTC)
    with factory.begin() as db:
        db.query(BackendSessionDelegation).one().code_expires_at = now - timedelta(seconds=1)
        # Expired auth sessions are retained; their count must not become a SQL
        # bind-parameter limit on an otherwise valid authorization request.
        db.execute(text("""
            INSERT INTO auth_sessions
                (id, tenant_id, region, user_id, token_hash, created_at, expires_at, last_seen_at)
            SELECT gen_random_uuid(), 'anytoolai', 'ru', :user_id,
                md5('synthetic-old-' || i::text) || md5('synthetic-suffix-' || i::text),
                :created_at, :expires_at, :created_at
            FROM generate_series(1, 32767) i
        """), {
            "user_id": user_id, "created_at": now - timedelta(days=31), "expires_at": now - timedelta(days=1),
        })
        db.execute(text("""
            INSERT INTO backend_session_delegations
                (id, auth_session_id, consumer_id, code_hash, code_challenge, code_expires_at)
            SELECT gen_random_uuid(), id, 'platform-kernel', :code_hash, :challenge, expires_at
            FROM auth_sessions WHERE user_id = :user_id AND expires_at <= :now ORDER BY id LIMIT 1
        """), {
            "user_id": user_id, "now": now, "challenge": delegation.pkce_challenge(VERIFIER),
            "code_hash": delegation.credential_hash("synthetic-old-parent-code"),
        })
    with factory() as db:
        issued = delegation.issue_code(
            db, token=PARENT_TOKEN, tenant_id="anytoolai", region="ru",
            code_challenge=delegation.pkce_challenge(VERIFIER), consumer_id="platform-kernel",
        )
        assert db.query(AuthSession).filter_by(user_id=user_id).count() == 32768
        assert db.query(BackendSessionDelegation).one().code_hash == delegation.credential_hash(issued.code)
        token = delegation.exchange_code(
            db, code=issued.code, verifier=VERIFIER, tenant_id="anytoolai", region="ru", consumer_id="platform-kernel",
        )
        assert delegation.introspect_token(
            db, token=token.access_token, tenant_id="anytoolai", region="ru", clock_skew_seconds=5,
            consumer_id="platform-kernel",
        ).user_id == user_id


@pytest.mark.parametrize("expired", [False, True])
def test_exchange_rereads_code_after_concurrent_issuance_cleanup(
    delegated_parent: DelegatedParent, monkeypatch: pytest.MonkeyPatch, expired: bool,
) -> None:
    factory, _, _, code = delegated_parent
    if expired:
        with factory.begin() as db:
            db.query(BackendSessionDelegation).one().code_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    read = Event()
    resume = Event()
    original = delegation.read_delegation

    def pause_after_read(
        db: Session, *, credential_hash: str, by_code: bool,
    ) -> tuple[BackendSessionDelegation, AuthSession, User] | None:
        found = original(db, credential_hash=credential_hash, by_code=by_code)
        read.set()
        assert resume.wait(10)
        return found

    monkeypatch.setattr(delegation, "read_delegation", pause_after_read)

    def exchange_waiting() -> delegation.DelegationToken | delegation.DelegationRefusal:
        with factory() as db:
            try:
                return delegation.exchange_code(
                    db, code=code, verifier=VERIFIER, tenant_id="anytoolai", region="ru", consumer_id="platform-kernel",
                )
            except delegation.InvalidDelegationError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(exchange_waiting)
        try:
            assert read.wait(10)
            with factory() as db:
                delegation.issue_code(
                    db, token=PARENT_TOKEN, tenant_id="anytoolai", region="ru",
                    code_challenge=delegation.pkce_challenge(VERIFIER), consumer_id="platform-kernel",
                )
        finally:
            resume.set()
        result = future.result(timeout=10)
    with factory() as db:
        if expired:
            assert result == delegation.DelegationRefusal.CODE_INVALID
            assert db.query(BackendSessionDelegation).count() == 1
        else:
            assert isinstance(result, delegation.DelegationToken)
            assert db.query(BackendSessionDelegation).count() == 2


def test_issuance_cleanup_preserves_exchange_committed_while_waiting_for_user(
    delegated_parent: DelegatedParent, monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, _, _, code = delegated_parent
    exchanging, issuing = Event(), Event()
    now = datetime.now(UTC)
    monkeypatch.setattr(delegation, "utc_now", lambda: now)
    original_lock = delegation.lock_active_user_by_id_and_scope

    def signal_issuer(db: Session, *, user_id: UUID, tenant_id: str, region: str) -> User | None:
        if db.info.get("issuer"):
            issuing.set()
        return original_lock(db, user_id=user_id, tenant_id=tenant_id, region=region)

    def before_exchange_commit(db: Session) -> None:
        nonlocal now
        exchanging.set()
        assert issuing.wait(10)
        now += timedelta(seconds=61)

    monkeypatch.setattr(delegation, "lock_active_user_by_id_and_scope", signal_issuer)

    def exchange_first() -> delegation.DelegationToken:
        with factory() as db:
            event.listen(db, "before_commit", before_exchange_commit, once=True)
            return delegation.exchange_code(
                db, code=code, verifier=VERIFIER, tenant_id="anytoolai", region="ru", consumer_id="platform-kernel",
            )

    def issue_waiting() -> delegation.DelegationCode:
        assert exchanging.wait(10)
        with factory() as db:
            db.info["issuer"] = True
            return delegation.issue_code(
                db, token=PARENT_TOKEN, tenant_id="anytoolai", region="ru",
                code_challenge=delegation.pkce_challenge(VERIFIER), consumer_id="platform-kernel",
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        exchange_result = pool.submit(exchange_first)
        issue_result = pool.submit(issue_waiting)
        token = exchange_result.result(timeout=15)
        issued = issue_result.result(timeout=15)
    with factory() as db:
        assert db.query(BackendSessionDelegation).count() == 2
        assert db.query(BackendSessionDelegation).filter_by(code_hash=delegation.credential_hash(issued.code)).one()
        assert delegation.introspect_token(
            db, token=token.access_token, tenant_id="anytoolai", region="ru", clock_skew_seconds=5,
            consumer_id="platform-kernel",
        ).user_id == token.identity.user_id
