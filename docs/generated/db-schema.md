# Generated Database Schema

Generated from SQLAlchemy metadata. Do not edit directly.

## `auth_sessions`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no |  |
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

- `ix_auth_sessions_region`
- `ix_auth_sessions_tenant_id`
- `ix_auth_sessions_token_hash`
- `ix_auth_sessions_user_id`

## `checkout_sessions`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no |  |
| `region` | `TEXT` | no | FK |
| `user_id` | `CHAR(32)` | no | FK |
| `entrypoint_session_id` | `CHAR(32)` | yes | FK |
| `plan_id` | `CHAR(32)` | yes |  |
| `status` | `TEXT` | no |  |
| `amount_minor` | `INTEGER` | no |  |
| `currency` | `VARCHAR(3)` | no |  |
| `expires_at` | `DATETIME` | no |  |
| `metadata` | `JSON` | no |  |
| `created_at` | `DATETIME` | no |  |
| `updated_at` | `DATETIME` | no |  |

Indexes and constraints:

- `ix_checkout_sessions_entrypoint_session_id`
- `ix_checkout_sessions_region`
- `ix_checkout_sessions_status_expires_at`
- `ix_checkout_sessions_tenant_id`
- `ix_checkout_sessions_user_id`
- `ix_checkout_sessions_user_id_created_at`

## `country_region_rules`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `country_code` | `VARCHAR(2)` | no |  |
| `region` | `TEXT` | no | FK |
| `market_enabled` | `BOOLEAN` | no |  |
| `allow_region_override` | `BOOLEAN` | no |  |
| `strict_mismatch` | `BOOLEAN` | no |  |
| `default_document_set` | `TEXT` | no |  |
| `default_payment_provider` | `TEXT` | no |  |

Indexes and constraints:

- `ix_country_region_rules_country_code`
- `ix_country_region_rules_region`

## `document_acceptances`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no |  |
| `region` | `TEXT` | no | FK |
| `user_id` | `CHAR(32)` | yes | FK |
| `guest_id` | `TEXT` | yes |  |
| `entrypoint_session_id` | `CHAR(32)` | yes |  |
| `document_version_id` | `CHAR(32)` | no | FK |
| `doc_type` | `TEXT` | no |  |
| `version` | `TEXT` | no |  |
| `acceptance_kind` | `TEXT` | no |  |
| `accepted_at` | `DATETIME` | no |  |
| `ip` | `VARCHAR(45)` | yes |  |
| `user_agent` | `TEXT` | yes |  |
| `acceptance_text_hash` | `TEXT` | no |  |
| `entrypoint_type` | `TEXT` | yes |  |
| `entrypoint_value` | `TEXT` | yes |  |
| `source_url` | `TEXT` | yes |  |
| `metadata` | `JSON` | no |  |
| `created_at` | `DATETIME` | no |  |

Indexes and constraints:

- `ix_document_acceptances_accepted_at`
- `ix_document_acceptances_doc_type`
- `ix_document_acceptances_document_version_id`
- `ix_document_acceptances_entrypoint_session_id`
- `ix_document_acceptances_guest_id`
- `ix_document_acceptances_region`
- `ix_document_acceptances_region_doc_version`
- `ix_document_acceptances_tenant_id`
- `ix_document_acceptances_user_id`
- `ix_document_acceptances_user_region_doc_accepted_at`

## `document_versions`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no |  |
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

- `uq_document_versions_tenant_region_doc_type_version`
- `ix_document_versions_doc_type`
- `ix_document_versions_is_active`
- `ix_document_versions_legal_entity_id`
- `ix_document_versions_region`
- `ix_document_versions_region_is_active`
- `ix_document_versions_tenant_id`
- `uq_document_versions_active_doc`

## `entrypoint_sessions`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no |  |
| `route_region` | `TEXT` | no |  |
| `resolved_region` | `TEXT` | no | FK |
| `ip_country` | `VARCHAR(2)` | yes |  |
| `declared_country` | `VARCHAR(2)` | yes |  |
| `browser_language` | `TEXT` | yes |  |
| `region_mismatch_status` | `TEXT` | no |  |
| `entrypoint_type` | `TEXT` | no |  |
| `entrypoint_value` | `TEXT` | no |  |
| `product_id` | `CHAR(32)` | yes |  |
| `bundle_id` | `CHAR(32)` | yes |  |
| `frontend_id` | `TEXT` | yes |  |
| `platform_guest_id` | `TEXT` | yes |  |
| `platform_user_id` | `TEXT` | yes |  |
| `scenario_session_id` | `TEXT` | yes |  |
| `artifact_id` | `TEXT` | yes |  |
| `user_id` | `CHAR(32)` | yes | FK |
| `source_url` | `TEXT` | yes |  |
| `acquisition_source` | `TEXT` | yes |  |
| `ip` | `VARCHAR(45)` | yes |  |
| `user_agent` | `TEXT` | yes |  |
| `metadata` | `JSON` | no |  |
| `created_at` | `DATETIME` | no |  |

Indexes and constraints:

- `ix_entrypoint_sessions_frontend_id_created_at`
- `ix_entrypoint_sessions_resolved_region_created_at`
- `ix_entrypoint_sessions_scenario_session_id`
- `ix_entrypoint_sessions_tenant_id`
- `ix_entrypoint_sessions_type_value`
- `ix_entrypoint_sessions_user_id`
- `ix_entrypoint_sessions_user_id_created_at`

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

- `ix_legal_entities_region`
- `ix_legal_entities_status`
- `ix_legal_entities_tenant_id`
- `ix_legal_entities_tenant_region_status`

## `magic_link_tokens`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no |  |
| `region` | `TEXT` | no | FK |
| `email_normalized` | `VARCHAR(320)` | no |  |
| `token_hash` | `TEXT` | no |  |
| `purpose` | `TEXT` | no |  |
| `entrypoint_session_id` | `CHAR(32)` | yes |  |
| `created_at` | `DATETIME` | no |  |
| `expires_at` | `DATETIME` | no |  |
| `used_at` | `DATETIME` | yes |  |
| `ip` | `VARCHAR(45)` | yes |  |
| `user_agent` | `TEXT` | yes |  |

Indexes and constraints:

- `ix_magic_link_tokens_email_normalized`
- `ix_magic_link_tokens_region`
- `ix_magic_link_tokens_tenant_id`
- `ix_magic_link_tokens_token_hash`

## `order_items`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `order_id` | `CHAR(32)` | no | FK |
| `item_type` | `TEXT` | no |  |
| `product_id` | `CHAR(32)` | yes |  |
| `bundle_id` | `CHAR(32)` | yes |  |
| `plan_id` | `CHAR(32)` | yes |  |
| `product_code_snapshot` | `TEXT` | yes |  |
| `plan_code_snapshot` | `TEXT` | yes |  |
| `title_snapshot` | `TEXT` | no |  |
| `quantity` | `INTEGER` | no |  |
| `list_amount_minor` | `INTEGER` | no |  |
| `discount_amount_minor` | `INTEGER` | no |  |
| `unit_amount_minor` | `INTEGER` | no |  |
| `amount_minor` | `INTEGER` | no |  |
| `currency` | `VARCHAR(3)` | no |  |
| `trial_days_snapshot` | `INTEGER` | no |  |
| `pricing_snapshot` | `JSON` | no |  |
| `metadata` | `JSON` | no |  |
| `created_at` | `DATETIME` | no |  |

Indexes and constraints:

- `ix_order_items_bundle_id`
- `ix_order_items_order_id`
- `ix_order_items_product_id`

## `orders`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no |  |
| `region` | `TEXT` | no | FK |
| `order_number` | `TEXT` | no |  |
| `user_id` | `CHAR(32)` | no | FK |
| `checkout_session_id` | `CHAR(32)` | yes | FK |
| `entrypoint_session_id` | `CHAR(32)` | yes | FK |
| `plan_id` | `CHAR(32)` | yes |  |
| `status` | `TEXT` | no |  |
| `amount_minor` | `INTEGER` | no |  |
| `currency` | `VARCHAR(3)` | no |  |
| `tax_amount_minor` | `INTEGER` | no |  |
| `discount_amount_minor` | `INTEGER` | no |  |
| `provider` | `TEXT` | no |  |
| `provider_account_id` | `CHAR(32)` | no | FK |
| `merchant_order_id` | `TEXT` | no |  |
| `provider_invoice_id` | `TEXT` | yes |  |
| `billing_country` | `VARCHAR(2)` | yes |  |
| `region_mismatch_status` | `TEXT` | no |  |
| `paid_at` | `DATETIME` | yes |  |
| `failed_at` | `DATETIME` | yes |  |
| `canceled_at` | `DATETIME` | yes |  |
| `expires_at` | `DATETIME` | yes |  |
| `metadata` | `JSON` | no |  |
| `created_at` | `DATETIME` | no |  |
| `updated_at` | `DATETIME` | no |  |

Indexes and constraints:

- `uq_orders_provider_account_merchant_order`
- `uq_orders_tenant_region_order_number`
- `ix_orders_checkout_session_id`
- `ix_orders_entrypoint_session_id`
- `ix_orders_provider_account_id`
- `ix_orders_provider_invoice_id`
- `ix_orders_region`
- `ix_orders_region_status_created_at`
- `ix_orders_status`
- `ix_orders_tenant_id`
- `ix_orders_user_id`
- `ix_orders_user_id_created_at`

## `payment_provider_accounts`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no |  |
| `region` | `TEXT` | no | FK |
| `legal_entity_id` | `CHAR(32)` | yes | FK |
| `provider` | `TEXT` | no |  |
| `public_identifier` | `TEXT` | yes |  |
| `default_currency` | `VARCHAR(3)` | no |  |
| `enabled` | `BOOLEAN` | no |  |
| `test_mode` | `BOOLEAN` | no |  |
| `config` | `JSON` | no |  |
| `created_at` | `DATETIME` | no |  |
| `updated_at` | `DATETIME` | no |  |

Indexes and constraints:

- `uq_pay_provider_accounts_tenant_region_provider_entity`
- `ix_payment_provider_accounts_legal_entity_id`
- `ix_payment_provider_accounts_provider`
- `ix_payment_provider_accounts_region`
- `ix_payment_provider_accounts_region_enabled`
- `ix_payment_provider_accounts_tenant_id`
- `uq_payment_provider_accounts_default`

## `payment_webhook_events`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no |  |
| `region` | `TEXT` | no | FK |
| `provider_account_id` | `CHAR(32)` | yes | FK |
| `provider` | `VARCHAR` | no |  |
| `endpoint` | `TEXT` | no |  |
| `event_type` | `TEXT` | yes |  |
| `provider_event_id` | `TEXT` | yes |  |
| `idempotency_key` | `TEXT` | yes |  |
| `payload_hash` | `TEXT` | no |  |
| `invoice_id` | `TEXT` | yes |  |
| `transaction_id` | `TEXT` | yes |  |
| `account_id` | `TEXT` | yes |  |
| `order_id` | `CHAR(32)` | yes | FK |
| `payment_id` | `CHAR(32)` | yes | FK |
| `amount_minor` | `INTEGER` | yes |  |
| `amount` | `NUMERIC(12, 2)` | yes |  |
| `currency` | `TEXT` | yes |  |
| `raw_payload` | `JSON` | no |  |
| `headers` | `JSON` | yes |  |
| `received_at` | `DATETIME` | no |  |
| `processed_at` | `DATETIME` | yes |  |
| `status` | `TEXT` | no |  |
| `error_code` | `TEXT` | yes |  |
| `error_message` | `TEXT` | yes |  |

Indexes and constraints:

- `ix_payment_webhook_events_idempotency_lookup`
- `ix_payment_webhook_events_order_id`
- `ix_payment_webhook_events_payment_id`
- `ix_payment_webhook_events_provider_account_id`
- `ix_payment_webhook_events_provider_endpoint_event_type`
- `ix_payment_webhook_events_provider_event_id`
- `ix_payment_webhook_events_region`
- `ix_payment_webhook_events_region_provider_received_at`
- `ix_payment_webhook_events_tenant_id`

## `payments`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no |  |
| `region` | `TEXT` | no | FK |
| `order_id` | `CHAR(32)` | no | FK |
| `provider_account_id` | `CHAR(32)` | no | FK |
| `provider` | `TEXT` | no |  |
| `provider_payment_id` | `TEXT` | yes |  |
| `provider_invoice_id` | `TEXT` | yes |  |
| `status` | `TEXT` | no |  |
| `amount_minor` | `INTEGER` | no |  |
| `currency` | `VARCHAR(3)` | no |  |
| `payment_method_type` | `TEXT` | yes |  |
| `authorized_at` | `DATETIME` | yes |  |
| `captured_at` | `DATETIME` | yes |  |
| `failed_at` | `DATETIME` | yes |  |
| `refunded_amount_minor` | `INTEGER` | no |  |
| `failure_code` | `TEXT` | yes |  |
| `failure_message_safe` | `TEXT` | yes |  |
| `raw_summary` | `JSON` | no |  |
| `created_at` | `DATETIME` | no |  |
| `updated_at` | `DATETIME` | no |  |

Indexes and constraints:

- `ix_payments_order_id`
- `ix_payments_provider_account_id`
- `ix_payments_region`
- `ix_payments_region_status_created_at`
- `ix_payments_status`
- `ix_payments_tenant_id`
- `uq_payments_provider_account_payment_id`

## `product_access_states`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `BIGINT` | no | PK |
| `user_id` | `CHAR(32)` | no | FK |
| `product_code` | `VARCHAR(64)` | no |  |
| `plan_code` | `VARCHAR(128)` | yes |  |
| `last_invoice_id` | `VARCHAR(128)` | yes |  |
| `last_transaction_id` | `VARCHAR(128)` | yes |  |
| `status` | `TEXT` | no |  |
| `starts_at` | `DATETIME` | yes |  |
| `expires_at` | `DATETIME` | yes |  |
| `updated_at` | `DATETIME` | no |  |

Indexes and constraints:

- `uq_user_product`
- `ix_product_access_states_last_invoice_id`
- `ix_product_access_states_product_code`
- `ix_product_access_states_user_id`

## `refunds`

| Column | Type | Nullable | Key |
|---|---|---:|---|
| `id` | `CHAR(32)` | no | PK |
| `tenant_id` | `TEXT` | no |  |
| `region` | `TEXT` | no | FK |
| `order_id` | `CHAR(32)` | no | FK |
| `payment_id` | `CHAR(32)` | no | FK |
| `provider_account_id` | `CHAR(32)` | no | FK |
| `provider_refund_id` | `TEXT` | yes |  |
| `status` | `TEXT` | no |  |
| `amount_minor` | `INTEGER` | no |  |
| `currency` | `VARCHAR(3)` | no |  |
| `reason` | `TEXT` | yes |  |
| `requested_at` | `DATETIME` | no |  |
| `succeeded_at` | `DATETIME` | yes |  |
| `metadata` | `JSON` | no |  |
| `created_at` | `DATETIME` | no |  |

Indexes and constraints:

- `ix_refunds_order_id`
- `ix_refunds_payment_id`
- `ix_refunds_provider_account_id`
- `ix_refunds_region`
- `ix_refunds_tenant_id`
- `uq_refunds_provider_account_refund_id`

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

- `uq_users_tenant_region_email_normalized`
- `ix_users_email_normalized`
- `ix_users_region`
- `ix_users_status`
- `ix_users_tenant_id`
