from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DatabaseError, IntegrityError


pytestmark = pytest.mark.postgres


USER_ID = uuid.UUID("10000000-0000-4000-8000-000000000001")
SECOND_USER_ID = uuid.UUID("10000000-0000-4000-8000-000000000002")
CUSTOMER_ID = uuid.UUID("20000000-0000-4000-8000-000000000001")
MAPPING_ID = uuid.UUID("30000000-0000-4000-8000-000000000001")
LEGAL_EVENT_ID = uuid.UUID("40000000-0000-4000-8000-000000000001")
PURCHASE_ID = uuid.UUID("50000000-0000-4000-8000-000000000001")
SCOPE_ID = uuid.UUID("60000000-0000-4000-8000-000000000001")
SUBSCRIPTION_ID = uuid.UUID("70000000-0000-4000-8000-000000000001")
SECOND_SUBSCRIPTION_ID = uuid.UUID("70000000-0000-4000-8000-000000000002")


def _insert_user(connection: Connection, user_id: uuid.UUID, email: str) -> None:
    connection.execute(
        text(
            "INSERT INTO users "
            "(id, tenant_id, region, email, email_normalized, status, metadata) "
            "VALUES (:id, 'anytoolai', 'ru', :email, :email, 'active', '{}'::jsonb)"
        ),
        {"id": user_id, "email": email},
    )


def _seed_purchase_graph(connection: Connection) -> None:
    _insert_user(connection, USER_ID, "billing@example.com")
    _insert_user(connection, SECOND_USER_ID, "second@example.com")
    connection.execute(
        text(
            "INSERT INTO commercial_mapping_revisions ("
            "mapping_revision_id, external_billing_account_id, billing_offer_id, revision_number, "
            "manifest_version, catalog_version, catalog_digest, mapping_schema_version, mapping_document, "
            "published_at, published_by_principal) VALUES ("
            ":id, 'account-a', 'offer-a', 1, 'manifest-a', NULL, 'digest-a', 'mapping-v1', "
            "'{}'::jsonb, now(), 'principal-a')"
        ),
        {"id": MAPPING_ID},
    )
    connection.execute(
        text(
            "INSERT INTO external_billing_customers ("
            "customer_id, external_billing_account_id, user_id, billing_customer_key, binding_state) "
            "VALUES (:id, 'account-a', :user_id, 'customer-key-a', 'unbound')"
        ),
        {"id": CUSTOMER_ID, "user_id": USER_ID},
    )
    connection.execute(
        text(
            "INSERT INTO legal_acceptance_events ("
            "id, tenant_id, region, user_id, external_billing_account_id, billing_offer_id, "
            "accepted_commercial_fingerprint, ip, user_agent) VALUES ("
            ":id, 'anytoolai', 'ru', :user_id, 'account-a', 'offer-a', 'fingerprint-a', "
            "'192.0.2.1', 'test-agent')"
        ),
        {"id": LEGAL_EVENT_ID, "user_id": USER_ID},
    )


def _insert_purchase(
    connection: Connection,
    purchase_id: uuid.UUID = PURCHASE_ID,
    idempotency_key: str = "idempotency-a",
) -> None:
    connection.execute(
        text(
            "INSERT INTO purchase_intents ("
            "purchase_intent_id, user_id, external_billing_account_id, customer_id, product_id, "
            "billing_offer_id, mapping_revision_id, accepted_commercial_fingerprint, "
            "client_idempotency_key, state, accepted_snapshot_schema_version, accepted_snapshot, "
            "legal_acceptance_event_id) VALUES ("
            ":purchase_id, :user_id, 'account-a', :customer_id, 'product-a', 'offer-a', :mapping_id, "
            "'fingerprint-a', :idempotency_key, 'created', 'snapshot-v1', '{}'::jsonb, :legal_event_id)"
        ),
        {
            "purchase_id": purchase_id,
            "user_id": USER_ID,
            "customer_id": CUSTOMER_ID,
            "mapping_id": MAPPING_ID,
            "idempotency_key": idempotency_key,
            "legal_event_id": LEGAL_EVENT_ID,
        },
    )


def _seed_subscription_graph(connection: Connection) -> None:
    _seed_purchase_graph(connection)
    _insert_purchase(connection)
    connection.execute(
        text(
            "INSERT INTO billing_product_access_scopes "
            "(access_scope_id, user_id, product_id) VALUES (:id, :user_id, 'product-a')"
        ),
        {"id": SCOPE_ID, "user_id": USER_ID},
    )
    connection.execute(
        text(
            "INSERT INTO external_subscriptions ("
            "subscription_id, external_billing_account_id, customer_id, user_id, product_id, "
            "purchase_intent_id, mapping_revision_id, lifecycle_status, financial_access_status, "
            "commercial_access_status, last_authoritative_read_at, projection_valid_until, "
            "reconciliation_fencing_token) VALUES ("
            ":subscription_id, 'account-a', :customer_id, :user_id, 'product-a', :purchase_id, "
            ":mapping_id, 'active', 'allowed', 'eligible', now(), now() + interval '1 hour', 0)"
        ),
        {
            "subscription_id": SUBSCRIPTION_ID,
            "customer_id": CUSTOMER_ID,
            "user_id": USER_ID,
            "purchase_id": PURCHASE_ID,
            "mapping_id": MAPPING_ID,
        },
    )


def _assert_integrity_error(engine: Engine, statement: str, parameters: dict[str, object] | None = None) -> None:
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text(statement), parameters or {})


def _assert_database_error(engine: Engine, statement: str, parameters: dict[str, object] | None = None) -> None:
    with pytest.raises(DatabaseError), engine.begin() as connection:
        connection.execute(text(statement), parameters or {})


def test_customer_slot_and_purchase_identity_constraints(migrated_database: Engine) -> None:
    with migrated_database.begin() as connection:
        _seed_purchase_graph(connection)
        _insert_purchase(connection)

    _assert_integrity_error(
        migrated_database,
        "INSERT INTO external_billing_customers (customer_id, external_billing_account_id, user_id, "
        "billing_customer_key, binding_state) VALUES "
        "(gen_random_uuid(), 'account-a', :user_id, 'another-key', 'unbound')",
        {"user_id": USER_ID},
    )
    _assert_integrity_error(
        migrated_database,
        "INSERT INTO external_billing_customers (customer_id, external_billing_account_id, user_id, "
        "billing_customer_key, binding_state) VALUES "
        "(gen_random_uuid(), 'account-b', :user_id, 'customer-key-a', 'unbound')",
        {"user_id": SECOND_USER_ID},
    )
    _assert_integrity_error(
        migrated_database,
        "INSERT INTO purchase_intents (purchase_intent_id, user_id, external_billing_account_id, "
        "customer_id, product_id, billing_offer_id, mapping_revision_id, accepted_commercial_fingerprint, "
        "client_idempotency_key, state, accepted_snapshot_schema_version, accepted_snapshot, "
        "legal_acceptance_event_id) VALUES (gen_random_uuid(), :user_id, 'account-a', :customer_id, "
        "'product-a', 'offer-a', :mapping_id, 'fingerprint-a', 'idempotency-a', 'created', "
        "'snapshot-v1', '{}'::jsonb, :legal_event_id)",
        {
            "user_id": USER_ID,
            "customer_id": CUSTOMER_ID,
            "mapping_id": MAPPING_ID,
            "legal_event_id": LEGAL_EVENT_ID,
        },
    )


def test_purchase_provenance_rejects_mismatched_customer_mapping_and_legal_evidence(
    migrated_database: Engine,
) -> None:
    with migrated_database.begin() as connection:
        _seed_purchase_graph(connection)

    base = (
        "INSERT INTO purchase_intents (purchase_intent_id, user_id, external_billing_account_id, "
        "customer_id, product_id, billing_offer_id, mapping_revision_id, accepted_commercial_fingerprint, "
        "client_idempotency_key, state, accepted_snapshot_schema_version, accepted_snapshot, "
        "legal_acceptance_event_id) VALUES (gen_random_uuid(), :user_id, :account_id, :customer_id, "
        "'product-a', :offer_id, :mapping_id, :fingerprint, :key, 'created', 'snapshot-v1', '{}'::jsonb, "
        ":legal_event_id)"
    )
    common = {
        "user_id": USER_ID,
        "account_id": "account-a",
        "customer_id": CUSTOMER_ID,
        "offer_id": "offer-a",
        "mapping_id": MAPPING_ID,
        "fingerprint": "fingerprint-a",
        "legal_event_id": LEGAL_EVENT_ID,
    }
    _assert_integrity_error(
        migrated_database,
        base,
        {**common, "account_id": "account-b", "key": "bad-customer"},
    )
    _assert_integrity_error(
        migrated_database,
        base,
        {**common, "offer_id": "offer-b", "key": "bad-mapping"},
    )
    _assert_integrity_error(
        migrated_database,
        base,
        {**common, "fingerprint": "fingerprint-b", "key": "bad-legal"},
    )


@pytest.mark.parametrize(
    "values",
    (
        {
            "kind": "customer",
            "purchase_id": PURCHASE_ID,
            "unknown_since": None,
            "deadline": None,
            "hint_version": None,
            "hint_document": None,
        },
        {
            "kind": "agreement",
            "purchase_id": None,
            "unknown_since": None,
            "deadline": None,
            "hint_version": None,
            "hint_document": None,
        },
        {
            "kind": "subscription",
            "purchase_id": PURCHASE_ID,
            "unknown_since": "2026-09-24T00:00:00Z",
            "deadline": "2026-09-24T01:00:00Z",
            "hint_version": None,
            "hint_document": None,
        },
        {
            "kind": "subscription",
            "purchase_id": PURCHASE_ID,
            "unknown_since": None,
            "deadline": None,
            "hint_version": "hint-v1",
            "hint_document": None,
        },
    ),
)
def test_external_create_operation_structural_constraints(
    migrated_database: Engine,
    values: dict[str, object],
) -> None:
    with migrated_database.begin() as connection:
        _seed_purchase_graph(connection)
        _insert_purchase(connection)

    _assert_integrity_error(
        migrated_database,
        "INSERT INTO external_create_operations (create_operation_id, operation_kind, customer_id, "
        "purchase_intent_id, request_correlation_key, operation_state, unknown_since, "
        "unknown_recovery_deadline_at, recovery_hint_schema_version, recovery_hint_document) VALUES ("
        "gen_random_uuid(), :kind, :customer_id, :purchase_id, 'correlation-a', 'pending', "
        ":unknown_since, :deadline, :hint_version, CAST(:hint_document AS jsonb))",
        {**values, "customer_id": CUSTOMER_ID},
    )


def test_access_subscription_observation_and_allowance_constraints(migrated_database: Engine) -> None:
    observation_id = uuid.UUID("80000000-0000-4000-8000-000000000001")
    with migrated_database.begin() as connection:
        _seed_subscription_graph(connection)
        connection.execute(
            text(
                "INSERT INTO external_subscriptions ("
                "subscription_id, external_billing_account_id, customer_id, user_id, product_id, "
                "lifecycle_status, financial_access_status, commercial_access_status, "
                "last_authoritative_read_at, projection_valid_until, reconciliation_fencing_token) VALUES ("
                ":subscription_id, 'account-a', :customer_id, :user_id, 'product-a', 'active', 'allowed', "
                "'eligible', now(), now() + interval '1 hour', 0)"
            ),
            {
                "subscription_id": SECOND_SUBSCRIPTION_ID,
                "customer_id": CUSTOMER_ID,
                "user_id": USER_ID,
            },
        )
        connection.execute(
            text(
                "INSERT INTO billing_state_observations ("
                "observation_id, observation_kind, external_billing_account_id, user_id, product_id, "
                "subscription_id, observed_at, evidence_schema_version, evidence_document, "
                "completeness_classification, result_classification) VALUES ("
                ":id, 'authoritative_subscription_read', 'account-a', :user_id, 'product-a', "
                ":subscription_id, now(), 'evidence-v1', '{}'::jsonb, 'complete', 'allowed')"
            ),
            {"id": observation_id, "user_id": USER_ID, "subscription_id": SUBSCRIPTION_ID},
        )

    _assert_integrity_error(
        migrated_database,
        "UPDATE billing_product_access_scopes SET primary_subscription_id = :subscription_id, "
        "product_id = 'product-b' WHERE access_scope_id = :scope_id",
        {"subscription_id": SUBSCRIPTION_ID, "scope_id": SCOPE_ID},
    )
    _assert_integrity_error(
        migrated_database,
        "INSERT INTO billing_state_observations (observation_id, observation_kind, "
        "external_billing_account_id, user_id, product_id, access_scope_id, observed_at, "
        "evidence_schema_version, evidence_document, completeness_classification, result_classification) "
        "VALUES (gen_random_uuid(), 'target_product_discovery', 'account-a', :user_id, 'product-b', "
        ":scope_id, now(), 'evidence-v1', '{}'::jsonb, 'complete', 'allowed')",
        {"user_id": USER_ID, "scope_id": SCOPE_ID},
    )
    _assert_integrity_error(
        migrated_database,
        "UPDATE external_subscriptions SET latest_observation_id = :observation_id "
        "WHERE subscription_id = :subscription_id",
        {"observation_id": observation_id, "subscription_id": SECOND_SUBSCRIPTION_ID},
    )
    subscription_insert = (
        "INSERT INTO external_subscriptions (subscription_id, external_billing_account_id, customer_id, "
        "user_id, product_id, purchase_intent_id, mapping_revision_id, lifecycle_status, "
        "financial_access_status, commercial_access_status, last_authoritative_read_at, "
        "projection_valid_until, reconciliation_fencing_token) VALUES (gen_random_uuid(), :account_id, "
        ":customer_id, :user_id, :product_id, :purchase_id, :mapping_id, 'active', 'allowed', "
        "'eligible', now(), now() + interval '1 hour', 0)"
    )
    _assert_integrity_error(
        migrated_database,
        subscription_insert,
        {
            "account_id": "account-b",
            "customer_id": CUSTOMER_ID,
            "user_id": USER_ID,
            "product_id": "product-a",
            "purchase_id": None,
            "mapping_id": None,
        },
    )
    _assert_integrity_error(
        migrated_database,
        subscription_insert,
        {
            "account_id": "account-a",
            "customer_id": CUSTOMER_ID,
            "user_id": USER_ID,
            "product_id": "product-b",
            "purchase_id": PURCHASE_ID,
            "mapping_id": MAPPING_ID,
        },
    )
    _assert_integrity_error(
        migrated_database,
        "INSERT INTO purchased_allowances (allowance_id, subscription_id, source_component_id, "
        "product_id, metric_key, quantity, period_start, period_end) VALUES (gen_random_uuid(), "
        ":subscription_id, 'component-a', 'product-b', 'metric-a', 1, now(), now() + interval '1 day')",
        {"subscription_id": SUBSCRIPTION_ID},
    )


@pytest.mark.parametrize(
    "statement",
    (
        "INSERT INTO billing_state_observations (observation_id, observation_kind, "
        "external_billing_account_id, observed_at, evidence_schema_version, evidence_document, "
        "completeness_classification, result_classification) VALUES (gen_random_uuid(), "
        "'authoritative_subscription_read', 'account-a', now(), 'v1', '{}'::jsonb, 'complete', 'allowed')",
        "INSERT INTO billing_state_observations (observation_id, observation_kind, "
        "external_billing_account_id, user_id, product_id, access_scope_id, subscription_id, "
        "purchase_intent_id, observed_at, evidence_schema_version, evidence_document, "
        "completeness_classification, result_classification) VALUES (gen_random_uuid(), "
        "'deterministic_access_boundary', 'account-a', :user_id, 'product-a', :scope_id, "
        ":subscription_id, :purchase_id, now(), 'v1', '{}'::jsonb, 'complete', 'allowed')",
        "INSERT INTO billing_state_observations (observation_id, observation_kind, "
        "external_billing_account_id, user_id, product_id, access_scope_id, subscription_id, "
        "observed_at, evidence_schema_version, evidence_document, completeness_classification, "
        "result_classification) VALUES (gen_random_uuid(), 'deterministic_access_boundary', "
        "'account-a', :user_id, 'product-a', :scope_id, :subscription_id, now(), 'v1', '{}'::jsonb, "
        "'complete', 'allowed')",
    ),
)
def test_observation_row_shape_and_provenance_constraints(
    migrated_database: Engine,
    statement: str,
) -> None:
    with migrated_database.begin() as connection:
        _seed_subscription_graph(connection)

    _assert_integrity_error(
        migrated_database,
        statement,
        {
            "user_id": USER_ID,
            "scope_id": SCOPE_ID,
            "subscription_id": SUBSCRIPTION_ID,
            "purchase_id": PURCHASE_ID,
        },
    )


@pytest.mark.parametrize(
    ("statement", "parameters"),
    (
        (
            "INSERT INTO purchased_allowances (allowance_id, subscription_id, source_component_id, "
            "product_id, metric_key, quantity, period_start, period_end) VALUES (gen_random_uuid(), "
            ":subscription_id, 'component-a', 'product-a', 'metric-a', -1, now(), now() + interval '1 day')",
            {},
        ),
        (
            "INSERT INTO purchased_allowances (allowance_id, subscription_id, source_component_id, "
            "product_id, metric_key, quantity, provider_cycle_start, period_start, period_end) VALUES ("
            "gen_random_uuid(), :subscription_id, 'component-a', 'product-a', 'metric-a', 1, now(), "
            "now(), now() + interval '1 day')",
            {},
        ),
        (
            "INSERT INTO purchased_allowances (allowance_id, subscription_id, source_component_id, "
            "product_id, metric_key, quantity, period_start, period_end) VALUES (gen_random_uuid(), "
            ":subscription_id, 'component-a', 'product-a', 'metric-a', 1, now(), now())",
            {},
        ),
        (
            "INSERT INTO external_subscriptions (subscription_id, external_billing_account_id, customer_id, "
            "user_id, product_id, lifecycle_status, financial_access_status, commercial_access_status, "
            "last_authoritative_read_at, projection_valid_until, reconciliation_fencing_token, "
            "reconciliation_lease_owner) VALUES (gen_random_uuid(), 'account-a', :customer_id, :user_id, "
            "'product-a', 'active', 'allowed', 'eligible', now(), now(), 0, 'worker-a')",
            {},
        ),
        (
            "INSERT INTO billing_work_items (work_item_id, work_kind, scope_kind, scope_reference, "
            "payload_schema_version, payload_document, priority, next_attempt_at, attempt_count, work_state, "
            "lease_expires_at) VALUES (gen_random_uuid(), 'refresh', 'user', 'user-a', 'payload-v1', "
            "'{}'::jsonb, 0, now(), 0, 'pending', now())",
            {},
        ),
    ),
)
def test_allowance_subscription_and_work_item_structural_checks(
    migrated_database: Engine,
    statement: str,
    parameters: dict[str, object],
) -> None:
    with migrated_database.begin() as connection:
        _seed_subscription_graph(connection)

    _assert_integrity_error(
        migrated_database,
        statement,
        {
            **parameters,
            "subscription_id": SUBSCRIPTION_ID,
            "customer_id": CUSTOMER_ID,
            "user_id": USER_ID,
        },
    )


@pytest.mark.parametrize(
    ("statement", "parameters"),
    (
        (
            "INSERT INTO paid_access_states (paid_access_state_id, tenant_id, region, user_id, "
            "access_revision, effective_state_schema_version, effective_state_document, committed_at) "
            "VALUES (gen_random_uuid(), 'other', 'ru', :user_id, 1, 'state-v1', '{}'::jsonb, now())",
            {},
        ),
        (
            "INSERT INTO access_invalidation_outbox (outbox_id, tenant_id, region, user_id, "
            "pending_revision, delivered_revision, attempt_count, next_attempt_at) VALUES "
            "(gen_random_uuid(), 'anytoolai', 'ru', :user_id, 0, 0, 0, now())",
            {},
        ),
        (
            "INSERT INTO access_invalidation_outbox (outbox_id, tenant_id, region, user_id, "
            "pending_revision, delivered_revision, attempt_count, next_attempt_at) VALUES "
            "(gen_random_uuid(), 'anytoolai', 'ru', :user_id, 1, 2, 0, now())",
            {},
        ),
    ),
)
def test_paid_access_and_outbox_scope_and_revision_checks(
    migrated_database: Engine,
    statement: str,
    parameters: dict[str, object],
) -> None:
    with migrated_database.begin() as connection:
        _insert_user(connection, USER_ID, "access@example.com")

    _assert_integrity_error(migrated_database, statement, {**parameters, "user_id": USER_ID})


def test_step3_legal_immutability_and_append_only_guards(migrated_database: Engine) -> None:
    event_id = uuid.UUID("40000000-0000-4000-8000-000000000010")
    acceptance_id = uuid.UUID("41000000-0000-4000-8000-000000000010")
    document_id = uuid.UUID("55555555-5555-4555-8555-555555555503")
    with migrated_database.begin() as connection:
        _insert_user(connection, USER_ID, "legal@example.com")
        connection.execute(
            text(
                "INSERT INTO legal_acceptance_events (id, tenant_id, region, user_id, ip, user_agent) "
                "VALUES (:id, 'anytoolai', 'ru', :user_id, '192.0.2.1', 'test-agent')"
            ),
            {"id": event_id, "user_id": USER_ID},
        )
        connection.execute(
            text(
                "INSERT INTO document_acceptances (id, legal_acceptance_event_id, tenant_id, region, "
                "user_id, document_version_id, acceptance_kind, acceptance_text_hash) VALUES ("
                ":id, :event_id, 'anytoolai', 'ru', :user_id, :document_id, "
                "'terms_acceptance', 'acceptance-hash')"
            ),
            {
                "id": acceptance_id,
                "event_id": event_id,
                "user_id": USER_ID,
                "document_id": document_id,
            },
        )
        connection.execute(
            text("UPDATE legal_acceptance_events SET ip = NULL, user_agent = NULL WHERE id = :id"),
            {"id": event_id},
        )
        connection.execute(
            text("UPDATE document_versions SET is_active = false WHERE id = :id"),
            {"id": document_id},
        )

    _assert_database_error(
        migrated_database,
        "UPDATE legal_acceptance_events SET ip = '192.0.2.2' WHERE id = :id",
        {"id": event_id},
    )
    _assert_database_error(
        migrated_database,
        "UPDATE legal_acceptance_events SET accepted_at = now() + interval '1 second' WHERE id = :id",
        {"id": event_id},
    )
    _assert_database_error(
        migrated_database,
        "DELETE FROM legal_acceptance_events WHERE id = :id",
        {"id": event_id},
    )
    _assert_database_error(
        migrated_database,
        "UPDATE document_acceptances SET acceptance_text_hash = 'changed' WHERE id = :id",
        {"id": acceptance_id},
    )
    _assert_database_error(
        migrated_database,
        "DELETE FROM document_acceptances WHERE id = :id",
        {"id": acceptance_id},
    )
    _assert_database_error(
        migrated_database,
        "UPDATE document_versions SET title = 'changed' WHERE id = :id",
        {"id": document_id},
    )
    _assert_database_error(
        migrated_database,
        "DELETE FROM document_versions WHERE id = :id",
        {"id": document_id},
    )


def test_target_identity_and_historical_evidence_immutability_guards(migrated_database: Engine) -> None:
    observation_id = uuid.UUID("80000000-0000-4000-8000-000000000010")
    allowance_id = uuid.UUID("90000000-0000-4000-8000-000000000010")
    with migrated_database.begin() as connection:
        _seed_subscription_graph(connection)
        connection.execute(
            text(
                "INSERT INTO billing_state_observations (observation_id, observation_kind, "
                "external_billing_account_id, user_id, product_id, subscription_id, observed_at, "
                "evidence_schema_version, evidence_document, completeness_classification, "
                "result_classification) VALUES (:id, 'authoritative_subscription_read', 'account-a', "
                ":user_id, 'product-a', :subscription_id, now(), 'evidence-v1', '{}'::jsonb, "
                "'complete', 'allowed')"
            ),
            {"id": observation_id, "user_id": USER_ID, "subscription_id": SUBSCRIPTION_ID},
        )
        connection.execute(
            text(
                "INSERT INTO purchased_allowances (allowance_id, subscription_id, source_component_id, "
                "product_id, metric_key, quantity, period_start, period_end) VALUES (:id, "
                ":subscription_id, 'component-a', 'product-a', 'metric-a', 10, now(), "
                "now() + interval '1 day')"
            ),
            {"id": allowance_id, "subscription_id": SUBSCRIPTION_ID},
        )
        connection.execute(
            text(
                "UPDATE external_billing_customers SET provider_customer_id = 'provider-a', "
                "binding_state = 'bound', binding_updated_at = now() WHERE customer_id = :id"
            ),
            {"id": CUSTOMER_ID},
        )
        connection.execute(
            text(
                "UPDATE purchase_intents SET state = 'preparing', state_updated_at = now() "
                "WHERE purchase_intent_id = :id"
            ),
            {"id": PURCHASE_ID},
        )
        connection.execute(
            text(
                "UPDATE billing_state_observations SET resulting_access_revision = 1 "
                "WHERE observation_id = :id"
            ),
            {"id": observation_id},
        )

    rejected_statements = (
        (
            "UPDATE external_billing_customers SET billing_customer_key = 'changed' WHERE customer_id = :id",
            {"id": CUSTOMER_ID},
        ),
        ("DELETE FROM external_billing_customers WHERE customer_id = :id", {"id": CUSTOMER_ID}),
        (
            "UPDATE commercial_mapping_revisions SET catalog_digest = 'changed' "
            "WHERE mapping_revision_id = :id",
            {"id": MAPPING_ID},
        ),
        ("DELETE FROM commercial_mapping_revisions WHERE mapping_revision_id = :id", {"id": MAPPING_ID}),
        (
            "UPDATE purchase_intents SET accepted_snapshot = '{\"changed\": true}'::jsonb "
            "WHERE purchase_intent_id = :id",
            {"id": PURCHASE_ID},
        ),
        ("DELETE FROM purchase_intents WHERE purchase_intent_id = :id", {"id": PURCHASE_ID}),
        (
            "UPDATE billing_state_observations SET evidence_document = '{\"changed\": true}'::jsonb "
            "WHERE observation_id = :id",
            {"id": observation_id},
        ),
        (
            "UPDATE billing_state_observations SET resulting_access_revision = 2 WHERE observation_id = :id",
            {"id": observation_id},
        ),
        ("DELETE FROM billing_state_observations WHERE observation_id = :id", {"id": observation_id}),
        (
            "UPDATE purchased_allowances SET quantity = 11 WHERE allowance_id = :id",
            {"id": allowance_id},
        ),
        ("DELETE FROM purchased_allowances WHERE allowance_id = :id", {"id": allowance_id}),
    )
    for statement, parameters in rejected_statements:
        _assert_database_error(migrated_database, statement, parameters)


def _concurrent_insert_outcomes(
    engine: Engine,
    statement: str,
    parameter_sets: tuple[dict[str, object], dict[str, object]],
) -> list[str]:
    barrier = Barrier(2)

    def insert_one(parameters: dict[str, object]) -> str:
        with engine.connect() as connection:
            transaction = connection.begin()
            barrier.wait(timeout=10)
            try:
                connection.execute(text(statement), parameters)
                transaction.commit()
                return "committed"
            except IntegrityError:
                transaction.rollback()
                return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(insert_one, parameters) for parameters in parameter_sets]
        return [future.result(timeout=15) for future in futures]


def test_step4_unique_identities_hold_under_concurrent_inserts(migrated_database: Engine) -> None:
    third_user_id = uuid.UUID("10000000-0000-4000-8000-000000000003")
    with migrated_database.begin() as connection:
        _seed_purchase_graph(connection)
        _insert_user(connection, third_user_id, "third@example.com")

    customer_insert = (
        "INSERT INTO external_billing_customers (customer_id, external_billing_account_id, user_id, "
        "billing_customer_key, binding_state) VALUES (:id, 'account-c', :user_id, :key, 'unbound')"
    )
    outcomes = _concurrent_insert_outcomes(
        migrated_database,
        customer_insert,
        (
            {"id": uuid.uuid4(), "user_id": SECOND_USER_ID, "key": "slot-key-1"},
            {"id": uuid.uuid4(), "user_id": SECOND_USER_ID, "key": "slot-key-2"},
        ),
    )
    assert sorted(outcomes) == ["committed", "rejected"]

    outcomes = _concurrent_insert_outcomes(
        migrated_database,
        customer_insert.replace("'account-c'", ":account_id"),
        (
            {
                "id": uuid.uuid4(),
                "account_id": "account-d",
                "user_id": SECOND_USER_ID,
                "key": "global-key",
            },
            {
                "id": uuid.uuid4(),
                "account_id": "account-e",
                "user_id": third_user_id,
                "key": "global-key",
            },
        ),
    )
    assert sorted(outcomes) == ["committed", "rejected"]

    outcomes = _concurrent_insert_outcomes(
        migrated_database,
        "INSERT INTO billing_product_access_scopes (access_scope_id, user_id, product_id) "
        "VALUES (:id, :user_id, 'product-concurrent')",
        (
            {"id": uuid.uuid4(), "user_id": USER_ID},
            {"id": uuid.uuid4(), "user_id": USER_ID},
        ),
    )
    assert sorted(outcomes) == ["committed", "rejected"]

    outcomes = _concurrent_insert_outcomes(
        migrated_database,
        "INSERT INTO external_create_operations (create_operation_id, operation_kind, customer_id, "
        "request_correlation_key, operation_state) VALUES (:id, 'customer', :customer_id, :key, 'pending')",
        (
            {"id": uuid.uuid4(), "customer_id": CUSTOMER_ID, "key": "correlation-1"},
            {"id": uuid.uuid4(), "customer_id": CUSTOMER_ID, "key": "correlation-2"},
        ),
    )
    assert sorted(outcomes) == ["committed", "rejected"]

    purchase_insert = (
        "INSERT INTO purchase_intents (purchase_intent_id, user_id, external_billing_account_id, "
        "customer_id, product_id, billing_offer_id, mapping_revision_id, accepted_commercial_fingerprint, "
        "client_idempotency_key, state, accepted_snapshot_schema_version, accepted_snapshot, "
        "legal_acceptance_event_id) VALUES (:id, :user_id, 'account-a', :customer_id, 'product-a', "
        "'offer-a', :mapping_id, 'fingerprint-a', 'concurrent-idempotency', 'created', 'snapshot-v1', "
        "'{}'::jsonb, :legal_event_id)"
    )
    common = {
        "user_id": USER_ID,
        "customer_id": CUSTOMER_ID,
        "mapping_id": MAPPING_ID,
        "legal_event_id": LEGAL_EVENT_ID,
    }
    outcomes = _concurrent_insert_outcomes(
        migrated_database,
        purchase_insert,
        ({**common, "id": uuid.uuid4()}, {**common, "id": uuid.uuid4()}),
    )
    assert sorted(outcomes) == ["committed", "rejected"]
