# Generated Database Schema

Generated from SQLAlchemy metadata. Do not edit directly.

## `access_invalidation_outbox`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `outbox_id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no | FK |
| `region` | `TEXT` | no | FK |
| `user_id` | `CHAR(32)` | no | FK |
| `pending_revision` | `BIGINT` | no |  |
| `delivered_revision` | `BIGINT` | no |  |
| `attempt_count` | `INTEGER` | no |  |
| `next_attempt_at` | `DATETIME` | no |  |
| `last_error_classification` | `TEXT` | yes |  |
| `created_at` | `DATETIME` | no |  |
| `updated_at` | `DATETIME` | no |  |

Indexes and constraints:

- `ck_access_invalidation_outbox_pending_revision_positive`
- `ck_access_invalidation_outbox_revision_order`
- `fk_access_invalidation_outbox_user_scope`
- `uq_access_invalidation_outbox_tenant_region_user`
- `ix_access_invalidation_outbox_next_attempt_at`

## `auth_sessions`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no | FK |
| `region` | `TEXT` | no | FK |
| `user_id` | `CHAR(32)` | no | FK |
| `token_hash` | `TEXT` | no |  |
| `created_at` | `DATETIME` | no |  |
| `expires_at` | `DATETIME` | no |  |
| `last_seen_at` | `DATETIME` | no |  |
| `revoked_at` | `DATETIME` | yes |  |
| `ip` | `VARCHAR(45)` | yes |  |
| `user_agent` | `TEXT` | yes |  |

Indexes and constraints:

- `fk_auth_sessions_user_scope`
- `ix_auth_sessions_region`
- `ix_auth_sessions_tenant_id`
- `ix_auth_sessions_token_hash`
- `ix_auth_sessions_user_id`

## `billing_product_access_scopes`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `access_scope_id` | `CHAR(32)` | no | PK |
| `user_id` | `CHAR(32)` | no | FK |
| `product_id` | `TEXT` | no | FK |
| `primary_subscription_id` | `CHAR(32)` | yes | FK |
| `updated_at` | `DATETIME` | no |  |

Indexes and constraints:

- `fk_billing_product_access_scopes_primary_subscription`
- `uq_billing_product_access_scopes_id_user_product`
- `uq_billing_product_access_scopes_user_product`
- `ix_billing_product_access_scopes_primary_subscription`

## `billing_state_observations`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `observation_id` | `CHAR(32)` | no | PK |
| `observation_kind` | `TEXT` | no |  |
| `external_billing_account_id` | `TEXT` | no | FK |
| `user_id` | `CHAR(32)` | yes | FK |
| `product_id` | `TEXT` | yes | FK |
| `access_scope_id` | `CHAR(32)` | yes | FK |
| `subscription_id` | `CHAR(32)` | yes | FK |
| `purchase_intent_id` | `CHAR(32)` | yes | FK |
| `work_item_id` | `CHAR(32)` | yes | FK |
| `basis_observation_id` | `CHAR(32)` | yes | FK |
| `observed_at` | `DATETIME` | no |  |
| `effective_at` | `DATETIME` | yes |  |
| `evidence_schema_version` | `TEXT` | no |  |
| `evidence_document` | `JSON` | no |  |
| `completeness_classification` | `TEXT` | no |  |
| `result_classification` | `TEXT` | no |  |
| `resulting_access_revision` | `BIGINT` | yes |  |
| `created_at` | `DATETIME` | no |  |

Indexes and constraints:

- `ck_billing_state_observations_evidence_schema_nonempty`
- `ck_billing_state_observations_kind`
- `ck_billing_state_observations_kind_shape`
- `ck_billing_state_observations_provenance_exclusive`
- `ck_billing_state_observations_subject_shape`
- `fk_billing_state_observations_access_scope`
- `fk_billing_state_observations_basis_scope`
- `fk_billing_state_observations_purchase_scope`
- `fk_billing_state_observations_subscription_scope`
- `uq_billing_state_observations_id_scope`
- `uq_billing_state_observations_id_subscription`
- `ix_billing_state_observations_account_kind_time`
- `ix_billing_state_observations_basis`
- `ix_billing_state_observations_completeness`
- `ix_billing_state_observations_effective_at`
- `ix_billing_state_observations_kind_time`
- `ix_billing_state_observations_purchase_time`
- `ix_billing_state_observations_result`
- `ix_billing_state_observations_scope_revision`
- `ix_billing_state_observations_scope_time`
- `ix_billing_state_observations_subscription_time`
- `ix_billing_state_observations_user_product_time`
- `ix_billing_state_observations_work_item`

## `billing_work_items`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `work_item_id` | `CHAR(32)` | no | PK |
| `work_kind` | `TEXT` | no |  |
| `scope_kind` | `TEXT` | no |  |
| `scope_reference` | `TEXT` | no |  |
| `coalescing_key` | `TEXT` | yes |  |
| `payload_schema_version` | `TEXT` | no |  |
| `payload_document` | `JSON` | no |  |
| `priority` | `INTEGER` | no |  |
| `next_attempt_at` | `DATETIME` | no |  |
| `attempt_count` | `INTEGER` | no |  |
| `work_state` | `TEXT` | no |  |
| `lease_owner` | `TEXT` | yes |  |
| `lease_expires_at` | `DATETIME` | yes |  |
| `last_error_classification` | `TEXT` | yes |  |
| `created_at` | `DATETIME` | no |  |
| `updated_at` | `DATETIME` | no |  |

Indexes and constraints:

- `ck_billing_work_items_lease_pair`
- `ck_billing_work_items_payload_schema_nonempty`
- `ix_billing_work_items_claim_scan`
- `ix_billing_work_items_coalescing_key`
- `ix_billing_work_items_kind_state`
- `ix_billing_work_items_kind_state_due`
- `ix_billing_work_items_lease_expiry`
- `ix_billing_work_items_priority_retry`
- `ix_billing_work_items_scope`

## `capability_manifest_projections`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `projection_id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no |  |
| `region` | `TEXT` | no |  |
| `schema_version` | `INTEGER` | no |  |
| `manifest_version` | `TEXT` | no |  |
| `generated_at` | `DATETIME` | no |  |
| `last_complete_sync_at` | `DATETIME` | no |  |
| `manifest_document` | `JSON` | no |  |

Indexes and constraints:

- `uq_capability_manifest_projections_scope`
- `ix_capability_manifest_projections_last_sync`
- `ix_capability_manifest_projections_manifest_version`

## `commercial_mapping_revisions`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `mapping_revision_id` | `CHAR(32)` | no | PK |
| `external_billing_account_id` | `TEXT` | no |  |
| `billing_offer_id` | `TEXT` | no |  |
| `revision_number` | `BIGINT` | no |  |
| `manifest_version` | `TEXT` | no |  |
| `catalog_version` | `TEXT` | yes |  |
| `catalog_digest` | `TEXT` | no |  |
| `mapping_schema_version` | `TEXT` | no |  |
| `mapping_document` | `JSON` | no |  |
| `published_at` | `DATETIME` | no |  |
| `published_by_principal` | `TEXT` | no |  |

Indexes and constraints:

- `ck_commercial_mapping_revisions_revision_positive`
- `ck_commercial_mapping_revisions_schema_nonempty`
- `uq_commercial_mapping_revisions_account_offer_revision`
- `uq_commercial_mapping_revisions_id_account`
- `uq_commercial_mapping_revisions_id_account_offer`
- `ix_commercial_mapping_revisions_manifest`
- `ix_commercial_mapping_revisions_principal`
- `ix_commercial_mapping_revisions_publication`

## `country_region_rules`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `country_code` | `VARCHAR(2)` | no |  |
| `region` | `TEXT` | no | FK |
| `market_enabled` | `BOOLEAN` | no |  |
| `strict_mismatch` | `BOOLEAN` | no |  |
| `default_document_set` | `TEXT` | no |  |

Indexes and constraints:

- `ix_country_region_rules_country_code`
- `ix_country_region_rules_region`

## `document_acceptances`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `legal_acceptance_event_id` | `CHAR(32)` | no | FK |
| `tenant_id` | `TEXT` | no | FK |
| `region` | `TEXT` | no | FK |
| `user_id` | `CHAR(32)` | no | FK |
| `document_version_id` | `CHAR(32)` | no | FK |
| `acceptance_kind` | `TEXT` | no |  |
| `acceptance_text_hash` | `TEXT` | no |  |
| `created_at` | `DATETIME` | no |  |

Indexes and constraints:

- `fk_document_acceptances_document_scope`
- `fk_document_acceptances_event_scope`
- `uq_document_acceptances_event_document`
- `ix_document_acceptances_document_version_id`
- `ix_document_acceptances_legal_acceptance_event_id`
- `ix_document_acceptances_region`
- `ix_document_acceptances_tenant_id`
- `ix_document_acceptances_user_id`

## `document_versions`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no | FK |
| `region` | `TEXT` | no | FK |
| `legal_entity_id` | `CHAR(32)` | no | FK |
| `doc_type` | `TEXT` | no |  |
| `version` | `TEXT` | no |  |
| `title` | `TEXT` | no |  |
| `url_path` | `TEXT` | no |  |
| `content_hash` | `TEXT` | no |  |
| `published_at` | `DATETIME` | no |  |
| `effective_from` | `DATETIME` | no |  |
| `is_active` | `BOOLEAN` | no |  |
| `requires_acceptance` | `BOOLEAN` | no |  |
| `created_at` | `DATETIME` | no |  |
| `updated_at` | `DATETIME` | no |  |

Indexes and constraints:

- `fk_document_versions_legal_entity_scope`
- `uq_document_versions_id_tenant_region`
- `uq_document_versions_tenant_region_doc_type_version`
- `ix_document_versions_doc_type`
- `ix_document_versions_is_active`
- `ix_document_versions_legal_entity_id`
- `ix_document_versions_region`
- `ix_document_versions_region_is_active`
- `ix_document_versions_tenant_id`
- `uq_document_versions_active_doc`

## `external_billing_catalog_projections`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `projection_id` | `CHAR(32)` | no | PK |
| `external_billing_account_id` | `TEXT` | no |  |
| `schema_version` | `TEXT` | no |  |
| `catalog_version` | `TEXT` | yes |  |
| `catalog_digest` | `TEXT` | no |  |
| `last_complete_sync_at` | `DATETIME` | no |  |
| `catalog_document` | `JSON` | no |  |

Indexes and constraints:

- `uq_external_billing_catalog_projections_account`
- `ix_external_billing_catalog_projections_catalog_digest`
- `ix_external_billing_catalog_projections_catalog_version`
- `ix_external_billing_catalog_projections_last_sync`

## `external_billing_customers`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `customer_id` | `CHAR(32)` | no | PK |
| `external_billing_account_id` | `TEXT` | no |  |
| `user_id` | `CHAR(32)` | no | FK |
| `billing_customer_key` | `TEXT` | no |  |
| `provider_customer_id` | `TEXT` | yes |  |
| `binding_state` | `TEXT` | no |  |
| `binding_updated_at` | `DATETIME` | no |  |
| `created_at` | `DATETIME` | no |  |

Indexes and constraints:

- `ck_external_billing_customers_binding_state`
- `ck_external_billing_customers_key_nonempty`
- `uq_external_billing_customers_account_user`
- `uq_external_billing_customers_billing_customer_key`
- `uq_external_billing_customers_id_account_user`
- `ix_external_billing_customers_binding_state`
- `ix_external_billing_customers_provider_customer_id`

## `external_billing_webhook_deliveries`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `delivery_id` | `CHAR(32)` | no | PK |
| `external_billing_account_id` | `TEXT` | no |  |
| `provider_event_id` | `TEXT` | yes |  |
| `payload_hash` | `TEXT` | no |  |
| `correlation_schema_version` | `TEXT` | no |  |
| `correlation_document` | `JSON` | no |  |
| `evidence_schema_version` | `TEXT` | no |  |
| `evidence_document` | `JSON` | no |  |
| `processing_state` | `TEXT` | no |  |
| `received_at` | `DATETIME` | no |  |
| `processing_started_at` | `DATETIME` | yes |  |
| `processed_at` | `DATETIME` | yes |  |
| `last_error_classification` | `TEXT` | yes |  |

Indexes and constraints:

- `ck_external_billing_webhook_deliveries_corr_schema_nonempty`
- `ck_external_billing_webhook_deliveries_evidence_schema_nonempty`
- `ck_external_billing_webhook_deliveries_hash_nonempty`
- `ix_external_billing_webhook_deliveries_account_received`
- `ix_external_billing_webhook_deliveries_payload_hash`
- `ix_external_billing_webhook_deliveries_processing_received`
- `ix_external_billing_webhook_deliveries_provider_event`
- `ix_external_billing_webhook_deliveries_received_at`

## `external_create_operations`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `create_operation_id` | `CHAR(32)` | no | PK |
| `operation_kind` | `TEXT` | no |  |
| `customer_id` | `CHAR(32)` | no | FK |
| `purchase_intent_id` | `CHAR(32)` | yes | FK |
| `request_correlation_key` | `TEXT` | no |  |
| `operation_state` | `TEXT` | no |  |
| `unknown_since` | `DATETIME` | yes |  |
| `unknown_recovery_deadline_at` | `DATETIME` | yes |  |
| `recovery_hint_schema_version` | `TEXT` | yes |  |
| `recovery_hint_document` | `JSON` | yes |  |
| `bound_external_object_id` | `TEXT` | yes |  |
| `created_at` | `DATETIME` | no |  |
| `updated_at` | `DATETIME` | no |  |
| `resolved_at` | `DATETIME` | yes |  |

Indexes and constraints:

- `ck_external_create_operations_correlation_nonempty`
- `ck_external_create_operations_kind`
- `ck_external_create_operations_purchase_requirement`
- `ck_external_create_operations_recovery_hint_pair`
- `ck_external_create_operations_unknown_deadline`
- `ck_external_create_operations_unknown_pair`
- `fk_external_create_operations_purchase_customer`
- `ix_external_create_operations_bound_object`
- `ix_external_create_operations_correlation`
- `ix_external_create_operations_customer_state`
- `ix_external_create_operations_purchase`
- `ix_external_create_operations_recovery_scan`
- `ix_external_create_operations_unknown_deadline`
- `uq_external_create_operations_unresolved_customer`

## `external_subscriptions`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `subscription_id` | `CHAR(32)` | no | PK |
| `external_billing_account_id` | `TEXT` | no | FK |
| `customer_id` | `CHAR(32)` | no | FK |
| `user_id` | `CHAR(32)` | no | FK |
| `product_id` | `TEXT` | no | FK |
| `purchase_intent_id` | `CHAR(32)` | yes | FK |
| `mapping_revision_id` | `CHAR(32)` | yes | FK |
| `external_subscription_id` | `TEXT` | yes |  |
| `external_agreement_id` | `TEXT` | yes |  |
| `lifecycle_status` | `TEXT` | no |  |
| `financial_access_status` | `TEXT` | no |  |
| `commercial_access_status` | `TEXT` | no |  |
| `last_authoritative_read_at` | `DATETIME` | no |  |
| `projection_valid_until` | `DATETIME` | no |  |
| `reconciliation_lease_owner` | `TEXT` | yes |  |
| `reconciliation_lease_expires_at` | `DATETIME` | yes |  |
| `reconciliation_fencing_token` | `BIGINT` | no |  |
| `latest_observation_id` | `CHAR(32)` | yes | FK |
| `created_at` | `DATETIME` | no |  |
| `updated_at` | `DATETIME` | no |  |

Indexes and constraints:

- `ck_external_subscriptions_commercial_access_status`
- `ck_external_subscriptions_fencing_token_nonnegative`
- `ck_external_subscriptions_financial_access_status`
- `ck_external_subscriptions_lifecycle_status`
- `ck_external_subscriptions_purchase_mapping`
- `ck_external_subscriptions_reconciliation_lease_pair`
- `fk_external_subscriptions_customer_scope`
- `fk_external_subscriptions_latest_observation`
- `fk_external_subscriptions_mapping_scope`
- `fk_external_subscriptions_purchase_provenance`
- `uq_external_subscriptions_id_account_user_product`
- `uq_external_subscriptions_id_product`
- `uq_external_subscriptions_id_user_product`
- `ix_external_subscriptions_account_customer`
- `ix_external_subscriptions_agreement_id`
- `ix_external_subscriptions_commercial_status`
- `ix_external_subscriptions_customer_product_status`
- `ix_external_subscriptions_external_id`
- `ix_external_subscriptions_financial_status`
- `ix_external_subscriptions_last_read`
- `ix_external_subscriptions_latest_observation`
- `ix_external_subscriptions_lease_expiry`
- `ix_external_subscriptions_lifecycle_status`
- `ix_external_subscriptions_mapping_provenance`
- `ix_external_subscriptions_purchase_provenance`
- `ix_external_subscriptions_reconciliation_claim`
- `ix_external_subscriptions_user_product_status`
- `ix_external_subscriptions_valid_until`
- `uq_external_subscriptions_purchase_intent`

## `legal_acceptance_events`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no | FK |
| `region` | `TEXT` | no | FK |
| `user_id` | `CHAR(32)` | no | FK |
| `external_billing_account_id` | `TEXT` | yes |  |
| `billing_offer_id` | `TEXT` | yes |  |
| `accepted_commercial_fingerprint` | `TEXT` | yes |  |
| `accepted_at` | `DATETIME` | no |  |
| `ip` | `VARCHAR(45)` | yes |  |
| `user_agent` | `TEXT` | yes |  |
| `created_at` | `DATETIME` | no |  |

Indexes and constraints:

- `ck_legal_acceptance_events_commercial_triplet`
- `fk_legal_acceptance_events_user_scope`
- `uq_legal_acceptance_events_purchase_binding`
- `uq_legal_acceptance_events_scope`
- `ix_legal_acceptance_events_accepted_at`
- `ix_legal_acceptance_events_region`
- `ix_legal_acceptance_events_tenant_id`
- `ix_legal_acceptance_events_user_id`

## `legal_entities`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no |  |
| `region` | `TEXT` | no | FK |
| `name` | `TEXT` | no |  |
| `entity_type` | `TEXT` | no |  |
| `tax_id` | `TEXT` | yes |  |
| `registration_id` | `TEXT` | yes |  |
| `legal_address` | `TEXT` | no |  |
| `support_email` | `TEXT` | no |  |
| `status` | `TEXT` | no |  |
| `created_at` | `DATETIME` | no |  |
| `updated_at` | `DATETIME` | no |  |

Indexes and constraints:

- `uq_legal_entities_id_tenant_region`
- `ix_legal_entities_region`
- `ix_legal_entities_status`
- `ix_legal_entities_tenant_id`
- `ix_legal_entities_tenant_region_status`

## `magic_link_tokens`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no | FK |
| `region` | `TEXT` | no | FK |
| `user_id` | `CHAR(32)` | yes | FK |
| `email_normalized` | `VARCHAR(320)` | no |  |
| `token_hash` | `TEXT` | no |  |
| `purpose` | `TEXT` | no |  |
| `created_at` | `DATETIME` | no |  |
| `expires_at` | `DATETIME` | no |  |
| `used_at` | `DATETIME` | yes |  |
| `ip` | `VARCHAR(45)` | yes |  |
| `user_agent` | `TEXT` | yes |  |

Indexes and constraints:

- `fk_magic_link_tokens_user_scope`
- `ix_magic_link_tokens_email_normalized`
- `ix_magic_link_tokens_region`
- `ix_magic_link_tokens_tenant_id`
- `ix_magic_link_tokens_token_hash`
- `ix_magic_link_tokens_user_id`

## `manual_review_cases`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `review_case_id` | `CHAR(32)` | no | PK |
| `reason_code` | `TEXT` | no |  |
| `scope_kind` | `TEXT` | no |  |
| `scope_reference` | `TEXT` | no |  |
| `evidence_schema_version` | `TEXT` | no |  |
| `evidence_document` | `JSON` | no |  |
| `case_state` | `TEXT` | no |  |
| `created_at` | `DATETIME` | no |  |
| `resolved_at` | `DATETIME` | yes |  |
| `resolved_by_principal` | `TEXT` | yes |  |
| `resolution_schema_version` | `TEXT` | yes |  |
| `resolution_document` | `JSON` | yes |  |

Indexes and constraints:

- `ck_manual_review_cases_evidence_schema_nonempty`
- `ix_manual_review_cases_reason_state`
- `ix_manual_review_cases_resolved_by`
- `ix_manual_review_cases_scope`
- `ix_manual_review_cases_state`
- `ix_manual_review_cases_state_created`

## `paid_access_states`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `paid_access_state_id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no | FK |
| `region` | `TEXT` | no | FK |
| `user_id` | `CHAR(32)` | no | FK |
| `access_revision` | `BIGINT` | no |  |
| `effective_state_schema_version` | `TEXT` | no |  |
| `effective_state_document` | `JSON` | no |  |
| `committed_at` | `DATETIME` | no |  |

Indexes and constraints:

- `fk_paid_access_states_user_scope`
- `uq_paid_access_states_tenant_region_user`

## `password_reset_rate_limits`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `rate_limit_key` | `TEXT` | no | PK |
| `count` | `INTEGER` | no |  |
| `window_start` | `DATETIME` | no |  |
| `expires_at` | `DATETIME` | no |  |
| `created_at` | `DATETIME` | no |  |
| `updated_at` | `DATETIME` | no |  |

Indexes and constraints:

- `ix_password_reset_rate_limits_expires_at`

## `purchase_intents`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `purchase_intent_id` | `CHAR(32)` | no | PK |
| `user_id` | `CHAR(32)` | no | FK |
| `external_billing_account_id` | `TEXT` | no | FK |
| `customer_id` | `CHAR(32)` | no | FK |
| `product_id` | `TEXT` | no |  |
| `billing_offer_id` | `TEXT` | no | FK |
| `mapping_revision_id` | `CHAR(32)` | no | FK |
| `accepted_commercial_fingerprint` | `TEXT` | no | FK |
| `client_idempotency_key` | `TEXT` | no |  |
| `state` | `TEXT` | no |  |
| `accepted_snapshot_schema_version` | `TEXT` | no |  |
| `accepted_snapshot` | `JSON` | no |  |
| `legal_acceptance_event_id` | `CHAR(32)` | no | FK |
| `created_at` | `DATETIME` | no |  |
| `state_updated_at` | `DATETIME` | no |  |
| `resolved_at` | `DATETIME` | yes |  |

Indexes and constraints:

- `ck_purchase_intents_fingerprint_nonempty`
- `ck_purchase_intents_idempotency_nonempty`
- `ck_purchase_intents_snapshot_schema_nonempty`
- `ck_purchase_intents_state`
- `fk_purchase_intents_customer_scope`
- `fk_purchase_intents_legal_evidence`
- `fk_purchase_intents_mapping_scope`
- `uq_purchase_intents_client_idempotency`
- `uq_purchase_intents_full_scope`
- `uq_purchase_intents_id_account_user_product`
- `uq_purchase_intents_id_customer`
- `ix_purchase_intents_account_offer`
- `ix_purchase_intents_commercial_fingerprint`
- `ix_purchase_intents_customer_purchase`
- `ix_purchase_intents_mapping_revision`
- `ix_purchase_intents_state`
- `ix_purchase_intents_state_updated_at`
- `ix_purchase_intents_user_product`

## `purchased_allowances`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `allowance_id` | `CHAR(32)` | no | PK |
| `subscription_id` | `CHAR(32)` | no | FK |
| `source_component_id` | `TEXT` | no |  |
| `product_id` | `TEXT` | no | FK |
| `metric_key` | `TEXT` | no |  |
| `quantity` | `BIGINT` | no |  |
| `provider_cycle_key` | `TEXT` | yes |  |
| `provider_cycle_start` | `DATETIME` | yes |  |
| `provider_cycle_end` | `DATETIME` | yes |  |
| `period_start` | `DATETIME` | no |  |
| `period_end` | `DATETIME` | no |  |
| `created_at` | `DATETIME` | no |  |

Indexes and constraints:

- `ck_purchased_allowances_period_order`
- `ck_purchased_allowances_provider_cycle_pair`
- `ck_purchased_allowances_quantity_nonnegative`
- `fk_purchased_allowances_subscription_product`
- `ix_purchased_allowances_product_metric`
- `ix_purchased_allowances_provider_cycle_key`
- `ix_purchased_allowances_subscription_component_cycle`
- `ix_purchased_allowances_subscription_cycle`

## `regions`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `code` | `TEXT` | no | PK |
| `name` | `TEXT` | no |  |
| `residency_zone` | `TEXT` | no |  |
| `default_currency` | `VARCHAR(3)` | no |  |
| `default_locale` | `TEXT` | no |  |
| `status` | `TEXT` | no |  |

Indexes and constraints:


## `users`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no |  |
| `region` | `TEXT` | no | FK |
| `email` | `VARCHAR(320)` | no |  |
| `email_normalized` | `VARCHAR(320)` | no |  |
| `email_verified_at` | `DATETIME` | yes |  |
| `status` | `TEXT` | no |  |
| `last_login_at` | `DATETIME` | yes |  |
| `password_hash` | `TEXT` | yes |  |
| `metadata` | `JSON` | no |  |
| `created_at` | `DATETIME` | no |  |
| `updated_at` | `DATETIME` | no |  |

Indexes and constraints:

- `uq_users_id_tenant_region`
- `uq_users_tenant_region_email_normalized`
- `ix_users_email_normalized`
- `ix_users_region`
- `ix_users_status`
- `ix_users_tenant_id`
