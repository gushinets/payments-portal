from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event

import pytest
from alembic import command
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domains.purchases.transactions import (
    bind_external_create,
    claim_external_create,
    release_purchase_scope,
    reserve_purchase_scope,
)
from app.infrastructure.persistence import purchase_scopes
from app.infrastructure.persistence.external_creates import ExternalCreateClaim
from app.infrastructure.persistence.purchase_scopes import (
    PurchaseScopeConflict,
    PurchaseScopeIdentity,
    PurchaseScopeReleaseEvidence,
    PurchaseScopeReservation,
)
from app.models import (
    BillingPurchaseScopeHold,
    BillingWorkItem,
    ExternalCreateOperation,
    ExternalCreateOperationKind,
    ExternalCreateOperationState,
    PurchaseIntent,
    PurchaseScopeHoldState,
    PurchaseScopeReleaseKind,
)
from apps.api.tests.support.postgres import alembic_test_config, reset_public_schema
from apps.api.tests.test_target_persistence_postgres import (
    CUSTOMER_ID,
    PURCHASE_ID,
    SECOND_USER_ID,
    SUBSCRIPTION_ID,
    USER_ID,
    _insert_purchase,
    _seed_purchase_graph,
    _seed_subscription_graph,
)


pytestmark = pytest.mark.postgres
SCOPE = PurchaseScopeIdentity(USER_ID, "product-a", "anytoolai", "ru", "account-a")
NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)


def _reserve(factory: sessionmaker[Session], key: str) -> PurchaseScopeReservation:
    def create(db: Session) -> PurchaseIntent:
        purchase_id = uuid.uuid4()
        _insert_purchase(db.connection(), purchase_id, key)
        return db.scalars(select(PurchaseIntent).where(PurchaseIntent.purchase_intent_id == purchase_id)).one()

    return reserve_purchase_scope(
        factory,
        scope=SCOPE,
        client_idempotency_key=key,
        create_intent=create,
        replay_matches=lambda purchase: purchase.accepted_snapshot == {},
    )


@pytest.mark.parametrize("same_key", [False, True])
def test_twenty_reservations_have_one_durable_owner(migrated_database: Engine, same_key: bool) -> None:
    with migrated_database.begin() as connection:
        _seed_purchase_graph(connection)
    factory = sessionmaker(migrated_database)
    barrier = Barrier(20)

    def reserve(index: int) -> PurchaseScopeReservation:
        barrier.wait()
        return _reserve(factory, "same-key" if same_key else f"different-key-{index}")

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(reserve, range(20)))
    assert len({result.hold_id for result in results}) == 1
    assert len({result.purchase_intent_id for result in results}) == 1
    assert sum(not result.replay and not result.occupied for result in results) == 1
    assert sum(result.replay for result in results) == (19 if same_key else 0)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PurchaseIntent)) == 1
        assert db.scalar(select(func.count()).select_from(BillingPurchaseScopeHold)) == 1
    # Fresh session factory models process restart; no source/catalog client exists.
    replay = _reserve(sessionmaker(migrated_database), "same-key" if same_key else "new-after-restart")
    assert replay.replay if same_key else replay.occupied


def test_changed_same_key_meaning_conflicts_without_new_intent(migrated_database: Engine) -> None:
    with migrated_database.begin() as connection:
        _seed_purchase_graph(connection)
    factory = sessionmaker(migrated_database)
    _reserve(factory, "same-key")
    with pytest.raises(PurchaseScopeConflict, match="different accepted meaning"):
        reserve_purchase_scope(
            factory,
            scope=SCOPE,
            client_idempotency_key="same-key",
            create_intent=lambda db: pytest.fail("replay must not create legal evidence/intent"),
            replay_matches=lambda purchase: False,
        )


def test_replay_locks_hold_committed_after_initial_scope_lookup(
    migrated_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with migrated_database.begin() as connection:
        _seed_purchase_graph(connection)
    factory = sessionmaker(migrated_database)
    initial_lookup = Event()
    winner_committed = Event()
    original_lock = purchase_scopes.lock_purchase_scope

    def pause_after_missing_hold(db: Session, user_id: uuid.UUID, product_id: str) -> BillingPurchaseScopeHold | None:
        hold = original_lock(db, user_id, product_id)
        if hold is None and not initial_lookup.is_set():
            initial_lookup.set()
            assert winner_committed.wait(timeout=10), "winner did not commit before replay lookup"
        return hold

    monkeypatch.setattr(purchase_scopes, "lock_purchase_scope", pause_after_missing_hold)
    with ThreadPoolExecutor(max_workers=1) as executor:
        follower = executor.submit(_reserve, factory, "same-key")
        try:
            assert initial_lookup.wait(timeout=10), "follower did not reach initial scope lookup"
            winner = _reserve(factory, "same-key")
        finally:
            winner_committed.set()
        replay = follower.result(timeout=10)
    assert winner.hold_id is not None
    assert replay.replay and not replay.occupied
    assert (replay.hold_id, replay.purchase_intent_id, replay.ownership_epoch) == (
        winner.hold_id,
        winner.purchase_intent_id,
        winner.ownership_epoch,
    )


@pytest.mark.parametrize("without_intent", [False, True])
def test_historical_unpaid_subscription_retains_scope(migrated_database: Engine, without_intent: bool) -> None:
    with migrated_database.begin() as connection:
        _seed_subscription_graph(connection)
        connection.execute(
            text("UPDATE purchase_intents SET state = :state"),
            {
                "state": "resolved_no_external_effect" if without_intent else "linked",
            },
        )
        connection.execute(
            text("""
            UPDATE external_subscriptions SET financial_access_status = 'blocked', lifecycle_status = 'inactive',
                purchase_intent_id = CASE WHEN :without_intent THEN NULL ELSE purchase_intent_id END
        """),
            {"without_intent": without_intent},
        )
    factory = sessionmaker(migrated_database)
    result = _reserve(factory, "cannot-bypass-unpaid")
    assert result.occupied and result.subscription_id == SUBSCRIPTION_ID
    assert result.purchase_intent_id == (None if without_intent else PURCHASE_ID)
    with pytest.raises(PurchaseScopeConflict, match="retains purchase hold"):
        release_purchase_scope(
            factory,
            scope=SCOPE,
            expected_epoch=1,
            evidence=PurchaseScopeReleaseEvidence(
                PurchaseScopeReleaseKind.VERIFIED_TERMINAL,
                "subscription-point-read",
                "test-reader",
                NOW,
            ),
        )
    assert _reserve(sessionmaker(migrated_database), "after-two-hours").occupied
    with migrated_database.connect() as connection:
        assert (
            connection.execute(text("SELECT primary_subscription_id FROM billing_product_access_scopes")).scalar_one()
            is None
        )


def _operation(
    factory: sessionmaker[Session], kind: ExternalCreateOperationKind, purchase_id: uuid.UUID | None
) -> uuid.UUID:
    with factory.begin() as db:
        operation = ExternalCreateOperation(
            customer_id=CUSTOMER_ID,
            external_billing_account_id="account-a",
            purchase_intent_id=purchase_id,
            operation_kind=kind,
            operation_state=ExternalCreateOperationState.UNSENT,
            request_correlation_key=str(uuid.uuid4()),
        )
        db.add(operation)
        db.flush()
        return operation.create_operation_id


def test_potential_send_commits_clock_and_one_due_item_before_crash(migrated_database: Engine) -> None:
    with migrated_database.begin() as connection:
        _seed_purchase_graph(connection)
    factory = sessionmaker(migrated_database)
    reservation = _reserve(factory, "claim-test")
    operation_id = _operation(factory, ExternalCreateOperationKind.AGREEMENT, reservation.purchase_intent_id)
    barrier = Barrier(20)

    def claim(index: int) -> ExternalCreateClaim | None:
        barrier.wait()
        return claim_external_create(sessionmaker(migrated_database), operation_id, now=NOW)

    with ThreadPoolExecutor(max_workers=20) as executor:
        claims = [claim for claim in executor.map(claim, range(20)) if claim is not None]
    assert len(claims) == 1
    with factory() as db:
        operation = db.get(ExternalCreateOperation, operation_id)
        assert operation is not None
        assert operation.operation_state == ExternalCreateOperationState.POSSIBLE_SEND
        assert operation.unknown_since == NOW
        assert operation.unknown_recovery_deadline_at == NOW + timedelta(hours=2)
        assert operation.scope_ownership_epoch == 1
        item = db.scalars(select(BillingWorkItem)).one()
        assert item.next_attempt_at == NOW + timedelta(hours=2)
    assert claim_external_create(sessionmaker(migrated_database), operation_id, now=NOW + timedelta(days=2)) is None
    with pytest.raises(PurchaseScopeConflict):
        release_purchase_scope(
            factory,
            scope=SCOPE,
            expected_epoch=1,
            evidence=PurchaseScopeReleaseEvidence(
                PurchaseScopeReleaseKind.AUTHORITATIVE_NO_EFFECT,
                "zero-result-is-insufficient",
                "reader",
                NOW,
            ),
        )
    # A duplicate work item cannot make two independent recovery obligations.
    with pytest.raises(IntegrityError), migrated_database.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO billing_work_items (work_item_id, work_kind, scope_kind, scope_reference, coalescing_key,
                payload_schema_version, payload_document, next_attempt_at, work_state)
            SELECT gen_random_uuid(), work_kind, scope_kind, scope_reference, coalescing_key,
                payload_schema_version, payload_document, next_attempt_at, work_state FROM billing_work_items
        """)
        )
    assert bind_external_create(factory, claims[0], verified_external_object_id="agreement-proof", now=NOW)
    with factory() as db:
        assert db.scalars(select(BillingWorkItem.work_state)).one() == "completed"
    # Permanent operation identity remains occupied after successful binding.
    with pytest.raises(IntegrityError):
        _operation(factory, ExternalCreateOperationKind.AGREEMENT, reservation.purchase_intent_id)
    with pytest.raises(DatabaseError), migrated_database.begin() as connection:
        connection.execute(
            text("DELETE FROM external_create_operations WHERE create_operation_id = :id"), {"id": operation_id}
        )


def test_twenty_direct_hold_writes_cannot_bypass_different_keys(migrated_database: Engine) -> None:
    purchase_ids = [uuid.uuid4() for _ in range(20)]
    with migrated_database.begin() as connection:
        _seed_purchase_graph(connection)
        for index, purchase_id in enumerate(purchase_ids):
            _insert_purchase(connection, purchase_id, f"direct-key-{index}")
    barrier = Barrier(20)

    def insert_hold(purchase_id: uuid.UUID) -> bool:
        barrier.wait()
        try:
            with Session(migrated_database) as db, db.begin():
                db.add(
                    BillingPurchaseScopeHold(
                        user_id=USER_ID,
                        product_id="product-a",
                        tenant_id="anytoolai",
                        region="ru",
                        external_billing_account_id="account-a",
                        purchase_intent_id=purchase_id,
                    )
                )
                db.flush()
            return True
        except IntegrityError:
            return False

    with ThreadPoolExecutor(max_workers=20) as executor:
        assert sum(executor.map(insert_hold, purchase_ids)) == 1


def test_direct_potential_send_requires_clock_and_committed_due_item(migrated_database: Engine) -> None:
    with migrated_database.begin() as connection:
        _seed_purchase_graph(connection)
    factory = sessionmaker(migrated_database)
    operation_id = _operation(factory, ExternalCreateOperationKind.CUSTOMER, None)
    with pytest.raises(IntegrityError), migrated_database.begin() as connection:
        connection.execute(text("UPDATE external_create_operations SET operation_state = 'possible_send'"))
    with pytest.raises(DatabaseError), migrated_database.begin() as connection:
        connection.execute(
            text("""
            UPDATE external_create_operations SET operation_state = 'possible_send', send_fencing_token = 1,
                unknown_since = now(), unknown_recovery_deadline_at = now() + interval '2 hours'
        """)
        )
    claim = claim_external_create(factory, operation_id, now=NOW)
    assert claim is not None
    with pytest.raises(DatabaseError), migrated_database.begin() as connection:
        connection.execute(text("UPDATE external_create_operations SET operation_state = 'unsent'"))
    with pytest.raises(DatabaseError), migrated_database.begin() as connection:
        connection.execute(
            text(
                "UPDATE external_create_operations SET unknown_recovery_deadline_at = unknown_since + interval '3 hours'"
            )
        )
    assert bind_external_create(factory, claim, verified_external_object_id="customer-bound", now=NOW)
    with pytest.raises(IntegrityError):
        _operation(factory, ExternalCreateOperationKind.CUSTOMER, None)


@pytest.mark.parametrize("field", ["external_subscription_id", "external_agreement_id"])
def test_subscription_provider_ids_are_unique_within_account(migrated_database: Engine, field: str) -> None:
    with migrated_database.begin() as connection:
        _seed_subscription_graph(connection)
        connection.execute(text(f"UPDATE external_subscriptions SET {field} = 'provider-object'"))
        # A separate account may use the same provider-local identifier.
        second_customer = uuid.uuid4()
        connection.execute(
            text("""
            INSERT INTO external_billing_customers (customer_id, external_billing_account_id, user_id, billing_customer_key)
            VALUES (:id, 'account-b', :user_id, 'customer-key-b')
        """),
            {"id": second_customer, "user_id": SECOND_USER_ID},
        )
        connection.execute(
            text(f"""
            INSERT INTO external_subscriptions (subscription_id, external_billing_account_id, customer_id, user_id,
                product_id, {field}, lifecycle_status, financial_access_status, commercial_access_status,
                last_authoritative_read_at, projection_valid_until)
            VALUES (gen_random_uuid(), 'account-b', :customer_id, :user_id, 'product-a', 'provider-object',
                'inactive', 'blocked', 'ineligible', now(), now())
        """),
            {"customer_id": second_customer, "user_id": SECOND_USER_ID},
        )
    with pytest.raises(IntegrityError), migrated_database.begin() as connection:
        connection.execute(
            text(f"""
            INSERT INTO external_subscriptions (subscription_id, external_billing_account_id, customer_id, user_id,
                product_id, {field}, lifecycle_status, financial_access_status, commercial_access_status,
                last_authoritative_read_at, projection_valid_until)
            VALUES (gen_random_uuid(), 'account-a', :customer_id, :user_id, 'product-other', 'provider-object',
                'inactive', 'blocked', 'ineligible', now(), now())
        """),
            {"customer_id": CUSTOMER_ID, "user_id": USER_ID},
        )


def test_manual_release_preserves_history_and_fences_late_response(migrated_database: Engine) -> None:
    with migrated_database.begin() as connection:
        _seed_purchase_graph(connection)
    factory = sessionmaker(migrated_database)
    first = _reserve(factory, "old-purchase")
    operation_id = _operation(factory, ExternalCreateOperationKind.SUBSCRIPTION, first.purchase_intent_id)
    claim = claim_external_create(factory, operation_id, now=NOW)
    assert claim is not None
    release_purchase_scope(
        factory,
        scope=SCOPE,
        expected_epoch=1,
        evidence=PurchaseScopeReleaseEvidence(
            PurchaseScopeReleaseKind.AUDITED_SUPPORT,
            "support-case/explicit-no-duplicate-decision",
            "support-a",
            NOW,
        ),
    )
    assert not bind_external_create(factory, claim, verified_external_object_id="late-object", now=NOW)
    second = _reserve(sessionmaker(migrated_database), "new-purchase")
    assert second.purchase_intent_id != first.purchase_intent_id and second.ownership_epoch == 3
    assert not bind_external_create(factory, claim, verified_external_object_id="late-object", now=NOW)
    with factory() as db:
        hold = db.get(BillingPurchaseScopeHold, second.hold_id)
        assert hold is not None and hold.hold_state == PurchaseScopeHoldState.HELD
        assert hold.release_evidence_document["releases"][0]["purchase_intent_id"] == str(first.purchase_intent_id)
        assert db.get(PurchaseIntent, first.purchase_intent_id) is not None
        assert db.get(ExternalCreateOperation, operation_id).bound_external_object_id is None


def test_no_effect_release_and_stale_release_epoch(migrated_database: Engine) -> None:
    with migrated_database.begin() as connection:
        _seed_purchase_graph(connection)
    factory = sessionmaker(migrated_database)
    first = _reserve(factory, "no-effect")
    proof = PurchaseScopeReleaseEvidence(
        PurchaseScopeReleaseKind.AUTHORITATIVE_NO_EFFECT, "proof/point-read", "reader", NOW
    )
    release_purchase_scope(factory, scope=SCOPE, expected_epoch=1, evidence=proof)
    with pytest.raises(PurchaseScopeConflict):
        release_purchase_scope(factory, scope=SCOPE, expected_epoch=1, evidence=proof)
    assert _reserve(factory, "replacement").ownership_epoch == 3
    assert _reserve(factory, "no-effect").purchase_intent_id == first.purchase_intent_id


@pytest.mark.parametrize(
    "field,value",
    [
        ("user_id", SECOND_USER_ID),
        ("external_billing_account_id", "other-account"),
        ("product_id", "other-product"),
        ("region", "other-region"),
    ],
)
def test_scope_foreign_keys_reject_wrong_owner(migrated_database: Engine, field: str, value: object) -> None:
    with migrated_database.begin() as connection:
        _seed_purchase_graph(connection)
        _insert_purchase(connection)
    values = dict(
        user_id=USER_ID,
        product_id="product-a",
        tenant_id="anytoolai",
        region="ru",
        external_billing_account_id="account-a",
        purchase_intent_id=PURCHASE_ID,
    )
    values[field] = value
    with pytest.raises(IntegrityError), Session(migrated_database) as db, db.begin():
        db.add(BillingPurchaseScopeHold(**values))
        db.flush()


def test_provider_bindings_are_account_scoped_before_subscription(migrated_database: Engine) -> None:
    with migrated_database.begin() as connection:
        _seed_purchase_graph(connection)
        _insert_purchase(connection)
        second_customer = uuid.uuid4()
        second_event = uuid.uuid4()
        parameters = {"customer_id": second_customer, "event_id": second_event, "user_id": SECOND_USER_ID}
        connection.execute(
            text("""
            INSERT INTO external_billing_customers (customer_id, external_billing_account_id, user_id, billing_customer_key)
            VALUES (:customer_id, 'account-a', :user_id, 'second-user-key')
        """),
            parameters,
        )
        connection.execute(
            text("""
            INSERT INTO legal_acceptance_events (id, tenant_id, region, user_id, external_billing_account_id,
                billing_offer_id, accepted_commercial_fingerprint)
            VALUES (:event_id, 'anytoolai', 'ru', :user_id, 'account-a', 'offer-a', 'fingerprint-a')
        """),
            parameters,
        )
        connection.execute(
            text("""
            INSERT INTO purchase_intents (purchase_intent_id, user_id, external_billing_account_id, customer_id,
                product_id, billing_offer_id, mapping_revision_id, accepted_commercial_fingerprint, client_idempotency_key,
                accepted_snapshot_schema_version, accepted_snapshot, legal_acceptance_event_id)
            SELECT gen_random_uuid(), :user_id, external_billing_account_id, :customer_id, product_id,
                billing_offer_id, mapping_revision_id, accepted_commercial_fingerprint, 'second-intent',
                accepted_snapshot_schema_version, accepted_snapshot, :event_id FROM purchase_intents
        """),
            parameters,
        )
        connection.execute(
            text(
                "UPDATE external_billing_customers SET provider_customer_id = 'provider-user' WHERE customer_id = :id"
            ),
            {"id": CUSTOMER_ID},
        )
        connection.execute(
            text("""
            INSERT INTO external_billing_customers (customer_id, external_billing_account_id, user_id, billing_customer_key, provider_customer_id)
            VALUES (gen_random_uuid(), 'other-account', :user_id, 'other-account-key', 'provider-user')
        """),
            {"user_id": SECOND_USER_ID},
        )
    with pytest.raises(IntegrityError), migrated_database.begin() as connection:
        connection.execute(
            text("""
            UPDATE external_billing_customers SET provider_customer_id = 'provider-user'
            WHERE external_billing_account_id = 'account-a' AND user_id = :user_id
        """),
            {"user_id": SECOND_USER_ID},
        )
    with migrated_database.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO external_create_operations (create_operation_id, external_billing_account_id, operation_kind,
                customer_id, purchase_intent_id, request_correlation_key, operation_state, bound_external_object_id, resolved_at)
            SELECT gen_random_uuid(), 'account-a', 'agreement', customer_id, purchase_intent_id,
                purchase_intent_id::text, 'bound', 'dedicated-agreement', now()
            FROM purchase_intents WHERE purchase_intent_id = :id
        """),
            {"id": PURCHASE_ID},
        )
    with pytest.raises(IntegrityError), migrated_database.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO external_create_operations (create_operation_id, external_billing_account_id, operation_kind,
                customer_id, purchase_intent_id, request_correlation_key, operation_state, bound_external_object_id, resolved_at)
            SELECT gen_random_uuid(), 'account-a', 'agreement', customer_id, purchase_intent_id,
                purchase_intent_id::text, 'bound', 'dedicated-agreement', now()
            FROM purchase_intents WHERE purchase_intent_id <> :id
        """),
            {"id": PURCHASE_ID},
        )
    with pytest.raises(IntegrityError), migrated_database.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO external_create_operations (create_operation_id, external_billing_account_id, operation_kind,
                customer_id, request_correlation_key, operation_state)
            VALUES (gen_random_uuid(), 'wrong-account', 'customer', :customer_id, 'wrong-account-correlation', 'unsent')
        """),
            {"customer_id": CUSTOMER_ID},
        )


def test_populated_baseline_upgrade_retains_evidence_and_quarantines_legacy_create(
    postgres_engine: Engine, database_test_url: URL
) -> None:
    reset_public_schema(postgres_engine)
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "20261001_0002")
        with postgres_engine.begin() as connection:
            _seed_subscription_graph(connection)
            connection.execute(text("UPDATE purchase_intents SET state = 'linked'"))
            connection.execute(text("UPDATE external_subscriptions SET financial_access_status = 'blocked'"))
            connection.execute(
                text("""
                INSERT INTO external_create_operations (create_operation_id, operation_kind, customer_id,
                    purchase_intent_id, request_correlation_key, operation_state)
                VALUES (gen_random_uuid(), 'agreement', :customer_id, :purchase_id, 'legacy-create', 'pending')
            """),
                {"customer_id": CUSTOMER_ID, "purchase_id": PURCHASE_ID},
            )
        command.upgrade(config, "head")
        with Session(postgres_engine) as db:
            hold = db.scalars(select(BillingPurchaseScopeHold)).one()
            assert hold.subscription_id == SUBSCRIPTION_ID and hold.purchase_intent_id == PURCHASE_ID
            assert db.get(PurchaseIntent, PURCHASE_ID).accepted_snapshot == {}
            operation = db.scalars(select(ExternalCreateOperation)).one()
            assert operation.external_billing_account_id == "account-a"
            assert operation.operation_state == ExternalCreateOperationState.MANUAL_REVIEW
            assert operation.unknown_recovery_deadline_at == operation.unknown_since + timedelta(hours=2)
            assert db.scalars(select(BillingWorkItem)).one().next_attempt_at == operation.unknown_recovery_deadline_at
        with pytest.raises(RuntimeError, match="forward-only"):
            command.downgrade(config, "20261001_0002")
    for table, column, expression, value in (
        ("purchase_intents", "accepted_snapshot", "CAST(:value AS jsonb)", '{"changed":true}'),
        ("legal_acceptance_events", "accepted_commercial_fingerprint", ":value", "changed"),
    ):
        with pytest.raises(DatabaseError), postgres_engine.begin() as connection:
            connection.execute(text(f"UPDATE {table} SET {column} = {expression}"), {"value": value})


@pytest.mark.parametrize("conflict", ["historical_scope", "provider_customer", "bound_agreement"])
def test_upgrade_refuses_conflicting_populated_baseline(
    postgres_engine: Engine, database_test_url: URL, conflict: str
) -> None:
    reset_public_schema(postgres_engine)
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "20261001_0002")
        with postgres_engine.begin() as connection:
            _seed_purchase_graph(connection)
            _insert_purchase(connection)
            if conflict in ("historical_scope", "bound_agreement"):
                _insert_purchase(connection, uuid.uuid4(), "second-key")
            if conflict == "provider_customer":
                connection.execute(text("UPDATE external_billing_customers SET provider_customer_id = 'same-provider'"))
                connection.execute(
                    text("""
                    INSERT INTO external_billing_customers (customer_id, external_billing_account_id, user_id, billing_customer_key, provider_customer_id)
                    VALUES (gen_random_uuid(), 'account-a', :user_id, 'conflicting-key', 'same-provider')
                """),
                    {"user_id": SECOND_USER_ID},
                )
            if conflict == "bound_agreement":
                connection.execute(
                    text("""
                    INSERT INTO external_create_operations (create_operation_id, operation_kind, customer_id, purchase_intent_id,
                        request_correlation_key, operation_state, bound_external_object_id, resolved_at)
                    SELECT gen_random_uuid(), 'agreement', customer_id, purchase_intent_id,
                        purchase_intent_id::text, 'bound', 'same-agreement', now() FROM purchase_intents
                """)
                )
        with pytest.raises(DatabaseError):
            command.upgrade(config, "head")
    assert "billing_purchase_scope_holds" not in inspect(postgres_engine).get_table_names()
    with postgres_engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20261001_0002"
