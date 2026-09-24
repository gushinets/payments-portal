from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import IntegrityError

from apps.api.tests.support.postgres import alembic_test_config, reset_public_schema


BASELINE_REVISION = "20260924_0001"

SURVIVOR_TABLES = {
    "regions",
    "country_region_rules",
    "users",
    "auth_sessions",
    "magic_link_tokens",
    "password_reset_rate_limits",
    "legal_entities",
    "document_versions",
    "legal_acceptance_events",
    "document_acceptances",
}

TARGET_TABLES = {
    "capability_manifest_projections",
    "external_billing_catalog_projections",
    "commercial_mapping_revisions",
    "external_billing_customers",
    "purchase_intents",
    "external_create_operations",
    "billing_product_access_scopes",
    "external_subscriptions",
    "billing_state_observations",
    "purchased_allowances",
    "external_billing_webhook_deliveries",
    "billing_work_items",
    "manual_review_cases",
    "paid_access_states",
    "access_invalidation_outbox",
}

APPLICATION_TABLES = SURVIVOR_TABLES | TARGET_TABLES

LEGACY_TABLES = {
    "products",
    "bundles",
    "bundle_products",
    "plans",
    "plan_price_components",
    "plan_limits",
    "orders",
    "payments",
    "refunds",
    "payment_provider_accounts",
    "payment_webhook_events",
    "subscriptions",
    "entitlements",
    "subscription_events",
    "product_access_states",
    "external_billing_accounts",
}

EXPECTED_COLUMNS = {
    "regions": {"code", "name", "residency_zone", "default_currency", "default_locale", "status"},
    "country_region_rules": {
        "id",
        "country_code",
        "region",
        "market_enabled",
        "strict_mismatch",
        "default_document_set",
    },
    "users": {
        "id",
        "tenant_id",
        "region",
        "email",
        "email_normalized",
        "email_verified_at",
        "status",
        "last_login_at",
        "password_hash",
        "metadata",
        "created_at",
        "updated_at",
    },
    "auth_sessions": {
        "id",
        "tenant_id",
        "region",
        "user_id",
        "token_hash",
        "created_at",
        "expires_at",
        "last_seen_at",
        "revoked_at",
        "ip",
        "user_agent",
    },
    "magic_link_tokens": {
        "id",
        "tenant_id",
        "region",
        "user_id",
        "email_normalized",
        "token_hash",
        "purpose",
        "created_at",
        "expires_at",
        "used_at",
        "ip",
        "user_agent",
    },
    "password_reset_rate_limits": {"rate_limit_key", "count", "window_start", "expires_at", "created_at", "updated_at"},
    "legal_entities": {
        "id",
        "tenant_id",
        "region",
        "name",
        "entity_type",
        "tax_id",
        "registration_id",
        "legal_address",
        "support_email",
        "status",
        "created_at",
        "updated_at",
    },
    "document_versions": {
        "id",
        "tenant_id",
        "region",
        "legal_entity_id",
        "doc_type",
        "version",
        "title",
        "url_path",
        "content_hash",
        "published_at",
        "effective_from",
        "is_active",
        "requires_acceptance",
        "created_at",
        "updated_at",
    },
    "legal_acceptance_events": {
        "id",
        "tenant_id",
        "region",
        "user_id",
        "external_billing_account_id",
        "billing_offer_id",
        "accepted_commercial_fingerprint",
        "accepted_at",
        "ip",
        "user_agent",
        "created_at",
    },
    "document_acceptances": {
        "id",
        "legal_acceptance_event_id",
        "tenant_id",
        "region",
        "user_id",
        "document_version_id",
        "acceptance_kind",
        "acceptance_text_hash",
        "created_at",
    },
    "capability_manifest_projections": {
        "projection_id",
        "tenant_id",
        "region",
        "schema_version",
        "manifest_version",
        "generated_at",
        "last_complete_sync_at",
        "manifest_document",
    },
    "external_billing_catalog_projections": {
        "projection_id",
        "external_billing_account_id",
        "schema_version",
        "catalog_version",
        "catalog_digest",
        "last_complete_sync_at",
        "catalog_document",
    },
    "commercial_mapping_revisions": {
        "mapping_revision_id",
        "external_billing_account_id",
        "billing_offer_id",
        "revision_number",
        "manifest_version",
        "catalog_version",
        "catalog_digest",
        "mapping_schema_version",
        "mapping_document",
        "published_at",
        "published_by_principal",
    },
    "external_billing_customers": {
        "customer_id",
        "external_billing_account_id",
        "user_id",
        "billing_customer_key",
        "provider_customer_id",
        "binding_state",
        "binding_updated_at",
        "created_at",
    },
    "purchase_intents": {
        "purchase_intent_id",
        "user_id",
        "external_billing_account_id",
        "customer_id",
        "product_id",
        "billing_offer_id",
        "mapping_revision_id",
        "accepted_commercial_fingerprint",
        "client_idempotency_key",
        "state",
        "accepted_snapshot_schema_version",
        "accepted_snapshot",
        "legal_acceptance_event_id",
        "created_at",
        "state_updated_at",
        "resolved_at",
    },
    "external_create_operations": {
        "create_operation_id",
        "operation_kind",
        "customer_id",
        "purchase_intent_id",
        "request_correlation_key",
        "operation_state",
        "unknown_since",
        "unknown_recovery_deadline_at",
        "recovery_hint_schema_version",
        "recovery_hint_document",
        "bound_external_object_id",
        "created_at",
        "updated_at",
        "resolved_at",
    },
    "billing_product_access_scopes": {
        "access_scope_id",
        "user_id",
        "product_id",
        "primary_subscription_id",
        "updated_at",
    },
    "external_subscriptions": {
        "subscription_id",
        "external_billing_account_id",
        "customer_id",
        "user_id",
        "product_id",
        "purchase_intent_id",
        "mapping_revision_id",
        "external_subscription_id",
        "external_agreement_id",
        "lifecycle_status",
        "financial_access_status",
        "commercial_access_status",
        "last_authoritative_read_at",
        "projection_valid_until",
        "reconciliation_lease_owner",
        "reconciliation_lease_expires_at",
        "reconciliation_fencing_token",
        "latest_observation_id",
        "created_at",
        "updated_at",
    },
    "billing_state_observations": {
        "observation_id",
        "observation_kind",
        "external_billing_account_id",
        "user_id",
        "product_id",
        "access_scope_id",
        "subscription_id",
        "purchase_intent_id",
        "work_item_id",
        "basis_observation_id",
        "observed_at",
        "effective_at",
        "evidence_schema_version",
        "evidence_document",
        "completeness_classification",
        "result_classification",
        "resulting_access_revision",
        "created_at",
    },
    "purchased_allowances": {
        "allowance_id",
        "subscription_id",
        "source_component_id",
        "product_id",
        "metric_key",
        "quantity",
        "provider_cycle_key",
        "provider_cycle_start",
        "provider_cycle_end",
        "period_start",
        "period_end",
        "created_at",
    },
    "external_billing_webhook_deliveries": {
        "delivery_id",
        "external_billing_account_id",
        "provider_event_id",
        "payload_hash",
        "correlation_schema_version",
        "correlation_document",
        "evidence_schema_version",
        "evidence_document",
        "processing_state",
        "received_at",
        "processing_started_at",
        "processed_at",
        "last_error_classification",
    },
    "billing_work_items": {
        "work_item_id",
        "work_kind",
        "scope_kind",
        "scope_reference",
        "coalescing_key",
        "payload_schema_version",
        "payload_document",
        "priority",
        "next_attempt_at",
        "attempt_count",
        "work_state",
        "lease_owner",
        "lease_expires_at",
        "last_error_classification",
        "created_at",
        "updated_at",
    },
    "manual_review_cases": {
        "review_case_id",
        "reason_code",
        "scope_kind",
        "scope_reference",
        "evidence_schema_version",
        "evidence_document",
        "case_state",
        "created_at",
        "resolved_at",
        "resolved_by_principal",
        "resolution_schema_version",
        "resolution_document",
    },
    "paid_access_states": {
        "paid_access_state_id",
        "tenant_id",
        "region",
        "user_id",
        "access_revision",
        "effective_state_schema_version",
        "effective_state_document",
        "committed_at",
    },
    "access_invalidation_outbox": {
        "outbox_id",
        "tenant_id",
        "region",
        "user_id",
        "pending_revision",
        "delivered_revision",
        "attempt_count",
        "next_attempt_at",
        "last_error_classification",
        "created_at",
        "updated_at",
    },
}

EXPECTED_CHECKS = {
    "legal_acceptance_events": {"ck_legal_acceptance_events_commercial_triplet"},
    "capability_manifest_projections": set(),
    "external_billing_catalog_projections": set(),
    "commercial_mapping_revisions": {
        "ck_commercial_mapping_revisions_revision_positive",
        "ck_commercial_mapping_revisions_schema_nonempty",
    },
    "external_billing_customers": {
        "ck_external_billing_customers_key_nonempty",
        "ck_external_billing_customers_binding_state",
    },
    "purchase_intents": {
        "ck_purchase_intents_fingerprint_nonempty",
        "ck_purchase_intents_idempotency_nonempty",
        "ck_purchase_intents_snapshot_schema_nonempty",
        "ck_purchase_intents_state",
    },
    "external_create_operations": {
        "ck_external_create_operations_purchase_requirement",
        "ck_external_create_operations_kind",
        "ck_external_create_operations_correlation_nonempty",
        "ck_external_create_operations_unknown_pair",
        "ck_external_create_operations_unknown_deadline",
        "ck_external_create_operations_recovery_hint_pair",
    },
    "billing_product_access_scopes": set(),
    "external_subscriptions": {
        "ck_external_subscriptions_purchase_mapping",
        "ck_external_subscriptions_lifecycle_status",
        "ck_external_subscriptions_financial_access_status",
        "ck_external_subscriptions_commercial_access_status",
        "ck_external_subscriptions_reconciliation_lease_pair",
        "ck_external_subscriptions_fencing_token_nonnegative",
    },
    "billing_state_observations": {
        "ck_billing_state_observations_provenance_exclusive",
        "ck_billing_state_observations_subject_shape",
        "ck_billing_state_observations_kind",
        "ck_billing_state_observations_kind_shape",
        "ck_billing_state_observations_evidence_schema_nonempty",
    },
    "purchased_allowances": {
        "ck_purchased_allowances_quantity_nonnegative",
        "ck_purchased_allowances_provider_cycle_pair",
        "ck_purchased_allowances_period_order",
    },
    "external_billing_webhook_deliveries": {
        "ck_external_billing_webhook_deliveries_hash_nonempty",
        "ck_external_billing_webhook_deliveries_corr_schema_nonempty",
        "ck_external_billing_webhook_deliveries_evidence_schema_nonempty",
    },
    "billing_work_items": {"ck_billing_work_items_payload_schema_nonempty", "ck_billing_work_items_lease_pair"},
    "manual_review_cases": {"ck_manual_review_cases_evidence_schema_nonempty"},
    "paid_access_states": set(),
    "access_invalidation_outbox": {
        "ck_access_invalidation_outbox_pending_revision_positive",
        "ck_access_invalidation_outbox_revision_order",
    },
}

EXPECTED_UNIQUE_CONSTRAINTS = {
    "country_region_rules": {"uq_country_region_rules_country_code"},
    "users": {"uq_users_tenant_region_email_normalized", "uq_users_id_tenant_region"},
    "auth_sessions": {"uq_auth_sessions_token_hash"},
    "magic_link_tokens": {"uq_magic_link_tokens_token_hash"},
    "legal_entities": {"uq_legal_entities_id_tenant_region"},
    "document_versions": {
        "uq_document_versions_tenant_region_doc_type_version",
        "uq_document_versions_id_tenant_region",
    },
    "legal_acceptance_events": {
        "uq_legal_acceptance_events_purchase_binding",
        "uq_legal_acceptance_events_scope",
    },
    "document_acceptances": {"uq_document_acceptances_event_document"},
    "capability_manifest_projections": {"uq_capability_manifest_projections_scope"},
    "external_billing_catalog_projections": {"uq_external_billing_catalog_projections_account"},
    "commercial_mapping_revisions": {
        "uq_commercial_mapping_revisions_id_account",
        "uq_commercial_mapping_revisions_id_account_offer",
        "uq_commercial_mapping_revisions_account_offer_revision",
    },
    "external_billing_customers": {
        "uq_external_billing_customers_id_account_user",
        "uq_external_billing_customers_account_user",
        "uq_external_billing_customers_billing_customer_key",
    },
    "purchase_intents": {
        "uq_purchase_intents_client_idempotency",
        "uq_purchase_intents_id_customer",
        "uq_purchase_intents_id_account_user_product",
        "uq_purchase_intents_full_scope",
    },
    "billing_product_access_scopes": {
        "uq_billing_product_access_scopes_id_user_product",
        "uq_billing_product_access_scopes_user_product",
    },
    "external_subscriptions": {
        "uq_external_subscriptions_id_product",
        "uq_external_subscriptions_id_user_product",
        "uq_external_subscriptions_id_account_user_product",
    },
    "billing_state_observations": {
        "uq_billing_state_observations_id_scope",
        "uq_billing_state_observations_id_subscription",
    },
    "paid_access_states": {"uq_paid_access_states_tenant_region_user"},
    "access_invalidation_outbox": {"uq_access_invalidation_outbox_tenant_region_user"},
}

EXPECTED_INDEXES = {
    "country_region_rules": {"ix_country_region_rules_country_code", "ix_country_region_rules_region"},
    "users": {"ix_users_tenant_id", "ix_users_region", "ix_users_email_normalized", "ix_users_status"},
    "auth_sessions": {
        "ix_auth_sessions_tenant_id",
        "ix_auth_sessions_region",
        "ix_auth_sessions_user_id",
        "ix_auth_sessions_token_hash",
    },
    "magic_link_tokens": {
        "ix_magic_link_tokens_tenant_id",
        "ix_magic_link_tokens_region",
        "ix_magic_link_tokens_user_id",
        "ix_magic_link_tokens_email_normalized",
        "ix_magic_link_tokens_token_hash",
    },
    "password_reset_rate_limits": {"ix_password_reset_rate_limits_expires_at"},
    "legal_entities": {
        "ix_legal_entities_tenant_id",
        "ix_legal_entities_region",
        "ix_legal_entities_status",
        "ix_legal_entities_tenant_region_status",
    },
    "document_versions": {
        "ix_document_versions_tenant_id",
        "ix_document_versions_region",
        "ix_document_versions_legal_entity_id",
        "ix_document_versions_doc_type",
        "ix_document_versions_is_active",
        "uq_document_versions_active_doc",
        "ix_document_versions_region_is_active",
    },
    "legal_acceptance_events": {
        "ix_legal_acceptance_events_tenant_id",
        "ix_legal_acceptance_events_region",
        "ix_legal_acceptance_events_user_id",
        "ix_legal_acceptance_events_accepted_at",
    },
    "document_acceptances": {
        "ix_document_acceptances_legal_acceptance_event_id",
        "ix_document_acceptances_tenant_id",
        "ix_document_acceptances_region",
        "ix_document_acceptances_user_id",
        "ix_document_acceptances_document_version_id",
    },
    "capability_manifest_projections": {
        "ix_capability_manifest_projections_manifest_version",
        "ix_capability_manifest_projections_last_sync",
    },
    "external_billing_catalog_projections": {
        "ix_external_billing_catalog_projections_catalog_version",
        "ix_external_billing_catalog_projections_catalog_digest",
        "ix_external_billing_catalog_projections_last_sync",
    },
    "commercial_mapping_revisions": {
        "ix_commercial_mapping_revisions_publication",
        "ix_commercial_mapping_revisions_manifest",
        "ix_commercial_mapping_revisions_principal",
    },
    "external_billing_customers": {
        "ix_external_billing_customers_provider_customer_id",
        "ix_external_billing_customers_binding_state",
    },
    "purchase_intents": {
        "ix_purchase_intents_user_product",
        "ix_purchase_intents_account_offer",
        "ix_purchase_intents_customer_purchase",
        "ix_purchase_intents_mapping_revision",
        "ix_purchase_intents_commercial_fingerprint",
        "ix_purchase_intents_state",
        "ix_purchase_intents_state_updated_at",
    },
    "external_create_operations": {
        "uq_external_create_operations_unresolved_customer",
        "ix_external_create_operations_customer_state",
        "ix_external_create_operations_purchase",
        "ix_external_create_operations_correlation",
        "ix_external_create_operations_unknown_deadline",
        "ix_external_create_operations_bound_object",
        "ix_external_create_operations_recovery_scan",
    },
    "billing_product_access_scopes": {"ix_billing_product_access_scopes_primary_subscription"},
    "external_subscriptions": {
        "uq_external_subscriptions_purchase_intent",
        "ix_external_subscriptions_account_customer",
        "ix_external_subscriptions_user_product_status",
        "ix_external_subscriptions_customer_product_status",
        "ix_external_subscriptions_purchase_provenance",
        "ix_external_subscriptions_mapping_provenance",
        "ix_external_subscriptions_external_id",
        "ix_external_subscriptions_agreement_id",
        "ix_external_subscriptions_lifecycle_status",
        "ix_external_subscriptions_financial_status",
        "ix_external_subscriptions_commercial_status",
        "ix_external_subscriptions_last_read",
        "ix_external_subscriptions_valid_until",
        "ix_external_subscriptions_lease_expiry",
        "ix_external_subscriptions_reconciliation_claim",
        "ix_external_subscriptions_latest_observation",
    },
    "billing_state_observations": {
        "ix_billing_state_observations_kind_time",
        "ix_billing_state_observations_account_kind_time",
        "ix_billing_state_observations_user_product_time",
        "ix_billing_state_observations_scope_time",
        "ix_billing_state_observations_subscription_time",
        "ix_billing_state_observations_purchase_time",
        "ix_billing_state_observations_work_item",
        "ix_billing_state_observations_basis",
        "ix_billing_state_observations_effective_at",
        "ix_billing_state_observations_completeness",
        "ix_billing_state_observations_result",
        "ix_billing_state_observations_scope_revision",
    },
    "purchased_allowances": {
        "ix_purchased_allowances_provider_cycle_key",
        "ix_purchased_allowances_subscription_cycle",
        "ix_purchased_allowances_subscription_component_cycle",
        "ix_purchased_allowances_product_metric",
    },
    "external_billing_webhook_deliveries": {
        "ix_external_billing_webhook_deliveries_account_received",
        "ix_external_billing_webhook_deliveries_processing_received",
        "ix_external_billing_webhook_deliveries_received_at",
        "ix_external_billing_webhook_deliveries_provider_event",
        "ix_external_billing_webhook_deliveries_payload_hash",
    },
    "billing_work_items": {
        "ix_billing_work_items_kind_state_due",
        "ix_billing_work_items_scope",
        "ix_billing_work_items_coalescing_key",
        "ix_billing_work_items_priority_retry",
        "ix_billing_work_items_lease_expiry",
        "ix_billing_work_items_claim_scan",
        "ix_billing_work_items_kind_state",
    },
    "manual_review_cases": {
        "ix_manual_review_cases_reason_state",
        "ix_manual_review_cases_scope",
        "ix_manual_review_cases_state",
        "ix_manual_review_cases_state_created",
        "ix_manual_review_cases_resolved_by",
    },
    "access_invalidation_outbox": {"ix_access_invalidation_outbox_next_attempt_at"},
}

ORM_ONLY_DEFAULT_COLUMNS = {
    ("regions", "status"),
    ("country_region_rules", "market_enabled"),
    ("country_region_rules", "strict_mismatch"),
    ("users", "status"),
    ("users", "metadata"),
    ("password_reset_rate_limits", "count"),
    ("legal_entities", "status"),
    ("document_versions", "is_active"),
    ("document_versions", "requires_acceptance"),
    ("external_billing_customers", "binding_state"),
    ("purchase_intents", "state"),
    ("external_subscriptions", "reconciliation_fencing_token"),
    ("billing_work_items", "priority"),
    ("billing_work_items", "attempt_count"),
    ("access_invalidation_outbox", "delivered_revision"),
    ("access_invalidation_outbox", "attempt_count"),
}

pytestmark = pytest.mark.postgres


def _public_table_names(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names(schema="public"))


def _expected_legal_documents() -> list[dict[str, str]]:
    manifest_path = Path(__file__).resolve().parents[3] / "apps/web/src/generated/legal-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return sorted(
        [
            {
                "id": document["id"],
                "doc_type": document["docType"],
                "version": document["version"],
                "content_hash": document["contentHash"],
            }
            for document in manifest["documents"]
        ],
        key=lambda document: document["id"],
    )


def test_clean_first_install_has_one_revision_and_exact_application_schema(
    postgres_engine: Engine,
    database_test_url: URL,
) -> None:
    reset_public_schema(postgres_engine)
    handlers = tuple(logging.getLogger().handlers)

    with alembic_test_config(database_test_url) as config:
        script = ScriptDirectory.from_config(config)
        assert script.get_heads() == [BASELINE_REVISION]
        assert script.get_bases() == [BASELINE_REVISION]
        assert [item.revision for item in script.walk_revisions()] == [BASELINE_REVISION]
        command.upgrade(config, "head")

    assert tuple(logging.getLogger().handlers) == handlers
    assert len(APPLICATION_TABLES) == 25
    assert _public_table_names(postgres_engine) == APPLICATION_TABLES | {"alembic_version"}
    assert LEGACY_TABLES.isdisjoint(_public_table_names(postgres_engine))
    with postgres_engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == BASELINE_REVISION

    inspector = inspect(postgres_engine)
    for table_name, expected_columns in EXPECTED_COLUMNS.items():
        assert {column["name"] for column in inspector.get_columns(table_name)} == expected_columns
    for table_name, expected_checks in EXPECTED_CHECKS.items():
        actual_checks = {constraint["name"] for constraint in inspector.get_check_constraints(table_name)}
        assert actual_checks == expected_checks
    for table_name, expected_constraints in EXPECTED_UNIQUE_CONSTRAINTS.items():
        actual_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints(table_name)}
        assert actual_constraints == expected_constraints
    for table_name, expected_indexes in EXPECTED_INDEXES.items():
        actual_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
        assert expected_indexes <= actual_indexes

    with postgres_engine.connect() as connection:
        partial_indexes = dict(
            connection.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' "
                    "AND indexname IN ('uq_document_versions_active_doc', "
                    "'uq_external_create_operations_unresolved_customer', "
                    "'uq_external_subscriptions_purchase_intent')"
                )
            ).all()
        )
    normalized_predicates = {
        name: " ".join(definition.upper().replace("(", " ").replace(")", " ").split())
        for name, definition in partial_indexes.items()
    }
    assert normalized_predicates["uq_document_versions_active_doc"].endswith("WHERE IS_ACTIVE = TRUE")
    assert normalized_predicates["uq_external_create_operations_unresolved_customer"].endswith(
        "WHERE OPERATION_KIND = 'CUSTOMER'::TEXT AND RESOLVED_AT IS NULL"
    )
    assert normalized_predicates["uq_external_subscriptions_purchase_intent"].endswith(
        "WHERE PURCHASE_INTENT_ID IS NOT NULL"
    )

    all_foreign_keys = {
        foreign_key["name"]: (
            table_name,
            tuple(foreign_key["constrained_columns"]),
            foreign_key["referred_table"],
            tuple(foreign_key["referred_columns"]),
        )
        for table_name in APPLICATION_TABLES
        for foreign_key in inspector.get_foreign_keys(table_name)
    }
    required_restrict_foreign_keys = {
        "fk_auth_sessions_user_scope",
        "fk_magic_link_tokens_user_scope",
        "fk_document_versions_legal_entity_scope",
        "fk_legal_acceptance_events_user_scope",
        "fk_document_acceptances_event_scope",
        "fk_document_acceptances_document_scope",
        "fk_purchase_intents_customer_scope",
        "fk_purchase_intents_mapping_scope",
        "fk_purchase_intents_legal_evidence",
        "fk_external_create_operations_purchase_customer",
        "fk_billing_product_access_scopes_primary_subscription",
        "fk_external_subscriptions_customer_scope",
        "fk_external_subscriptions_purchase_provenance",
        "fk_external_subscriptions_mapping_scope",
        "fk_external_subscriptions_latest_observation",
        "fk_billing_state_observations_access_scope",
        "fk_billing_state_observations_subscription_scope",
        "fk_billing_state_observations_purchase_scope",
        "fk_billing_state_observations_basis_scope",
        "fk_purchased_allowances_subscription_product",
        "fk_paid_access_states_user_scope",
        "fk_access_invalidation_outbox_user_scope",
    }
    assert required_restrict_foreign_keys <= all_foreign_keys.keys()
    foreign_key_ondelete = {
        foreign_key["name"]: foreign_key["options"].get("ondelete")
        for table_name in APPLICATION_TABLES
        for foreign_key in inspector.get_foreign_keys(table_name)
    }
    assert all(foreign_key_ondelete[name] == "RESTRICT" for name in required_restrict_foreign_keys)
    assert all_foreign_keys["fk_billing_product_access_scopes_primary_subscription"] == (
        "billing_product_access_scopes",
        ("primary_subscription_id", "user_id", "product_id"),
        "external_subscriptions",
        ("subscription_id", "user_id", "product_id"),
    )
    assert all_foreign_keys["fk_external_subscriptions_latest_observation"] == (
        "external_subscriptions",
        ("latest_observation_id", "subscription_id"),
        "billing_state_observations",
        ("observation_id", "subscription_id"),
    )

    json_columns = {
        ("users", "metadata"),
        ("capability_manifest_projections", "manifest_document"),
        ("external_billing_catalog_projections", "catalog_document"),
        ("commercial_mapping_revisions", "mapping_document"),
        ("purchase_intents", "accepted_snapshot"),
        ("external_create_operations", "recovery_hint_document"),
        ("billing_state_observations", "evidence_document"),
        ("external_billing_webhook_deliveries", "correlation_document"),
        ("external_billing_webhook_deliveries", "evidence_document"),
        ("billing_work_items", "payload_document"),
        ("manual_review_cases", "evidence_document"),
        ("manual_review_cases", "resolution_document"),
        ("paid_access_states", "effective_state_document"),
    }
    for table_name, column_name in json_columns:
        columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        assert isinstance(columns[column_name]["type"], JSONB)
    for table_name, column_name in ORM_ONLY_DEFAULT_COLUMNS:
        columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        assert columns[column_name]["default"] is None


def test_clean_first_install_bootstraps_supported_configured_scope_and_empty_targets(
    postgres_engine: Engine,
    database_test_url: URL,
) -> None:
    reset_public_schema(postgres_engine)
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "head")

    with postgres_engine.connect() as connection:
        assert connection.execute(text("SELECT code FROM regions ORDER BY code")).scalars().all() == ["ru"]
        assert connection.execute(
            text("SELECT country_code, region, default_document_set FROM country_region_rules")
        ).one() == ("RU", "ru", "ru_ip_v1")
        assert connection.execute(
            text("SELECT tenant_id, region, count(*) FROM legal_entities GROUP BY tenant_id, region")
        ).one() == ("anytoolai", "ru", 1)
        documents = [
            dict(row)
            for row in connection.execute(
                text("SELECT id::text, doc_type, version, content_hash FROM document_versions ORDER BY id")
            ).mappings()
        ]
        assert documents == _expected_legal_documents()
        for table_name in TARGET_TABLES:
            assert connection.execute(text(f'SELECT count(*) FROM "{table_name}"')).scalar_one() == 0


@pytest.mark.parametrize(
    ("instance_tenant_id", "instance_region"),
    [("other", "ru"), ("anytoolai", "eu")],
)
def test_clean_first_install_rejects_unsupported_configured_scope(
    postgres_engine: Engine,
    database_test_url: URL,
    instance_tenant_id: str,
    instance_region: str,
) -> None:
    reset_public_schema(postgres_engine)

    with alembic_test_config(
        database_test_url,
        instance_tenant_id=instance_tenant_id,
        instance_region=instance_region,
    ) as config:
        with pytest.raises(ValueError, match="current bootstrap supports only anytoolai/ru"):
            command.upgrade(config, "head")

    assert _public_table_names(postgres_engine) == set()


def test_survivor_scope_constraints_reject_cross_contour_references(migrated_database: Engine) -> None:
    with migrated_database.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, tenant_id, region, email, email_normalized, status, metadata) VALUES "
                "('10000000-0000-4000-8000-000000000001', 'anytoolai', 'ru', "
                "'scope@example.com', 'scope@example.com', 'active', '{}'::jsonb)"
            )
        )

    with pytest.raises(IntegrityError), migrated_database.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO auth_sessions "
                "(id, tenant_id, region, user_id, token_hash, expires_at) VALUES "
                "('10000000-0000-4000-8000-000000000002', 'other', 'ru', "
                "'10000000-0000-4000-8000-000000000001', 'scope-token', now() + interval '1 hour')"
            )
        )

    with pytest.raises(IntegrityError), migrated_database.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO legal_acceptance_events "
                "(id, tenant_id, region, user_id) VALUES "
                "('10000000-0000-4000-8000-000000000003', 'anytoolai', 'other', "
                "'10000000-0000-4000-8000-000000000001')"
            )
        )


def test_clean_first_install_downgrades_to_empty_public_schema(
    postgres_engine: Engine,
    database_test_url: URL,
) -> None:
    reset_public_schema(postgres_engine)
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "head")
        command.downgrade(config, "base")

    assert _public_table_names(postgres_engine) == {"alembic_version"}
    with postgres_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM alembic_version")).scalar_one() == 0
