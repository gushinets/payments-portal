# ANY-522 Implementation Plan

**Issue:** ANY-522 — Implement Clean Target Persistence Baseline & Remove Legacy Commerce / CloudPayments  
**Parent:** ANY-504 — RU External Billing & Paid Access Architecture Program  
**Plan status:** `completed — retained implementation history and handoff evidence`  
**Final Step-3 baseline:** `main` at merge commit `87dbb62301fcf25eedb86bb897bbe92e021d9886`  
**Validated:** 2026-09-23  
**Completed:** 2026-09-24

---

## Completion record

Steps 1–9 are complete in the ANY-522 implementation. The repository now has
the clean 25-table first-install baseline, the retained identity/session/legal
runtime, provider-neutral target persistence with no producer runtime, and no
CloudPayments/direct-provider or Portal-owned commerce runtime. Generated
schema/OpenAPI artifacts and the recorded verification evidence form the final
Step-9 handoff. Sections below are preserved as the sequential implementation
contract and historical evidence; they are not instructions to restart at
Step 1. Later billing behavior remains owned by ANY-504 Steps 5–11.

---

## 1. Final researched baseline

ANY-510 / PR #118 is merged and `ANY-510` is `Done`.

The final merged Step-3 files were re-read from `main`, including:

- `docs/architecture/portal-identity-session-legal-baseline.md`;
- `docs/architecture/external-billing-persistence-reset.md`;
- final identity/legal ORM;
- final identity/legal API surfaces;
- transitional Step-3 Alembic revisions;
- repository harness and architecture guards affected by Step 4.

The merged content of the key Step-3 handoff, ORM and API files is identical to the last reviewed PR #118 head `f83fdaa3b7347583d45ea8a0af708ebb2a53a850`, so the previously researched Step-3 physical contract requires no architectural redesign.

The authority chain for this plan is:

1. ADR 0005 — External Billing Boundary;
2. `docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md`;
3. `docs/superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md`;
4. completed ANY-509 and `docs/architecture/external-billing-persistence-reset.md`;
5. completed ANY-510 and `docs/architecture/portal-identity-session-legal-baseline.md`;
6. ANY-504 for implementation order.

The current implementation remains intentionally transitional:

- Step-3 identity/session/recovery/legal behavior is the retained baseline;
- legacy Portal-owned catalog/checkout/order/payment/refund/subscription/entitlement/trial persistence still exists;
- `PaymentProviderRegistry` still exists in normal application composition, although CloudPayments is deactivated from normal runtime;
- CloudPayments/direct-provider source, settings, tests and frontend code still physically exist;
- the pre-reset Alembic history still includes the legacy schema plus the Step-3 transitional revisions;
- the repository harness still contains assumptions tied to the old initial migration, old billing enums and direct-provider cleanup state.

No unresolved Step-3 identity/session/legal architecture decision remains for ANY-522 to invent.

---

## 2. Authoritative implementation assumptions

ANY-522 is executed under the already approved ANY-504 program direction and the completed predecessor state present in the repository.

For implementation authority:

- ANY-504 defines the current program sequence and target architecture;
- completed ANY-509 defines the clean-reset / target-persistence contract;
- completed ANY-510 and the current `main` baseline define the retained identity/session/legal state;
- ANY-522 defines the Step-4 removal and persistence work to execute now.

Only the authority chain above, the completed predecessor state in the repository, and ANY-522 itself are implementation inputs. Codex must not broaden execution by consulting unrelated Linear tickets or reopening architecture already settled by ANY-504 / ANY-509 / ANY-510.

The clean-reset / recreate-only premise is already an approved input from ANY-509 / ANY-504 for this pre-production architecture transition:

- no compatibility bridge from the discarded billing schema is required;
- no legacy billing-data backfill is required;
- no dual-write is required;
- databases stamped with the discarded migration history are recreate-only;
- Step 7 replaces the old Alembic history with the clean first-install baseline rather than preserving an upgrade path from the superseded schema.

Execution agents should stop only for a **material contradiction in the current repository or completed predecessor state** that makes the approved ANY-522 result unsafe or impossible. They should not perform unrelated ticket research or reopen architecture already settled by the authority chain.

---

## 3. Locked Step-4 outcome

After ANY-522, a fresh installation must contain exactly:

```text
10 retained Step-3 identity/session/legal/contour tables
+
15 approved target external-billing persistence tables
=
25 application tables
```

There must be:

- one fresh first-install Alembic baseline;
- one Alembic head;
- no old Portal-owned catalog/order/payment/subscription/entitlement/trial table;
- no `external_billing_accounts` table;
- no CloudPayments/direct-provider runtime;
- no target billing runtime from ANY-504 Steps 5–11;
- no target table populated by Step-4 application behavior.

External Billing must not be implemented through `PaymentProviderAdapter` or `PaymentProviderRegistry`.

---

## 4. Final Step-3 survivor physical contract and traceability

The merged ANY-510 Step-3 ORM and `docs/architecture/portal-identity-session-legal-baseline.md` are fixed input. The table below records the final Step-4 survivor shape so execution does not need to rediscover it.

| Table | Final retained fields / defaults / nullability | Structural invariants and indexes | Bootstrap / verification ownership |
| --- | --- | --- | --- |
| `regions` | `code text PK`; `name text not null`; `residency_zone text not null`; `default_currency varchar(3) not null`; `default_locale text not null`; `status RegionStatus text not null` with ORM-only default `active` and no DB server default | No provider-routing columns; no additional business identity beyond `code` | Step 7 creates only configured-contour rows; survivor behavior verified by Step-3 API/bootstrap tests |
| `country_region_rules` | `id UUID PK` with ORM-only `uuid4` and no DB server default; `country_code varchar(2) not null`; `region text not null`; `market_enabled bool not null` ORM-only default `true`; `strict_mismatch bool not null` ORM-only default `true`; `default_document_set text not null`; `allow_region_override` and `default_payment_provider` absent | `country_code UNIQUE` and indexed; `region -> regions.code` and indexed | Step 7 RU bootstrap keeps only configured contour/country membership/document config |
| `users` | `id UUID PK` with ORM `uuid4`; `tenant_id text not null`; `region text not null`; `email varchar(320) not null`; `email_normalized varchar(320) not null`; `email_verified_at timestamptz null`; `status UserStatus text not null` ORM-only default `active`; `last_login_at timestamptz null`; `password_hash text null`; `metadata json/jsonb not null` ORM-only default `{}`; `created_at timestamptz not null` server default `now()`; `updated_at timestamptz not null` server default `now()` with ORM on-update timestamp | `region -> regions.code`; `UNIQUE(tenant_id, region, email_normalized)`; `UNIQUE(id, tenant_id, region)`; indexes on `tenant_id`, `region`, `email_normalized`, `status` | Step 7 migration + Step-3 registration/auth/scope/concurrency regressions |
| `auth_sessions` | `id UUID PK` with ORM `uuid4`; `tenant_id text not null`; `region text not null`; `user_id UUID not null`; `token_hash text not null`; `created_at timestamptz not null` server default `now()`; `expires_at timestamptz not null`; `last_seen_at timestamptz not null` server default `now()`; `revoked_at timestamptz null`; `ip inet null`; `user_agent text null` | `region -> regions.code`; `token_hash UNIQUE` and indexed; composite FK `(user_id, tenant_id, region) -> users(id, tenant_id, region) ON DELETE RESTRICT`; indexes on `tenant_id`, `region`, `user_id` | Step 7 + Step-3 logout/revocation/foreign-contour/session-scope tests |
| `magic_link_tokens` | `id UUID PK` with ORM `uuid4`; `tenant_id text not null`; `region text not null`; `user_id UUID null` only for unknown-email decoys; `email_normalized varchar(320) not null`; `token_hash text not null`; `purpose MagicLinkPurpose text not null`; `created_at timestamptz not null` server default `now()`; `expires_at timestamptz not null`; `used_at timestamptz null`; `ip inet null`; `user_agent text null`; no `entrypoint_session_id` | `region -> regions.code`; `token_hash UNIQUE` and indexed; nullable composite FK `(user_id, tenant_id, region) -> users(id, tenant_id, region) ON DELETE RESTRICT`; indexes on `tenant_id`, `region`, `user_id`, `email_normalized` | Step 7 + Step-3 known-user/decoy/recovery-scope tests |
| `password_reset_rate_limits` | `rate_limit_key text PK`; `count integer not null` ORM-only default `0`; `window_start timestamptz not null`; `expires_at timestamptz not null`; `created_at timestamptz not null` server default `now()`; `updated_at timestamptz not null` server default `now()` with ORM on-update timestamp | index on `expires_at`; persisted shared throttle state | Step 7 + existing PostgreSQL rate-limit upsert test |
| `legal_entities` | `id UUID PK` with ORM `uuid4`; `tenant_id text not null`; `region text not null`; `name text not null`; `entity_type LegalEntityType text not null`; `tax_id text null`; `registration_id text null`; `legal_address text not null`; `support_email text not null`; `status LegalEntityStatus text not null` ORM-only default `active`; `created_at timestamptz not null` server default `now()`; `updated_at timestamptz not null` server default `now()` with ORM on-update timestamp | `region -> regions.code`; `UNIQUE(id, tenant_id, region)`; indexes on `tenant_id`, `region`, `status`; composite index `(tenant_id, region, status)` | Step 7 legal bootstrap and scope tests |
| `document_versions` | `id UUID PK` with ORM `uuid4`; `tenant_id text not null`; `region text not null`; `legal_entity_id UUID not null`; `doc_type text not null`; `version text not null`; `title text not null`; `url_path text not null`; `content_hash text not null`; `published_at timestamptz not null`; `effective_from timestamptz not null`; `is_active bool not null` ORM-only default `true`; `requires_acceptance bool not null` ORM-only default `true`; `created_at timestamptz not null` server default `now()`; `updated_at timestamptz not null` server default `now()` with ORM on-update timestamp | `region -> regions.code`; composite FK `(legal_entity_id, tenant_id, region) -> legal_entities(id, tenant_id, region) ON DELETE RESTRICT`; `UNIQUE(tenant_id, region, doc_type, version)`; `UNIQUE(id, tenant_id, region)`; partial unique index `(tenant_id, region, doc_type) WHERE is_active = true`; indexes on `tenant_id`, `region`, `legal_entity_id`, `doc_type`, `is_active`; composite index `(region, is_active)` | Step 7 recreates material-immutability PostgreSQL guard and fail-closed legal bootstrap; existing immutable-version tests survive |
| `legal_acceptance_events` | `id UUID PK` with ORM `uuid4`; `tenant_id text not null`; `region text not null`; `user_id UUID not null`; `external_billing_account_id text null`; `billing_offer_id text null`; `accepted_commercial_fingerprint text null`; `accepted_at timestamptz not null` server default `now()`; `ip inet null`; `user_agent text null`; `created_at timestamptz not null` server default `now()` | `region -> regions.code`; composite FK `(user_id, tenant_id, region) -> users(id, tenant_id, region) ON DELETE RESTRICT`; all-null/all-nonempty commercial-triplet check; `UNIQUE(id, tenant_id, region, user_id)`; `UNIQUE(id, user_id, external_billing_account_id, billing_offer_id, accepted_commercial_fingerprint)`; indexes on `tenant_id`, `region`, `user_id`, `accepted_at` | Step 7 recreates immutable-core + IP/user-agent clear-only PostgreSQL guard; purchase FK target verified in target DDL tests |
| `document_acceptances` | exactly `id UUID PK` with ORM `uuid4`; `legal_acceptance_event_id UUID not null`; `tenant_id text not null`; `region text not null`; `user_id UUID not null`; `document_version_id UUID not null`; `acceptance_kind AcceptanceKind text not null`; `acceptance_text_hash text not null`; `created_at timestamptz not null` server default `now()` | `region -> regions.code`; composite FK `(legal_acceptance_event_id, tenant_id, region, user_id) -> legal_acceptance_events(id, tenant_id, region, user_id) ON DELETE RESTRICT`; composite FK `(document_version_id, tenant_id, region) -> document_versions(id, tenant_id, region) ON DELETE RESTRICT`; `UNIQUE(legal_acceptance_event_id, document_version_id)`; indexes on `legal_acceptance_event_id`, `tenant_id`, `region`, `user_id`, `document_version_id`; no old `doc_type`/`version`/`accepted_at`/entrypoint indexes | Step 7 recreates unconditional UPDATE/DELETE rejection; generic acceptance remains append-only/new-event-per-call |

### Step-3 PostgreSQL-only protections that Step 7 must recreate exactly

1. `legal_acceptance_events`: reject every DELETE; reject UPDATE of identity/scope/user/commercial triplet/`accepted_at`/`created_at`; permit `ip` and `user_agent` only `value -> NULL`, never `NULL -> value` or value replacement.
2. `document_acceptances`: reject every UPDATE and DELETE.
3. `document_versions`: reject every DELETE and material UPDATE of id/scope/legal entity/type/version/title/url/content hash/publication/effective timestamps/`requires_acceptance`; allow intended `is_active` lifecycle change and corresponding `updated_at`.

### Step-3 bootstrap contract

- configured instance tenant/region is authoritative;
- RU clean data plane does not seed legacy `eu`/DE/ES rows;
- legal source/manifest remains canonical bootstrap input;
- bootstrap fails closed on same-version material mismatch rather than rewriting published legal meaning;
- no Product/Plan/Bundle/provider-account target seed is allowed.

### Step-3 survivor verification

Step 7/9 must preserve the existing **provider-independent behavior proofs** from the Step-3 regression matrix: server-authoritative scope, atomic/concurrent registration, session invalidation/logout, recovery, scope FKs/restrictive deletion, legal immutability/append-only evidence, commercial-triplet validity, active-only users, architecture prohibition of external-billing-account identity coupling, and legal manifest/hash integrity.

The old Step-3 **upgrade/backfill migration tests are not survivor behavior** after the clean reset. They must not force a compatibility migration or backfill path back into ANY-522. Step 7 replaces those discarded-history tests with equivalent clean-first-install/bootstrap/constraint/trigger proofs for the final retained schema. Existing named runtime/identity/legal tests remain the canonical behavior inventory and may only be adapted when the clean physical schema requires it.

---

## 5. Target persistence physical-invariant traceability

This section is the implementation map. Execution models should use it as the fixed requirement set. The corresponding ANY-509 table section may be opened only to verify an exact SQLAlchemy/Alembic spelling or index name, not to derive new requirements or redesign the schema.

For every target table:

Numbering note: the numbered `# Step N` headings are execution steps inside this ANY-522 plan. Any deferred program owner is written explicitly as `ANY-504 Step N`.

- **ORM owner** = the Step that introduces the SQLAlchemy model;
- **DDL owner** = Step 7 clean baseline;
- **verification owner** = Step 7 PostgreSQL/schema suite, with final generated-schema confirmation in Step 9;
- every listed later-owned field is still created physically now;
- a `PHASE_0_GATED` or `LATER_STEP_RUNTIME` semantic rule remains open even when its storage column exists;
- no provider-specific uniqueness/status interpretation is added unless explicitly `STEP_4_SAFE` below.

### 5.1 `capability_manifest_projections` — ORM Step 4

Fields created now:

```text
projection_id UUID not null PK
tenant_id text not null
region text not null
schema_version integer not null
manifest_version text not null
generated_at timestamptz not null
last_complete_sync_at timestamptz not null
manifest_document jsonb not null
```

Step-4 physical invariants:

- `UNIQUE(tenant_id, region)` for the single LKG projection scope plus lookup index;
- lookup index on `manifest_version`; its non-empty/content validation remains ANY-504 Step 6 runtime and is not a Step-4 CHECK;
- freshness index on `last_complete_sync_at`;
- no Portal Product FK for any Kernel `product_id`/`metric_key` inside the document.

Deferred semantics: atomic LKG replacement, typed-document validation, freshness enforcement and the 24-hour admission rule are ANY-504 Steps 6–7 runtime behavior, not Step-4 application behavior.

### 5.2 `external_billing_catalog_projections` — ORM Step 4

Fields:

```text
projection_id UUID not null PK
external_billing_account_id text not null
schema_version text not null
catalog_version text null
catalog_digest text not null
last_complete_sync_at timestamptz not null
catalog_document jsonb not null
```

Step-4 physical invariants:

- one LKG row per `external_billing_account_id` via unique scope;
- `schema_version` is physically non-null as approved, but its non-empty/content validation remains ANY-504 Step 6 runtime and is not a Step-4 CHECK;
- `catalog_version` indexed when present but deliberately nullable/opaque;
- `catalog_digest` indexed;
- freshness index on `last_complete_sync_at`;
- no FK to a Portal-owned offer/product catalog.

Deferred/gated: meaning/canonicality of `catalog_version` is Phase 0 / ANY-504 Steps 5–6; normalized document validation, complete replacement and freshness behavior are ANY-504 Step 6.

### 5.3 `commercial_mapping_revisions` — ORM Step 4

Fields:

```text
mapping_revision_id UUID not null PK
external_billing_account_id text not null
billing_offer_id text not null
revision_number bigint not null
manifest_version text not null
catalog_version text null
catalog_digest text not null
mapping_schema_version text not null
mapping_document jsonb not null
published_at timestamptz not null
published_by_principal text not null
```

Step-4 physical invariants:

- `UNIQUE(mapping_revision_id, external_billing_account_id)`;
- `UNIQUE(mapping_revision_id, external_billing_account_id, billing_offer_id)`;
- `revision_number > 0`;
- `UNIQUE(external_billing_account_id, billing_offer_id, revision_number)`;
- the unique `(external_billing_account_id, billing_offer_id, revision_number)` key is the revision lookup/current-order key;
- publication lookup indexes cover `(external_billing_account_id, billing_offer_id, published_at)` and manifest lookup within the same account/offer publication scope; `published_by_principal` has an audit lookup index;
- `mapping_schema_version` non-empty is Step-4-safe; `published_by_principal` is physically non-null and indexed, while principal/non-empty semantics remain ANY-504 Step 6 runtime;
- immutable historical mapping fields receive schema-level immutability protection in Step 7 as required by the ANY-509 verification matrix.

Deferred/gated: `catalog_version` semantics remain opaque until ANY-504 Steps 5–6; calculating/publishing the next monotonic revision and validating `mapping_document` are ANY-504 Step 6 runtime responsibilities. Step 4 enforces only positive revision number + scoped uniqueness, not publication sequencing behavior.

### 5.4 `external_billing_customers` — ORM Step 4

Fields:

```text
customer_id UUID not null PK
external_billing_account_id text not null
user_id UUID not null
billing_customer_key text not null
provider_customer_id text null
binding_state closed text enum not null default unbound
binding_updated_at timestamptz not null
created_at timestamptz not null
```

Step-4 physical invariants:

- FK `user_id -> users.id ON DELETE RESTRICT`;
- `UNIQUE(customer_id, external_billing_account_id, user_id)`;
- `UNIQUE(external_billing_account_id, user_id)`;
- `billing_customer_key` non-empty and globally unique across all customer slots;
- closed `binding_state = unbound | bound | identity_conflict`;
- `provider_customer_id` indexed when present but no pre-Phase-0 uniqueness;
- `binding_state` has a state lookup index.

Deferred/gated: provider customer identity/correction semantics and provider-ID uniqueness are ANY-504 Steps 5 and 7 / Phase-0 concerns; allocation/binding behavior is ANY-504 Step 7.

### 5.5 `purchase_intents` — ORM Step 4

Fields:

```text
purchase_intent_id UUID not null PK
user_id UUID not null
external_billing_account_id text not null
customer_id UUID not null
product_id text not null
billing_offer_id text not null
mapping_revision_id UUID not null
accepted_commercial_fingerprint text not null
client_idempotency_key text not null
state closed text enum not null default created
accepted_snapshot_schema_version text not null
accepted_snapshot jsonb not null
legal_acceptance_event_id UUID not null
created_at timestamptz not null
state_updated_at timestamptz not null
resolved_at timestamptz null
```

Step-4 physical invariants:

- `user_id -> users.id ON DELETE RESTRICT`;
- composite customer FK `(customer_id, external_billing_account_id, user_id)`;
- composite mapping FK `(mapping_revision_id, external_billing_account_id, billing_offer_id)`;
- exact composite legal-evidence FK `(legal_acceptance_event_id, user_id, external_billing_account_id, billing_offer_id, accepted_commercial_fingerprint)` to the Step-3 purchase-binding key, `ON DELETE RESTRICT`;
- `accepted_commercial_fingerprint`, `client_idempotency_key`, `accepted_snapshot_schema_version` non-empty;
- `UNIQUE(external_billing_account_id, user_id, client_idempotency_key)`;
- alternate relational targets `UNIQUE(purchase_intent_id, customer_id)`, `UNIQUE(purchase_intent_id, external_billing_account_id, user_id, product_id)`, and `UNIQUE(purchase_intent_id, customer_id, external_billing_account_id, user_id, product_id, mapping_revision_id)`;
- closed state vocabulary `created | preparing | awaiting_external_result | linked | resolved_no_external_effect | failed_before_external_effect | manual_review`;
- lookup/index coverage for `(user_id, product_id)`, `(external_billing_account_id, billing_offer_id)`, customer/purchase lookup, `mapping_revision_id`, `accepted_commercial_fingerprint`, `state`, and `state_updated_at` recovery scans;
- Step 7 adds schema-level immutability protection for accepted/provenance fields and accepted snapshot while still allowing later-owned state timestamps/state transitions.

Deferred: replay-vs-conflict comparison, accepted-snapshot typed validation, state transitions and subscription linking are ANY-504 Steps 7–8 runtime.

### 5.6 `external_create_operations` — ORM Step 4

Fields:

```text
create_operation_id UUID not null PK
operation_kind closed text enum not null
customer_id UUID not null
purchase_intent_id UUID null
request_correlation_key text not null
operation_state text not null
unknown_since timestamptz null
unknown_recovery_deadline_at timestamptz null
recovery_hint_schema_version text null
recovery_hint_document jsonb null
bound_external_object_id text null
created_at timestamptz not null
updated_at timestamptz not null
resolved_at timestamptz null
```

Step-4 physical invariants:

- `operation_kind = customer | agreement | subscription`;
- customer FK `ON DELETE RESTRICT`;
- composite `(purchase_intent_id, customer_id)` FK to purchase when present;
- `purchase_intent_id` forbidden for `customer` and required for `agreement`/`subscription`;
- partial `UNIQUE(customer_id) WHERE operation_kind = 'customer' AND resolved_at IS NULL`;
- `request_correlation_key` non-empty/indexed but provider meaning remains opaque;
- `unknown_since` and `unknown_recovery_deadline_at` both null or both present; when present deadline equals `unknown_since + 2 hours`;
- recovery-hint schema/document pairing;
- `bound_external_object_id` indexed when present with no pre-Phase-0 uniqueness;
- lookup/index coverage for customer/state recovery, `purchase_intent_id`, `request_correlation_key`, unknown recovery deadline, bound external object, and state/deadline update scans;
- `operation_state` remains open text and must not receive a speculative enum/check.

Deferred/gated: exact provider correlation, external-object identity, operation-state vocabulary and recovery transitions are ANY-504 Steps 5, 7 and 8.

### 5.7 `billing_product_access_scopes` — ORM Step 5

Fields:

```text
access_scope_id UUID not null PK
user_id UUID not null
product_id text not null
primary_subscription_id UUID null
updated_at timestamptz not null
```

Step-4 physical invariants:

- `user_id -> users.id ON DELETE RESTRICT`;
- `UNIQUE(access_scope_id, user_id, product_id)`;
- `UNIQUE(user_id, product_id)`;
- composite FK `(primary_subscription_id, user_id, product_id) -> external_subscriptions(subscription_id, user_id, product_id) ON DELETE RESTRICT`;
- reverse lookup index on primary subscription.

Deferred: row acquisition/locking, scope ownership and deterministic primary-selection behavior are ANY-504 Steps 7–9 runtime.

### 5.8 `external_subscriptions` — ORM Step 5

Fields:

```text
subscription_id UUID not null PK
external_billing_account_id text not null
customer_id UUID not null
user_id UUID not null
product_id text not null
purchase_intent_id UUID null
mapping_revision_id UUID null
external_subscription_id text null
external_agreement_id text null
lifecycle_status closed text enum not null
financial_access_status closed text enum not null
commercial_access_status closed text enum not null
last_authoritative_read_at timestamptz not null
projection_valid_until timestamptz not null
reconciliation_lease_owner text null
reconciliation_lease_expires_at timestamptz null
reconciliation_fencing_token bigint not null default 0
latest_observation_id UUID null
created_at timestamptz not null
updated_at timestamptz not null
```

Step-4 physical invariants:

- alternate keys `UNIQUE(subscription_id, product_id)`, `UNIQUE(subscription_id, user_id, product_id)`, `UNIQUE(subscription_id, external_billing_account_id, user_id, product_id)`;
- composite customer FK `(customer_id, external_billing_account_id, user_id)`;
- nullable composite purchase/provenance FK `(purchase_intent_id, customer_id, external_billing_account_id, user_id, product_id, mapping_revision_id)`;
- partial `UNIQUE(purchase_intent_id)` when non-null;
- composite mapping FK `(mapping_revision_id, external_billing_account_id)` and check requiring mapping revision when purchase link exists;
- external subscription/agreement IDs indexed but nullable/opaque/no pre-Phase-0 uniqueness;
- closed status vocabularies: lifecycle `active|inactive|ended`, financial `allowed|blocked`, commercial `eligible|ineligible`;
- reconciliation lease owner/expiry paired-nullability check;
- `reconciliation_fencing_token >= 0` storage;
- composite `(latest_observation_id, subscription_id)` FK to observation target;
- lookup/index coverage for account/customer, user/product/status, customer/product/status, purchase provenance, mapping provenance, external subscription/agreement IDs, each closed status, `last_authoritative_read_at`, `projection_valid_until`, reconciliation lease expiry/claim scans, and `latest_observation_id`.

Deferred/gated: canonical provider subscription/agreement semantics and uniqueness are ANY-504 Step 5; projection transitions, lease/fencing behavior and latest-observation kind/causality are ANY-504 Steps 8–9 runtime.

### 5.9 `billing_state_observations` — ORM Step 5

Fields:

```text
observation_id UUID not null PK
observation_kind closed text enum not null
external_billing_account_id text not null
user_id UUID null
product_id text null
access_scope_id UUID null
subscription_id UUID null
purchase_intent_id UUID null
work_item_id UUID null
basis_observation_id UUID null
observed_at timestamptz not null
effective_at timestamptz null
evidence_schema_version text not null
evidence_document jsonb not null
completeness_classification text not null
result_classification text not null
resulting_access_revision bigint null
created_at timestamptz not null
```

Step-4 physical invariants:

- `UNIQUE(observation_id, access_scope_id)` and `UNIQUE(observation_id, subscription_id)`;
- closed observation kind `authoritative_subscription_read | target_product_discovery | primary_selection | deterministic_access_boundary`;
- user FK `ON DELETE RESTRICT`;
- composite scope FK to `billing_product_access_scopes`;
- composite subscription FK to `external_subscriptions`;
- composite purchase FK to `purchase_intents`;
- `work_item_id -> billing_work_items.work_item_id ON DELETE SET NULL`;
- same-scope self-FK `(basis_observation_id, access_scope_id)`;
- `CHECK(subscription_id IS NULL OR purchase_intent_id IS NULL)`;
- require user/product when scope/subscription/purchase references are present;
- kind-shape check: authoritative read requires subscription; discovery requires user+product+scope; primary selection requires scope+basis; deterministic boundary requires scope+subscription+effective_at;
- `evidence_schema_version` non-empty;
- `resulting_access_revision` remains nullable storage in Step 4; positivity and the one-time semantic bind are ANY-504 Step 9 runtime and are not encoded as a Step-4 CHECK;
- lookup/index coverage for observation kind/time, account/kind/time, user/product/time, access-scope/time, subscription/time, direct-purchase/time, `work_item_id`, `basis_observation_id`, `effective_at`, completeness/result classifications, and canonical scope/revision audit lookup;
- completeness/result classifications stay open text.

Deferred: typed evidence validation, result/completeness vocabularies, basis-kind causality, latest-observation kind causality and the one-time `resulting_access_revision` transition are ANY-504 Steps 8–9 runtime.

### 5.10 `purchased_allowances` — ORM Step 5

Fields:

```text
allowance_id UUID not null PK
subscription_id UUID not null
source_component_id text not null
product_id text not null
metric_key text not null
quantity bigint not null
provider_cycle_key text null
provider_cycle_start timestamptz null
provider_cycle_end timestamptz null
period_start timestamptz not null
period_end timestamptz not null
created_at timestamptz not null
```

Step-4 physical invariants:

- composite FK `(subscription_id, product_id) -> external_subscriptions(subscription_id, product_id) ON DELETE RESTRICT`;
- `quantity >= 0`;
- provider-cycle raw start/end both null or both present;
- `period_start < period_end`;
- provider cycle key indexed but no Phase-0 logical uniqueness;
- lookup/index coverage for subscription/cycle, subscription/component/cycle, and product/metric queries;
- no persisted `remaining`;
- Step 7 adds schema-level immutability protection for the frozen allowance identity/product/metric/quantity/effective-period tuple required by the ANY-509 DDL verification matrix.

Deferred/gated: provider cycle identity/uniqueness and authoritative quantity source are ANY-504 Steps 5 and 9; materialization and clock-skew derivation are ANY-504 Step 9.

### 5.11 `external_billing_webhook_deliveries` — ORM Step 5

Fields:

```text
delivery_id UUID not null PK
external_billing_account_id text not null
provider_event_id text null
payload_hash text not null
correlation_schema_version text not null
correlation_document jsonb not null
evidence_schema_version text not null
evidence_document jsonb not null
processing_state text not null
received_at timestamptz not null
processing_started_at timestamptz null
processed_at timestamptz null
last_error_classification text null
```

Step-4 physical invariants:

- account/receipt lookup index, processing/receipt scan index and `received_at` scan index;
- provider event ID indexed when present but no pre-Phase-0 uniqueness;
- `payload_hash` indexed for bounded correlation/dedup evidence;
- `payload_hash`, correlation schema version and evidence schema version non-empty;
- bounded/redacted documents only; raw webhook body/payment history/secrets are forbidden by architecture/static tests;
- processing state remains open text.

Deferred/gated: provider event dedup semantics are ANY-504 Step 5; processing vocabulary and transitions are ANY-504 Step 8.

### 5.12 `billing_work_items` — ORM Step 5

Fields:

```text
work_item_id UUID not null PK
work_kind text not null
scope_kind text not null
scope_reference text not null
coalescing_key text null
payload_schema_version text not null
payload_document jsonb not null
priority integer not null default 0
next_attempt_at timestamptz not null
attempt_count integer not null default 0
work_state text not null
lease_owner text null
lease_expires_at timestamptz null
last_error_classification text null
created_at timestamptz not null
updated_at timestamptz not null
```

Step-4 physical invariants:

- payload schema version non-empty;
- indexes cover `(work_kind, work_state, next_attempt_at)` due scans, `(scope_kind, scope_reference)` scope lookup, `coalescing_key`, `(work_state, priority, next_attempt_at)` retry/priority scans, `lease_expires_at`/claim scans, and the approved state/kind lookup paths;
- create `attempt_count` as non-null integer with default `0`, but do **not** add an `attempt_count >= 0` database CHECK in Step 4: the ANY-509 matrix classifies that constraint/transition semantics as `LATER_STEP_RUNTIME` owned by ANY-504 Step 8;
- lease owner/expiry both null or both present; this paired-nullability CHECK is `STEP_4_SAFE` and is installed now;
- no exact coalescing uniqueness before ANY-504 Step 8 closes applicable work kinds/states;
- work kind, scope kind and work state remain open text.

Deferred: work vocabularies, scheduling/coalescing behavior, claims/retries and deterministic-deadline execution are ANY-504 Steps 8–9 runtime.

### 5.13 `manual_review_cases` — ORM Step 5

Fields:

```text
review_case_id UUID not null PK
reason_code text not null
scope_kind text not null
scope_reference text not null
evidence_schema_version text not null
evidence_document jsonb not null
case_state text not null
created_at timestamptz not null
resolved_at timestamptz null
resolved_by_principal text null
resolution_schema_version text null
resolution_document jsonb null
```

Step-4 physical shape:

- evidence schema version non-empty;
- indexes cover `(reason_code, case_state)`, `(scope_kind, scope_reference)`, `case_state`, `created_at` state/time lookup, and `resolved_by_principal` audit lookup when present;
- reason/scope/state remain open text;
- create all nullable resolution slots now;
- do **not** add Step-4 database CHECKs tying `resolved_at`, `resolved_by_principal`, `resolution_schema_version` or `resolution_document` together: those pairing/non-empty/set-once semantics are `LATER_STEP_RUNTIME` in ANY-509 and belong to ANY-504 Steps 7–9;
- the only Step-4-safe manual-review content CHECK is non-empty `evidence_schema_version`.

Deferred: resolution-field pairing, principal mapping, resolution schema/document validation, case-state vocabulary, resolution transitions and any access/commercial consequence are ANY-504 Steps 7–9 runtime.

### 5.14 `paid_access_states` — ORM Step 6

Fields:

```text
paid_access_state_id UUID not null PK
tenant_id text not null
region text not null
user_id UUID not null
access_revision bigint not null
effective_state_schema_version text not null
effective_state_document jsonb not null
committed_at timestamptz not null
```

Step-4 physical invariants:

- composite FK `(user_id, tenant_id, region) -> users(id, tenant_id, region) ON DELETE RESTRICT`;
- `UNIQUE(tenant_id, region, user_id)`;
- `access_revision` is physically non-null; revision production/monotonicity and positive-value validation remain ANY-504 Step 9 runtime rather than a Step-4 CHECK;
- `effective_state_schema_version` is physically non-null; semantic/non-empty document-version validation remains ANY-504 Step 9 runtime;
- no Step-4 runtime creates a row at revision zero; absence represents implicit revision zero;
- no provider identifiers/statuses or runtime remaining quota.

Deferred: semantic document validation, user-row lock protocol, revision production and paid-access derivation are ANY-504 Steps 9–10 runtime.

### 5.15 `access_invalidation_outbox` — ORM Step 6

Fields:

```text
outbox_id UUID not null PK
tenant_id text not null
region text not null
user_id UUID not null
pending_revision bigint not null
delivered_revision bigint not null default 0
attempt_count integer not null default 0
next_attempt_at timestamptz not null
last_error_classification text null
created_at timestamptz not null
updated_at timestamptz not null
```

Step-4 physical invariants:

- same composite canonical-user FK and `UNIQUE(tenant_id, region, user_id)` as `paid_access_states`;
- `pending_revision > 0`;
- `pending_revision >= delivered_revision`;
- `delivered_revision` and `attempt_count` keep their approved non-null/default-`0` storage, but their non-negative transition validation remains ANY-504 Step 10 runtime and is not added as a Step-4 CHECK;
- due-delivery index;
- revision zero cannot create a durable outbox row.

Deferred: production/coalescing, delivery, acknowledgement and retry behavior are ANY-504 Steps 9–10 runtime.

### 5.16 Cross-table DDL immutability assignment

Step 7 must not interpret every `Immutable` label as permission to invent a generic trigger framework. Implement the focused PostgreSQL protections below because they are required to keep Step-4 historical/identity evidence from being silently rewritten; do not generalize them into a reusable trigger framework.

- all three exact Step-3 legal protections in Section 4;
- `external_billing_customers`: reject DELETE of an allocated customer-slot row and reject UPDATE of `customer_id`, `external_billing_account_id`, `user_id`, `billing_customer_key`, and `created_at`; later-owned provider binding/state fields remain mutable only through their later runtime owner. This preserves permanent local non-reuse of `billing_customer_key` without encoding provider-ID semantics;
- `commercial_mapping_revisions`: reject DELETE and reject UPDATE of every stored field (`mapping_revision_id`, `external_billing_account_id`, `billing_offer_id`, `revision_number`, `manifest_version`, `catalog_version`, `catalog_digest`, `mapping_schema_version`, `mapping_document`, `published_at`, `published_by_principal`);
- `purchase_intents`: reject DELETE and reject UPDATE of immutable identity/provenance/accepted-evidence fields (`purchase_intent_id`, `user_id`, `external_billing_account_id`, `customer_id`, `product_id`, `billing_offer_id`, `mapping_revision_id`, `accepted_commercial_fingerprint`, `client_idempotency_key`, `accepted_snapshot_schema_version`, `accepted_snapshot`, `legal_acceptance_event_id`, `created_at`); leave only the later-owned `state`, `state_updated_at` and `resolved_at` transition fields outside this guard;
- `billing_state_observations`: reject DELETE and reject UPDATE of every field except `resulting_access_revision`; that field may change at most once from `NULL` to a non-null value, while positivity and semantic/causal binding remain ANY-504 Step 9 runtime. A populated value cannot be replaced or cleared;
- `purchased_allowances`: reject DELETE and reject UPDATE of the frozen stored row (`allowance_id`, `subscription_id`, `source_component_id`, `product_id`, `metric_key`, `quantity`, `provider_cycle_key`, `provider_cycle_start`, `provider_cycle_end`, `period_start`, `period_end`, `created_at`).

For Step 7, this section is the explicit target DDL-immutability assignment. Do not add triggers merely because another field is described as `Immutable` in a later-runtime semantic contract, and do not remove one of the protections above without a concrete contradiction against the merged ANY-509 handoff.

### 5.17 FK-cycle implementation and clean-baseline DDL order

The following models are intentionally implemented together in Step 5 because their approved schema contains cross-references that form one persistence graph:

```text
billing_product_access_scopes
        ↕
external_subscriptions
        ↕
billing_state_observations
        ↓
purchased_allowances

billing_state_observations -> billing_work_items
```

This avoids an intermediate commit whose SQLAlchemy metadata references a table that does not yet exist.

Step 7 must also handle the same graph explicitly in Alembic. Do **not** rely on declaration order or weaken any approved FK. The clean first-install migration uses this two-phase DDL sequence:

1. create prerequisite tables that do not depend on the cycle, including `users`, `external_billing_customers`, `commercial_mapping_revisions`, `purchase_intents`, and `billing_work_items`;
2. create `billing_product_access_scopes` with `primary_subscription_id` present but defer only its composite FK to `external_subscriptions`;
3. create `external_subscriptions` with `latest_observation_id` present but defer only its composite FK to `billing_state_observations`; all customer/purchase/mapping FKs and Step-4-safe checks that already have targets are created immediately;
4. create `billing_state_observations` with its scope/subscription/purchase/work/self-reference columns and all FKs whose targets now exist;
5. add the deferred composite FK `(billing_product_access_scopes.primary_subscription_id, user_id, product_id) -> external_subscriptions(subscription_id, user_id, product_id) ON DELETE RESTRICT`;
6. add the deferred composite FK `(external_subscriptions.latest_observation_id, subscription_id) -> billing_state_observations(observation_id, subscription_id) ON DELETE RESTRICT`;
7. create `purchased_allowances` and the remaining dependent tables/constraints.

The downgrade path must reverse dependency order: drop the two cycle-closing FKs before dropping `billing_state_observations`, `external_subscriptions`, or `billing_product_access_scopes`.

Only those two cycle-closing FKs are deferred during table creation. This is migration mechanics, not a relaxation of the final schema: after `upgrade head` the same complete approved FK graph must exist and be covered by negative mismatch tests.

---

## 5.18 Sequential checkpoint / merge-readiness contract

Steps 1–8 are **branch-local checkpoint steps**, not independent merge/deploy candidates. The plan intentionally postpones canonical current-state documentation alignment and generated DB/OpenAPI artifacts until Steps 8–9, so `npm run check` is not a required green boundary after every earlier checkpoint.

Each checkpoint must still be internally source-coherent:

- imports and application composition for the changed source must resolve;
- the step-specific manual verification commands listed in that step must pass, except a check explicitly documented as intentionally stale because its owning docs/generated-artifact step has not run yet;
- no checkpoint may leave an accidental missing-file reference such as the deleted Alembic baseline path — Step 7 updates that source in the same commit;
- no partial checkpoint may be deployed or merged into `main`.

Step 9 is the **single canonical CI/merge-ready boundary**: `npm run generate:check` and the full `npm run check` must pass there. If CI is configured to require the full canonical suite on every pushed commit, keep Steps 1–8 local/squashed or otherwise avoid presenting them as merge candidates; do not weaken repository gates merely to make intermediate commits green.

### 5.19 Historical Codex execution protocol used for separate chats

This plan used **one fresh Codex chat per implementation step**.

Before Step 1, this document was placed in the repository as:

```text
docs/exec-plans/completed/ANY-522-implementation-plan.md
```

The following completed protocol is retained as implementation evidence and
must not be restarted:

1. Start from the same ANY-522 branch/worktree; all previous numbered steps must already be implemented there.
2. Paste only the `AI prompt` for the selected step into the fresh chat. The prompt may read the canonical plan file above, but only the explicitly named sections for that step; it must not reread the whole plan or redo predecessor research.
3. The new chat must not rely on memory from an earlier Codex chat. Current Git/source state and the canonical plan are the complete handoff.
4. Codex may inspect `git status --short`, a short recent `git log`, and directly named source files to confirm the previous step is present. If the prerequisite state is missing or materially contradicts the plan, it must stop rather than compensate by implementing multiple steps at once.
5. Codex implements only the selected step and does **not** run tests/linters/formatters unless the selected prompt explicitly permits a command (Step 9 permits only generation). The user runs the step's `Manual verification` commands.
6. Do not start the next chat until the current step's manual verification passes and the step is committed (or otherwise fixed as the stable branch checkpoint).
7. A failed manual verification is repaired within the same numbered step; do not move the fix into a later step merely to preserve the plan sequence.
8. Do not broaden a step with unrelated Linear-ticket research. ANY-504, completed ANY-509/ANY-510, the current repository state and this plan are the implementation authority.

The objective of this protocol is not to minimize file changes at the expense of correctness. It is to keep each Codex chat bounded while ensuring that the **final Step-9 branch state**, not any intermediate checkpoint, is the authoritative ANY-522 result.

---

# Step 1 — Remove Legacy Public Billing Contracts and Neutralize Frontend Consumers

**Status:** `completed`

## Goal

Remove all reachable legacy billing/payment public contracts before deleting the runtime and persistence they depend on, while preserving a reachable provider-independent Step-3 registration/login/session/legal browser surface.

## Scope / affected code

Primary backend areas:

- `apps/api/app/main.py`;
- `apps/api/app/domains/identity/router.py`;
- `apps/api/app/domains/identity/services/account.py`;
- `apps/api/app/domains/legal/router.py` and the directly related legal service/query path;
- current billing/catalog routers and presentation models;
- directly affected API tests.

Primary frontend areas:

- old catalog consumers;
- old checkout/payment-result consumers;
- old account-subscription consumers;
- `apps/web/src/features/checkout/CheckoutClient.tsx` and its direct clients/types/tests;
- current auth routes/components that must continue exposing `AuthForm`.

## Implementation decisions

Remove these public backend contracts:

```text
GET  /api/catalog/products
POST /api/auth/checkout-intent
GET  /api/account/subscriptions
GET  /api/account/subscriptions/{subscription_id}
GET  /api/auth/payment-status
```

Preserve core:

```text
GET /api/auth/session
```

but remove:

- optional `product` selector;
- `product_state`;
- all Product/Plan/Order/Payment/Entitlement lookup behavior surrounding the retained session identity.

Preserve final Step-3 registration/login/logout/password-reset/legal contracts.

The current generic legal acceptance request still carries transitional checkout context. Remove or adapt the legacy-only request/service fields together with the deleted checkout consumers, including the current `plan_id`, entrypoint, source URL and arbitrary checkout metadata semantics. Do not remove the retained exact-version legal acceptance behavior or the canonical event-backed evidence model.

Do not delete the transitional persistence columns in this step; Step 3 owns physical ORM cleanup.

Frontend routes may remain as neutral informational/unavailable shells only if useful for navigation. They must no longer call removed billing APIs or execute a provider checkout.

Keep `/ru/auth-checkout` as the minimal retained browser authentication shell for this step: remove its provider scripts/checkout orchestration and render the final Step-3 `AuthForm` through a small provider-independent auth wrapper using the existing auth/session helpers. Do not create a new authentication architecture. This gives Step 4 one explicit reachable registration/login surface instead of leaving route ownership for the execution model to decide.

## Invariants

- canonical Step-3 auth/session/recovery/legal behavior is unchanged;
- instance tenant/region remains server-authoritative;
- core session response still returns authenticated canonical user identity;
- retained legal acceptance remains exact-version and event-backed;
- no target catalog/PurchaseIntent/account API is introduced early;
- no LBX behavior is introduced.

## Out of scope

- deleting CloudPayments/provider source;
- deleting legacy ORM models;
- target persistence;
- Alembic reset;
- target purchase/catalog/account runtime.

## AI prompt

This prompt is intended for a **fresh Codex chat**. Work from the current ANY-522 branch/worktree, which must already contain every earlier numbered step. Do not rely on prior chat memory. The canonical plan must exist at `docs/exec-plans/completed/ANY-522-implementation-plan.md`. Read only Sections 1–3 and the Step 1 section; do not reread the full plan or repeat ANY-509/ANY-510 architecture research. Inspect only the current Git state and directly relevant files needed to confirm the prerequisite checkpoint. If an earlier step is missing or the current source materially contradicts this step's fixed assumptions, stop and report the contradiction instead of implementing multiple steps or redesigning the architecture.

Implement only Step 1 of ANY-522: remove the legacy public billing/payment contracts and neutralize their frontend consumers while preserving the final merged Step-3 provider-independent authentication/session/recovery/legal surface.

The final predecessor baseline is `main` at merge commit `87dbb62301fcf25eedb86bb897bbe92e021d9886`. Do not re-research the architecture. Inspect only the directly relevant current router/service/frontend files as needed to verify these plan assumptions.

Backend outcome:

- remove `GET /api/catalog/products`;
- remove `POST /api/auth/checkout-intent`;
- remove `GET /api/account/subscriptions`;
- remove `GET /api/account/subscriptions/{subscription_id}`;
- remove `GET /api/auth/payment-status`;
- preserve core `GET /api/auth/session`, but remove its optional `product` input and billing-derived `product_state`;
- remove router composition/presentation types that exist only for the deleted contracts;
- preserve registration, login, logout, password-reset request/confirmation, required-document discovery, generic authenticated legal acceptance and bearer-session authentication.

The current generic legal acceptance request still contains checkout-era fields (`plan_id`, entrypoint context, source URL and arbitrary metadata). Remove/adapt those fields and their legacy recurring-plan/entrypoint validation only to the extent required by deletion of the old checkout flow. Preserve exact document-version/hash acceptance and canonical `LegalAcceptanceEvent` + `DocumentAcceptance` evidence. Physical removal of transitional `DocumentAcceptance` columns belongs to Step 3.

Frontend outcome:

- remove all calls to the deleted catalog, checkout, payment-status and old account-subscription APIs;
- remove reachable provider checkout execution from the old flow;
- keep `/ru/auth-checkout` as the explicit minimal auth-only shell: remove provider `<Script>` loading, adapter status and checkout orchestration, and render the existing Step-3 `AuthForm` through the smallest provider-independent wrapper needed to submit register/login and manage the bearer session;
- neutralize `/ru`, `/ru/products`, `/ru/account` and `/ru/payment-result` as needed so they make no removed billing API calls;
- do not invent a new auth architecture or target commerce UI;
- do not create target catalog, PurchaseIntent, Widget or account behavior.

Update only directly affected tests. Preserve Step-3 auth/legal survivor tests instead of changing their behavior.

Implement only this step. Follow the decisions defined in this prompt. Do not perform broad repository research. Do not redesign the architecture. Do not perform unrelated refactoring. Do not work on future steps.

Do not run tests, linters, formatters or other automated verification commands. Do not stage files. Do not create commits.

After implementation, report:

1. every changed/deleted file;
2. which public contracts were removed;
3. which provider-independent auth/legal contracts remain;
4. the surviving browser registration/login entry surface;
5. a concise handoff for the next fresh Codex chat: prerequisite state now established and any intentional deferrals;
6. the exact manual verification commands below.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
npm run test:api:fast
npm --workspace @anytoolai/web run test:components
npm run test:boundaries:web
```

## Expected completion

- removed billing endpoints are no longer mounted;
- `/api/auth/session` is identity/session-only;
- generic legal API no longer carries old checkout-plan/entrypoint authority;
- frontend code no longer calls removed billing contracts;
- provider-independent browser registration/login remains reachable and is covered by the surviving auth-only route/component tests;
- legacy provider/runtime source still exists only as cleanup input for Step 2.

## Proposed commit

```text
refactor(api): remove legacy billing public contracts
```

---

# Step 2 — Physically Remove Legacy Billing Runtime, Direct-Provider Infrastructure and CloudPayments

**Status:** `completed`

## Goal

Delete superseded runtime code after its public consumers are gone, leaving no executable direct-provider/CloudPayments path or obsolete Portal-owned commerce lifecycle.

## Scope / affected code

Expected removal/adaptation areas include:

```text
apps/api/app/domains/billing/**
apps/api/app/domains/identity/services/checkout.py
legacy billing portions of identity account services
apps/api/app/payment_providers/**
apps/api/app/integrations/cloudpayments/**
apps/api/app/cloudpayments.py
apps/api/app/commands/expire_subscriptions.py
legacy billing persistence/query helpers
apps/api/app/http_dependencies.py
apps/api/app/main.py
apps/api/app/core/settings.py
apps/api/app/core/payment_api_limits.py if no surviving consumer remains
scripts/cloudpayments_sandbox_verify.py
CloudPayments environment/config examples
legacy billing/provider tests
remaining frontend provider adapters/types
architecture-limits.json entries for deleted files
```

## Implementation decisions

Physically remove `PaymentProviderRegistry` and `PaymentProviderAdapter` runtime/composition. Do not preserve the current empty registry as a target abstraction.

Physically remove retained CloudPayments implementation source rather than leaving disabled source as a future template.

Remove Portal-owned runtime tied to:

- Product/Plan commercial catalog;
- checkout/order/payment/refund;
- subscription/entitlement/trial;
- old expiry/commercial-transition behavior.

Delete persistence/query helpers only after their surviving callers are gone.

Remove CloudPayments settings, URL validation, environment requirements, sandbox scripts and provider-only infrastructure.

Remove `app.core.payment_api_limits` only if a direct usage check confirms that no provider-independent consumer remains.

Remove obsolete architecture line-limit exceptions when their files are deleted.

In the same step, update `apps/api/tests/test_architecture.py` so deleting CloudPayments source cannot leave the fast test suite unimportable. The current file imports `CloudPaymentsAdapter` and the CloudPayments router at module scope and contains `test_retained_cloudpayments_webhook_keeps_shared_async_body_and_sync_processing_boundary`; remove that retained-implementation test and those implementation imports together with the source. Preserve/adapt only static architecture tests that prohibit forbidden CloudPayments/direct-provider dependencies or literals without importing deleted implementation modules.

Preserve generic database, HTTP, FastAPI, observability, Sentry, error, identity, recovery, legal and persistence-boundary infrastructure.

Legacy ORM classes remain temporarily for Step 3.

## Invariants

- no executable direct-provider/CloudPayments path remains;
- FastAPI composition has no payment-provider registry;
- no replacement generic billing/provider framework is introduced;
- provider-independent observability/privacy remains;
- identity/legal/recovery has no dependency on removed billing runtime.

## Out of scope

- legacy ORM deletion;
- target ORM;
- migrations;
- LBX client/runtime;
- workers/reconciliation/access delivery.

## AI prompt

This prompt is intended for a **fresh Codex chat**. Work from the current ANY-522 branch/worktree, which must already contain every earlier numbered step. Do not rely on prior chat memory. The canonical plan must exist at `docs/exec-plans/completed/ANY-522-implementation-plan.md`. Read only the Step 2 section and Section 3 locked outcome/removal boundaries; do not reread the full plan or repeat ANY-509/ANY-510 architecture research. Inspect only the current Git state and directly relevant files needed to confirm the prerequisite checkpoint. If an earlier step is missing or the current source materially contradicts this step's fixed assumptions, stop and report the contradiction instead of implementing multiple steps or redesigning the architecture.

Implement only Step 2 of ANY-522: physically remove the legacy Portal billing runtime, direct-provider infrastructure and CloudPayments implementation after Step 1 has removed their public consumers.

Do not perform broad repository research. Inspect only direct current imports/usages before deleting a file so that no surviving provider-independent caller is removed.

Remove executable code and dead support for:

- legacy Portal-owned catalog/checkout/order/payment/refund/subscription/entitlement/trial behavior;
- `app.payment_providers/**`;
- `PaymentProviderRegistry` / `PaymentProviderAdapter` DI and composition;
- `app.integrations.cloudpayments/**`;
- `app.cloudpayments.py`;
- `apps/api/app/commands/expire_subscriptions.py`;
- CloudPayments-only scripts, settings, validators, environment variables and examples;
- legacy query/persistence helpers whose only callers were deleted;
- obsolete checkout/CloudPayments/direct-provider business metrics and tests with no retained provider-independent purpose;
- remaining frontend provider adapters/types with no survivor;
- architecture line-limit exceptions referring to deleted files;
- the retained CloudPayments implementation-level architecture test and its module-scope imports from `apps/api/tests/test_architecture.py`; keep only implementation-independent prohibition/guard tests that remain valid after the source tree is deleted.

Remove `app.core.payment_api_limits` only if direct current usage confirms it has no provider-independent remaining consumer.

Adapt `app.main` and `app.http_dependencies` so the application no longer constructs, stores or resolves a payment-provider registry.

Preserve database/session infrastructure, generic FastAPI DI, provider-independent HTTP errors, request observability/privacy, Sentry, identity/session/recovery/legal runtime and still-valid architecture/persistence boundaries.

Do not modify the canonical ORM schema or Alembic history in this step. Legacy model modules may remain temporarily for Step 3.

Do not implement LBX, External Billing ports, a replacement provider registry, target workers or any later-step behavior.

Implement only this step. Follow the decisions defined in this prompt. Do not perform broad repository research. Do not redesign the architecture. Do not perform unrelated refactoring. Do not work on future steps.

Do not run tests, linters, formatters or other automated verification commands. Do not stage files. Do not create commits.

After implementation, report:

1. every changed/deleted file;
2. removed executable provider/runtime roots;
3. any helper intentionally retained because a provider-independent caller still exists;
4. a concise handoff for the next fresh Codex chat: prerequisite state now established and any intentional deferrals;
5. the exact manual verification commands below.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
npm run architecture:check
npm run test:api:fast
git grep -n -i "cloudpayments\|PaymentProviderRegistry\|PaymentProviderAdapter" -- apps/api/app apps/web/src scripts ':!docs/**'
```

The grep result may contain a narrow static prohibition/guard, but must contain no executable runtime dependency or retained implementation source.

## Expected completion

The repository contains no executable direct-provider or CloudPayments runtime while the retained provider-independent application remains functional.

## Proposed commit

```text
refactor(billing): remove direct provider runtime
```

---

# Step 3 — Reduce the Canonical ORM to the Final Step-3 Survivor Schema

**Status:** `completed`

## Goal

Make `app.models` contain only the final retained identity/session/legal/contour schema before target billing persistence is introduced.

## Scope / affected code

Primary areas:

```text
apps/api/app/models/__init__.py
apps/api/app/models/enums.py
apps/api/app/models/_shared.py
apps/api/app/models/identity.py
apps/api/app/models/legal.py
apps/api/app/models/catalog.py
apps/api/app/models/commerce.py
apps/api/app/models/providers.py
apps/api/app/models/subscriptions.py
apps/api/app/models/webhooks.py
legal service/query code touching transitional acceptance fields
focused model/architecture tests
```

## Implementation decisions

The retained ORM consists of exactly these ten tables:

```text
regions
country_region_rules
users
auth_sessions
magic_link_tokens
password_reset_rate_limits
legal_entities
document_versions
legal_acceptance_events
document_acceptances
```

Remove `entrypoint_sessions`.

Remove from `country_region_rules`:

```text
default_payment_provider
allow_region_override
```

Retain only provider-independent country/market/document configuration used by the one-contour identity/legal bootstrap.

Remove all legacy Portal commercial/provider/subscription ORM classes and billing-only enums that are not part of the retained Step-3 schema.

Reduce `DocumentAcceptance` to the exact clean subset defined in Section 4.

Preserve the full final Step-3 contract for survivor fields, alternate keys, composite FKs, checks and indexes.

Do not create target external-billing tables yet.

## Invariants

- `users.id` remains canonical Portal identity and is never reused;
- `(tenant_id, region, user_id)` remains canonical cross-boundary user scope;
- Step-3 structural scope consistency remains intact;
- password reset remains hash-only and provider-independent;
- `LegalAcceptanceEvent` purchase-compatible commercial triplet and alternate key remain;
- no `external_billing_accounts` model exists;
- no old Product/Plan/Order/Payment/Subscription/Entitlement table remains in SQLAlchemy metadata.

## Out of scope

- target billing models;
- baseline migration;
- provider-specific semantics;
- runtime for target persistence.

## AI prompt

This prompt is intended for a **fresh Codex chat**. Work from the current ANY-522 branch/worktree, which must already contain every earlier numbered step. Do not rely on prior chat memory. The canonical plan must exist at `docs/exec-plans/completed/ANY-522-implementation-plan.md`. Read only Section 4 and the Step 3 section; do not reread the full plan or repeat ANY-509/ANY-510 architecture research. Inspect only the current Git state and directly relevant files needed to confirm the prerequisite checkpoint. If an earlier step is missing or the current source materially contradicts this step's fixed assumptions, stop and report the contradiction instead of implementing multiple steps or redesigning the architecture.

Implement only Step 3 of ANY-522: reduce the canonical ORM to the final provider-independent Step-3 identity/session/recovery/legal/contour survivor schema.

Use the merged `docs/architecture/portal-identity-session-legal-baseline.md` and final merged Step-3 ORM as fixed input. Do not re-research or redesign the retained contract.

Retain exactly these tables:

- `regions`;
- `country_region_rules`;
- `users`;
- `auth_sessions`;
- `magic_link_tokens`;
- `password_reset_rate_limits`;
- `legal_entities`;
- `document_versions`;
- `legal_acceptance_events`;
- `document_acceptances`.

For every retained table, preserve the complete final Step-3 columns, types, defaults/nullability, alternate keys, composite scope FKs, indexes and checks.

Required cleanup:

- remove `entrypoint_sessions`;
- remove `country_region_rules.default_payment_provider`;
- remove `country_region_rules.allow_region_override`;
- remove legacy catalog/commerce/provider/subscription/entitlement/trial ORM classes;
- remove old billing-only persisted enums no longer used by the retained contract;
- reduce `DocumentAcceptance` to exactly:
  `id`, `legal_acceptance_event_id`, `tenant_id`, `region`, `user_id`,
  `document_version_id`, `acceptance_kind`, `acceptance_text_hash`, `created_at`;
- remove transitional guest/entrypoint/source/arbitrary metadata/legacy plan and duplicated document/action/audit fields classified for removal by the Step-3 handoff;
- adapt only directly affected retained legal query/service code to the clean physical contract.

Preserve `LegalAcceptanceEvent` including its optional all-or-none commercial triplet and purchase-binding alternate key because target `purchase_intents` will reference it.

Update `app.models.__init__` and the canonical `app.models.enums` definitions/exports to match the retained contract. Do not finalize the repository-wide persisted-enum inventory in `scripts/repo.py` here; Step 8 updates that guard once all target enums from Steps 4–6 exist.

Do not create target external-billing models yet. Do not modify Alembic history yet. Do not create compatibility models or a parallel entity hierarchy.

Implement only this step. Follow the decisions defined in this prompt. Do not perform broad repository research. Inspect only directly relevant model/legal files if needed to verify plan assumptions. Do not redesign the architecture. Do not perform unrelated refactoring. Do not work on future steps.

Do not run tests, linters, formatters or other automated verification commands. Do not stage files. Do not create commits.

After implementation, report:

1. changed/deleted files;
2. retained ORM tables;
3. removed legacy model modules/enums;
4. final `DocumentAcceptance` field set;
5. a concise handoff for the next fresh Codex chat: prerequisite state now established and any intentional deferrals;
6. the exact manual verification commands below.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
npm run test:api:fast
npm run architecture:check
```

## Expected completion

`app.models` describes only the ten final Step-3 survivor tables. Legacy commercial/payment persistence symbols are absent from canonical ORM metadata.

## Proposed commit

```text
refactor(models): retain clean identity and legal schema
```

---

# Step 4 — Add Target Projection, Mapping, Customer and Purchase Foundation Models

**Status:** `completed`

## Goal

Add the six target tables that form the provider-neutral projection/provenance/customer/purchase foundation, while keeping the intermediate SQLAlchemy metadata self-contained and executable.

## Scope / affected code

Target tables:

```text
capability_manifest_projections
external_billing_catalog_projections
commercial_mapping_revisions
external_billing_customers
purchase_intents
external_create_operations
```

Also update:

```text
apps/api/app/models/enums.py
apps/api/app/models/__init__.py
coherent new app.models modules
focused model/architecture tests
```

## Implementation decisions

Implement every field/slot and every Step-4-owned physical invariant from Section 5.1–5.6. The matching ANY-509 table sections are reference-only for exact declaration details.

Important locked rules:

- Kernel `product_id` / `metric_key` remain text identities with no Portal catalog FK;
- `external_billing_account_id` is configuration scope, not a table FK;
- one customer slot per `(external_billing_account_id, user_id)`;
- `billing_customer_key` is non-empty, globally unique, immutable and permanently non-reusable;
- provider customer ID stays nullable/opaque with no Phase-0-dependent uniqueness;
- mapping revisions retain approved composite relational targets, `revision_number > 0`, and scoped revision-number uniqueness; monotonic publication sequencing remains ANY-504 Step 6 runtime;
- PurchaseIntent binds exact customer, mapping revision, commercial fingerprint and Step-3 legal event through the approved composite FKs;
- client idempotency is unique on `(external_billing_account_id, user_id, client_idempotency_key)`;
- PurchaseIntent state is the approved closed provider-neutral vocabulary;
- create-operation kind is the approved closed provider-neutral vocabulary;
- create-operation `operation_state` remains open text;
- UNKNOWN/recovery/provider-object fields are storage only; no recovery behavior is implemented.

## Invariants

- no `external_billing_accounts` table;
- no Portal Product/Plan authority;
- no LBX status/type becomes canonical domain vocabulary;
- gated external IDs remain intentionally under-constrained;
- no application service, query, route or network call is introduced for these tables;
- normal runtime leaves all six tables empty.

## Out of scope

- `billing_product_access_scopes` and the subscription/observation FK graph — Step 5;
- paid access/outbox — Step 6;
- migrations — Step 7;
- synchronization/publication/purchase/customer/create runtime — later ANY-504 steps.

## AI prompt

This prompt is intended for a **fresh Codex chat**. Work from the current ANY-522 branch/worktree, which must already contain every earlier numbered step. Do not rely on prior chat memory. The canonical plan must exist at `docs/exec-plans/completed/ANY-522-implementation-plan.md`. Read only Sections 5.1–5.6 and the Step 4 section; do not reread the full plan or repeat ANY-509/ANY-510 architecture research. Inspect only the current Git state and directly relevant files needed to confirm the prerequisite checkpoint. If an earlier step is missing or the current source materially contradicts this step's fixed assumptions, stop and report the contradiction instead of implementing multiple steps or redesigning the architecture.

Implement only Step 4 of ANY-522: add the provider-neutral target ORM foundation for projections, immutable mapping provenance, external-billing customer slots, PurchaseIntent evidence and durable outbound-create state.

Do not perform broad repository research. Use Section 5.1–5.6 of this plan as the fixed implementation contract. Inspect only the current `app.models` structure and, if an exact SQLAlchemy/Alembic spelling or index name needs confirmation, the matching table section in `docs/architecture/external-billing-persistence-reset.md`. Do not derive new requirements from that inspection.

Implement every field/slot and every Step-4-owned physical invariant listed in Section 5.1–5.6. Create all approved later-owned/gated storage slots now, but do not add unproven provider interpretation.

Required boundaries:

- no `external_billing_accounts` table;
- Kernel product/metric identities are text and have no Portal catalog FK;
- `external_billing_account_id` is opaque configuration scope;
- one `external_billing_customers` row per `(external_billing_account_id, user_id)`;
- `billing_customer_key` is globally unique and non-empty;
- provider customer ID stays nullable/opaque without pre-Phase-0 uniqueness;
- PurchaseIntent customer/mapping/legal/commercial provenance uses the exact approved composite FKs and alternate relational keys;
- client idempotency uniqueness is exactly `(external_billing_account_id, user_id, client_idempotency_key)`;
- use only the closed provider-neutral enums explicitly fixed by ANY-509;
- keep `external_create_operations.operation_state` and other later-owned open vocabularies as text without speculative checks;
- do not implement create/recovery transitions.

Keep canonical ORM ownership under `app.models`. Split new model files by coherent persistence responsibility only as needed to follow current repository line limits. Do not create repositories-per-table, a generic Unit of Work or a parallel pure-domain entity graph.

Do not add migrations, services, queries, APIs, network clients or seed data for these tables.

Implement only this step. Follow the decisions defined in this prompt. Do not perform broad repository research. Do not redesign the architecture. Do not perform unrelated refactoring. Do not work on future steps.

Do not run tests, linters, formatters or other automated verification commands. Do not stage files. Do not create commits.

After implementation, report:

1. changed files;
2. all six created table models;
3. every new closed enum;
4. fields/vocabularies deliberately left opaque/open/gated;
5. a concise handoff for the next fresh Codex chat: prerequisite state now established and any intentional deferrals;
6. the exact manual verification commands below.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
npm run test:api:fast
npm run architecture:check
```

## Expected completion

The six foundation tables are present in SQLAlchemy metadata with the complete approved physical shape and no runtime behavior or unresolved FK target to a future step.

## Proposed commit

```text
feat(persistence): add billing foundation models
```

---

# Step 5 — Add the Target Subscription, Observation and Reconciliation Persistence Graph

**Status:** `completed`

## Goal

Add the complete interconnected persistence graph required for product-scope serialization, external-subscription projection, normalized observations, purchased allowances and durable reconciliation evidence/work.

## Scope / affected code

Target tables added together in this step:

```text
billing_product_access_scopes
external_subscriptions
billing_state_observations
purchased_allowances
external_billing_webhook_deliveries
billing_work_items
manual_review_cases
```

Also update target enums, exports and focused ORM/architecture tests.

## Implementation decisions

Implement the fixed Section 5.7–5.13 physical contract for all seven tables in one step because the first four form one FK graph and observations also reference the durable work table.

Critical rules include:

- unique `(user_id, product_id)` serialization scope;
- composite primary-subscription reference from access scope;
- external subscription customer/purchase/mapping provenance FKs;
- external subscription opaque external IDs remain nullable with no Phase-0 uniqueness;
- only approved closed provider-neutral lifecycle/financial/commercial statuses become enums;
- reconciliation lease owner/expiry pair is structurally checked;
- fencing token physical shape is retained;
- `latest_observation_id` uses the approved same-subscription composite FK but observation-kind causality remains later runtime behavior;
- observation kind is the approved closed provider-neutral vocabulary;
- observation row-shape, scope consistency and contradictory subscription/direct-purchase checks are implemented now;
- completeness/result classifications remain open text;
- purchased allowance quantity is non-negative;
- raw provider cycle start/end use the approved paired nullable shape and no Phase-0-gated uniqueness;
- effective period is structurally valid and frozen storage contains no runtime `remaining`;
- webhook inbox stores bounded/redacted evidence shape, not raw payment ledger data;
- work kind/state remain open vocabularies; the approved lease pair and Step-4-safe structural constraints are installed;
- manual-review reason/scope/state remain open later-owned vocabularies.

## Invariants

- every FK target required by this step exists by the end of the same commit;
- no provider-specific subscription identity is promoted before Phase 0;
- no raw provider/payment ledger is introduced;
- no worker, reconciliation or access behavior is implemented;
- all seven tables remain empty in normal Step-4 runtime.

## Out of scope

- paid-access current state/outbox — Step 6;
- migration DDL — Step 7;
- discovery/reconciliation/webhook workers — Step 8 of ANY-504;
- allowance materialization/access derivation — Step 9 of ANY-504.

## AI prompt

This prompt is intended for a **fresh Codex chat**. Work from the current ANY-522 branch/worktree, which must already contain every earlier numbered step. Do not rely on prior chat memory. The canonical plan must exist at `docs/exec-plans/completed/ANY-522-implementation-plan.md`. Read only Sections 5.7–5.13 and 5.17 plus the Step 5 section; do not reread the full plan or repeat ANY-509/ANY-510 architecture research. Inspect only the current Git state and directly relevant files needed to confirm the prerequisite checkpoint. If an earlier step is missing or the current source materially contradicts this step's fixed assumptions, stop and report the contradiction instead of implementing multiple steps or redesigning the architecture.

Implement only Step 5 of ANY-522: add the complete target ORM graph for product access scopes, external subscription projection, normalized observation evidence, purchased allowances, webhook evidence, durable reconciliation work and manual-review evidence.

Do not perform broad repository research. Use Section 5.7–5.13 of this plan as the fixed implementation contract. Inspect only directly relevant target-model files and, when an exact declaration/index name needs confirmation, the matching handoff section. Do not derive or redesign requirements from that inspection.

Implement all seven in this step because the approved schema contains cross-table references between access scopes, subscriptions and observations, and observations reference the work table. The completed commit must leave SQLAlchemy metadata with all FK targets resolvable.

Implement every field/slot and every `STEP_4_SAFE` key, composite FK, uniqueness rule, partial index, index, check and narrative physical requirement from the authoritative table sections. Create later-owned/gated storage slots but do not implement later behavior.

Required boundaries:

- one access scope per `(user_id, product_id)`;
- preserve the composite `primary_subscription_id` reference exactly;
- preserve external-subscription customer/purchase/mapping provenance FKs and approved alternate keys;
- external subscription/agreement/provider identifiers remain nullable opaque fields with no pre-Phase-0 uniqueness;
- use only the approved provider-neutral closed lifecycle/financial/commercial enums;
- preserve reconciliation lease owner/expiry paired-nullability and fencing-token storage;
- preserve `latest_observation_id` same-subscription FK without attempting to encode observation-kind causality in a duplicate discriminator;
- use the approved closed observation-kind enum;
- implement the Step-4 observation row-shape and scope/provenance checks, including prohibition of contradictory direct purchase + subscription provenance;
- keep completeness/result classifications as open text;
- purchased allowance `quantity >= 0`;
- provider cycle identity remains opaque/gated and receives no logical uniqueness before Phase 0;
- raw provider cycle bounds follow the approved paired nullable shape;
- effective `period_start < period_end` and there is no persisted runtime `remaining`;
- webhook evidence remains bounded/redacted and does not store raw payment history/secrets;
- work kind/state and manual-review reason/scope/state remain open later-owned vocabularies;
- install only the approved Step-4-safe work lease/scheduling and review evidence shape.

Use repository-standard SQLAlchemy string/composite FK declarations so all cyclic targets resolve within this same metadata step. This is ORM declaration mechanics only; do not weaken or omit any FK, and do not invent a different schema split. The clean Alembic two-phase creation order is fixed separately by Section 5.17.

Do not add services, queries, workers, provider calls, webhook processing, reconciliation, allowance derivation or access runtime. Do not add migrations yet.

Implement only this step. Follow the decisions defined in this prompt. Do not perform broad repository research. Do not redesign the architecture. Do not perform unrelated refactoring. Do not work on future steps.

Do not run tests, linters, formatters or other automated verification commands. Do not stage files. Do not create commits.

After implementation, report:

1. changed files;
2. all seven created tables;
3. closed versus intentionally open vocabularies;
4. every provider-specific constraint intentionally deferred;
5. confirmation that all new FK targets resolve within current metadata;
6. a concise handoff for the next fresh Codex chat: prerequisite state now established and any intentional deferrals;
7. the exact manual verification commands below.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
npm run test:api:fast
npm run architecture:check
```

## Expected completion

The complete subscription/observation/reconciliation persistence graph exists with all approved Step-4-safe physical constraints, no unresolved metadata references and no runtime behavior.

## Proposed commit

```text
feat(persistence): add billing reconciliation models
```

---

# Step 6 — Add Provider-Neutral Paid Access State and Invalidation Outbox Models

**Status:** `completed`

## Goal

Complete the 15-table target ORM baseline with the provider-neutral current paid-access state and coalesced invalidation outbox storage required by later Portal↔Kernel work.

## Scope / affected code

Target tables:

```text
paid_access_states
access_invalidation_outbox
```

Also update model exports and focused ORM/architecture tests.

## Implementation decisions

Implement the fixed Section 5.14–5.15 physical contract for both tables.

Critical rules:

- both use explicit, non-null `tenant_id`, `region`, `user_id`;
- both use the same composite restrictive FK to `users(id, tenant_id, region)`;
- both are unique per `(tenant_id, region, user_id)`;
- `paid_access_states.access_revision` is non-null storage; absence of a row represents implicit revision zero, while positive/monotonic revision validation remains ANY-504 Step 9 runtime;
- effective-state schema/document/commit fields exist physically but runtime semantics remain ANY-504 Step 9;
- outbox `pending_revision > 0` and `pending_revision >= delivered_revision` are Step-4-safe structural checks;
- `delivered_revision` and `attempt_count` retain non-null/default-`0` storage, while their non-negative transition validation remains ANY-504 Step 10 runtime;
- no revision-zero outbox row is representable;
- no delivery/runtime behavior is implemented.

## Invariants

- target ORM table count reaches exactly 15 target tables plus the ten survivors;
- current access state contains no provider IDs/statuses;
- Portal does not persist Kernel runtime remaining quota;
- no read path creates revision zero state;
- no invalidation worker/transport is implemented.

## Out of scope

- semantic access derivation;
- access revision writer;
- invalidation production/delivery;
- Portal↔Kernel API/transport.

## AI prompt

This prompt is intended for a **fresh Codex chat**. Work from the current ANY-522 branch/worktree, which must already contain every earlier numbered step. Do not rely on prior chat memory. The canonical plan must exist at `docs/exec-plans/completed/ANY-522-implementation-plan.md`. Read only Sections 5.14–5.15 plus the Step 6 section; do not reread the full plan or repeat ANY-509/ANY-510 architecture research. Inspect only the current Git state and directly relevant files needed to confirm the prerequisite checkpoint. If an earlier step is missing or the current source materially contradicts this step's fixed assumptions, stop and report the contradiction instead of implementing multiple steps or redesigning the architecture.

Implement only Step 6 of ANY-522: add the final provider-neutral target ORM tables `paid_access_states` and `access_invalidation_outbox`.

Do not perform broad repository research. Use Section 5.14–5.15 of this plan plus the final Step-3 user-scope contract in Section 4 as fixed implementation input. Open the authoritative handoff only to confirm an exact declaration/index name, not to derive new requirements.

Implement every approved field/slot and every `STEP_4_SAFE` physical invariant for both tables.

Required contract:

- explicit non-null `tenant_id`, `region`, `user_id` on both tables;
- composite FK `(user_id, tenant_id, region) -> users(id, tenant_id, region) ON DELETE RESTRICT`;
- `UNIQUE(tenant_id, region, user_id)` on both;
- keep `paid_access_states.access_revision` non-null, but do not add a Step-4 positivity/monotonicity CHECK; ANY-504 Step 9 owns revision semantics;
- absence of a state row remains implicit revision zero and must not be materialized by Step 4;
- retain the approved effective-state schema/document and commit timestamp fields without implementing semantic access writes or non-empty document-schema validation;
- enforce `access_invalidation_outbox.pending_revision > 0`;
- enforce `pending_revision >= delivered_revision`;
- keep `delivered_revision` and `attempt_count` non-null with default `0`, but do not add their later-owned non-negative transition CHECKs in Step 4;
- preserve the approved due/retry/error/timestamp slots;
- do not allow an outbox row for revision zero.

Do not add provider IDs/statuses to the paid-access document contract and do not persist runtime remaining quota.

Do not add access derivation, revision production, invalidation delivery, Portal↔Kernel transport, queries/services or migrations in this step.

Implement only this step. Follow the decisions defined in this prompt. Do not perform broad repository research. Do not redesign the architecture. Do not perform unrelated refactoring. Do not work on future steps.

Do not run tests, linters, formatters or other automated verification commands. Do not stage files. Do not create commits.

After implementation, report:

1. changed files;
2. both created models;
3. final application metadata table count;
4. revision-zero protections;
5. a concise handoff for the next fresh Codex chat: prerequisite state now established and any intentional deferrals;
6. the exact manual verification commands below.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
npm run test:api:fast
npm run architecture:check
```

## Expected completion

SQLAlchemy metadata contains exactly the ten retained Step-3 tables plus all fifteen approved target tables, with no legacy table and no target runtime behavior.

## Proposed commit

```text
feat(persistence): add paid access state models
```

---

# Step 7 — Replace the Complete Alembic History with One Clean First-Install Baseline

**Status:** `completed`

## Goal

Make a fresh PostgreSQL installation create exactly the final 25-table schema, final Step-3 legal protections and contour/legal bootstrap from one new baseline revision and one head.

## Scope / affected code

Primary areas:

```text
apps/api/alembic/versions/**
apps/api/tests/test_alembic_postgres.py
focused target-persistence PostgreSQL tests if needed for reviewability
legal/contour bootstrap code where required
migration-related test support
scripts/repo.py (only the migration/legal-version source that would otherwise point at the deleted baseline)
apps/api/tests/test_repository_docs.py (only focused coverage for that source change, if needed)
```

## Implementation decisions

The clean-reset / recreate-only premise is already approved by ANY-509 / ANY-504 and is an authoritative input to this step. Do not redesign an upgrade bridge, data backfill or compatibility path. If the current repository itself contains a material preservation/cutover obligation that directly contradicts this approved premise, stop and report that repository contradiction.

Delete the complete pre-reset migration history present at execution time, including the Step-3 transitional revisions.

Create one first-install revision that contains:

- all ten final survivor tables;
- all fifteen target tables;
- every ORM-representable and migration-only `STEP_4_SAFE` physical invariant;
- all required Step-3 PostgreSQL legal trigger/function semantics;
- the exact approved indexes, composite keys/FKs and checks;
- no provider-specific rule left gated by ANY-509 / ANY-504 Step 5.

This is not an upgrade bridge from the discarded schema.

Bootstrap only configured-contour/legal state:

- no accidental `eu`/DE/ES rows in an RU data plane;
- no Product/Plan/Bundle/provider-account seeds;
- all target external-billing tables start empty.

Rewrite old migration/schema tests around the clean target rather than preserving revision-chain/catalog assertions.

In the same commit, update only the minimal `scripts/repo.py` migration/legal-version source that would otherwise keep referencing the deleted `20260707_0001_foundation_identity_legal_provider.py`. Point it at the actual new canonical first-install baseline; do not leave the harness referencing a file deleted by this step. Broader enum/provider/docs guard cleanup remains Step 8.

The PostgreSQL verification must cover every Step-4-owned physical invariant from Section 5, not only a sample, including the focused DDL immutability assignment in Section 5.16.

For the cyclic access-scope/subscription/observation graph, implement the exact two-phase Alembic order from Section 5.17. Create the columns immediately, defer only the two cycle-closing composite FKs until both referenced tables exist, then add those FKs explicitly. Downgrade must drop those cycle-closing FKs before dropping the referenced tables. The final upgraded schema must contain the complete FK graph; no FK may be omitted as a workaround.

## Invariants

- exactly one Alembic revision/head;
- exactly 25 application tables after a fresh upgrade;
- no legacy commercial/provider table;
- no `external_billing_accounts` table;
- target tables empty after bootstrap;
- no compatibility migration from old stamps;
- legal evidence protections are preserved exactly.

## Out of scope

- data migration from discarded billing schema;
- target runtime population;
- provider behavior;
- later application concurrency/state-transition tests.

## AI prompt

This prompt is intended for a **fresh Codex chat**. Work from the current ANY-522 branch/worktree, which must already contain every earlier numbered step. Do not rely on prior chat memory. The canonical plan must exist at `docs/exec-plans/completed/ANY-522-implementation-plan.md`. Read only Sections 4, 5.1–5.17 and the Step 7 section; do not reread the full plan or repeat ANY-509/ANY-510 architecture research. Inspect only the current Git state and directly relevant files needed to confirm the prerequisite checkpoint. If an earlier step is missing or the current source materially contradicts this step's fixed assumptions, stop and report the contradiction instead of implementing multiple steps or redesigning the architecture.

Implement only Step 7 of ANY-522: replace the complete pre-reset Alembic history with one clean first-install baseline and implement the Step-4-owned PostgreSQL schema verification.

Treat the clean-reset / recreate-only premise as an approved ANY-504 / ANY-509 input. Do not require a separate external gate confirmation. Stop only if the current repository or task context contains concrete evidence of a production-data, active-client, retention or cutover obligation that materially contradicts that approved premise.

Delete the complete Alembic revision history currently present under `apps/api/alembic/versions/` and create one new first-install revision with one head.

The new baseline must create exactly:

- the ten final Step-3 survivor application tables;
- the fifteen approved ANY-509 target tables.

Use Sections 4–5 of this plan as the fixed implementation contract. Inspect the current ORM and authoritative handoff only to confirm exact generated DDL/index/constraint naming when necessary. Do not re-research or redesign tables.

For retained Step-3 persistence:

- reproduce final columns, defaults/nullability, alternate keys, composite FKs, checks and indexes;
- recreate PostgreSQL legal protections equivalent to:
  - immutable `legal_acceptance_events` core with `ip`/`user_agent` clear-only behavior;
  - unconditional UPDATE/DELETE rejection for `document_acceptances`;
  - immutable material `document_versions` while allowing the intended active-version lifecycle selector.

For all fifteen target tables:

- create every approved physical field/slot, including later-owned and Phase-0-gated storage slots;
- create every Step-4-owned FK, uniqueness rule, partial index, index, check and focused immutability protection listed in Section 5;
- for the cycle, follow Section 5.17 exactly: create `billing_product_access_scopes.primary_subscription_id` and `external_subscriptions.latest_observation_id` with their columns present, add all non-cyclic constraints immediately, create `billing_state_observations`, then add the two cycle-closing composite FKs explicitly; reverse that order in downgrade;
- do not add provider-specific uniqueness/identity/interpretation left gated by ANY-504 Step 5;
- keep open later-owned vocabularies open where specified.

Bootstrap only configured local contour and canonical legal data required by the final Step-3 contract.

Do not seed any Portal-owned product/plan/bundle/provider account or any target billing projection, mapping, customer, purchase, subscription, observation, allowance, access, work, outbox or review row.

Rewrite `apps/api/tests/test_alembic_postgres.py` instead of retaining old migration-chain/catalog-schema expectations. Add a separate focused target-persistence PostgreSQL test module if necessary to keep the complete negative-constraint matrix reviewable.

The Step-4 DDL verification must trace every Step-4-owned physical invariant from Section 5. At minimum the resulting suite must prove:

- fresh upgrade to the sole head;
- exact 25-table application set;
- no legacy tables;
- configured-contour/legal bootstrap and no obsolete foreign contour seeds;
- target tables empty;
- retained Step-3 user/legal composite scope integrity;
- customer-slot uniqueness and globally unique `billing_customer_key`;
- PurchaseIntent idempotency and customer/mapping/legal provenance constraints;
- external-create structural/UNKNOWN storage constraints owned by Step 4;
- access-scope/subscription/observation composite FK mismatch rejection;
- observation row-shape and contradictory provenance rejection;
- allowance quantity/period/provider-cycle-pair structural checks;
- subscription and work-item lease-pair checks;
- paid-access/outbox canonical-user scope, outbox `pending_revision > 0`, and `pending_revision >= delivered_revision` Step-4 checks;
- Step-3 legal immutability/append-only triggers;
- target DDL immutability protections assigned in Section 5.16;
- PostgreSQL uniqueness under concurrent inserts for the Step-4-owned physical identities: two concurrent attempts cannot commit two customer slots for the same `(external_billing_account_id, user_id)`, cannot commit the same `billing_customer_key` to two slots even across different account scopes, cannot commit two `billing_product_access_scopes` rows for the same `(user_id, product_id)`, cannot commit two unresolved `customer` create-operation rows for the same customer, and cannot commit two PurchaseIntent rows with the same `(external_billing_account_id, user_id, client_idempotency_key)`.

These are database-concurrency proofs of the Step-4 DDL only. Do **not** implement or test the later application protocols here: no customer-key allocation/retry algorithm, no acquire/get-and-lock purchase workflow, no replay comparison, no external-call permission logic, no worker claiming, and no paid-access transition serialization.

Do not fake provider/runtime behavior from ANY-504 Steps 5–10.

Do not create an upgrade/stamp bridge for databases on the discarded history. They are recreate-only.

Implement only this step. Follow the decisions defined in this prompt. Do not perform broad repository research. Inspect only migration/bootstrap/test files necessary to implement the fixed contract. Do not redesign the architecture. Do not perform unrelated refactoring. Do not work on future steps.

Do not run tests, linters, formatters or other automated verification commands. Do not stage files. Do not create commits.

After implementation, report:

1. all deleted/new migration files;
2. the new revision/head;
3. expected application table count and names;
4. bootstrap contents;
5. the PostgreSQL negative-constraint/immutability matrix;
6. the new `scripts/repo.py` canonical-baseline reference;
7. a concise handoff for the next fresh Codex chat: clean-baseline state now established and any intentional deferrals;
8. the exact manual verification commands below.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
npm run test:api:postgres
npm run test:api:fast
```

## Expected completion

A fresh PostgreSQL database reaches one clean Alembic head and contains only the final ten survivor tables plus the empty fifteen-table target model with all Step-4-safe physical invariants enforced.

## Proposed commit

```text
refactor(db): replace legacy history with clean baseline
```

---

# Step 8 — Align Repository Harness, Architecture Guards and Current-State Documentation

**Status:** `completed`

## Goal

Make repository tooling, architecture guards and operational/current-state documentation treat the new clean baseline as the current system rather than the discarded migration/direct-provider architecture.

## Scope / affected code

Expected areas:

```text
scripts/repo.py
apps/api/tests/test_repository_docs.py
apps/api/tests/test_architecture.py
apps/api/tests/test_deployment_contract.py
architecture-limits.json
.env examples / compose / CI if stale references remain
docs/architecture/payment-portal-data-model.md
docs/architecture/payment-providers.md
docs/product/ru-mvp.md
ARCHITECTURE.md
docs/PRODUCT.md
docs/RELIABILITY.md
README.md
deployment/reset documentation where the compatibility contract belongs
```

## Implementation decisions

Finish repository-harness assumptions tied to:

- the old persisted billing enum inventory;
- CloudPayments environment stripping or required provider config;
- direct-provider source being retained implementation;
- old catalog/provider/subscription table inventory;
- old lifecycle command paths.

Step 7 already moved the migration/legal-version source to the actual clean baseline so no commit references a deleted migration file. Step 8 may refactor that focused mechanism only if needed for maintainability, but must not move authority away from the clean baseline.

Preserve the ADR 0005 / external-billing documentation authority precedence guard.

Update architecture/static guards so removed executable architecture cannot return, while not requiring deleted source files to exist merely as evidence.

Rewrite `docs/architecture/payment-portal-data-model.md` as the current as-built 25-table schema reference.

Reclassify `docs/architecture/payment-providers.md` consistently with physical direct-provider removal.

Update only current-state/operational claims invalidated by Step 4; keep historical/superseded ADRs and plans as history.

Document the destructive reset compatibility/recovery contract:

- pre-Step-4 binaries never run against the Step-4 DB;
- old-stamped databases are recreate-only;
- image-only rollback across the reset is forbidden;
- rollback/recovery restores a matching application + database baseline;
- reset/bootstrap failure blocks rollout.

Add an explicit **one-time dev/test/pre-production recreate/bootstrap runbook** using the repository's existing harness/deployment mechanisms rather than inventing a second reset system.

For the repository-managed local dev/test harness, use the existing commands exactly:

```bash
# Obtain the current harness worktree_id from .harness/runtime.json or the JSON
# previously printed by `python scripts/repo.py up`.
python scripts/repo.py reset --confirm <worktree_id>
python scripts/repo.py test-db up
python scripts/repo.py migrate-api
```

`reset` already executes the harness-scoped Compose `down --volumes --remove-orphans`, so it is the supported destructive local database reset. `test-db up` starts only PostgreSQL. `migrate-api` runs `alembic upgrade head` against that harness database. The new Step-7 first-install migration itself owns configured-contour/legal bootstrap, so **do not invent a separate bootstrap CLI**.

After the pre-start schema/bootstrap verification succeeds, start the matching Step-4 stack with:

```bash
python scripts/repo.py up --reuse
```

The Compose `migrate` service runs the same `alembic upgrade head` before API startup, and the API's existing legal seed remains an idempotent/fail-closed runtime check of the canonical legal material rather than a second schema authority.

The runbook sequence is therefore:

1. identify the Step-4 application revision/image and target environment; record the pre-reset application/database pairing;
2. stop every pre-Step-4 API/web/worker/scheduler process that can access the database and verify it cannot restart against the clean DB;
3. for the local harness, run `python scripts/repo.py reset --confirm <worktree_id>`; for shared dev/test/pre-production, use that environment's canonical database destroy/recreate operation — never `alembic stamp`, downgrade, or an upgrade bridge from the discarded history;
4. for the local harness, run `python scripts/repo.py test-db up` and then `python scripts/repo.py migrate-api`; this applies the sole clean head and the migration-owned configured-contour/legal bootstrap to an empty database;
5. before starting normal runtime, verify one Alembic head/current revision, exactly 25 application tables, absence of every legacy table, emptiness of all 15 target billing tables, configured-contour-only region/country state, and expected legal bootstrap rows using the Step-7 PostgreSQL verification described in this plan;
6. start only the matching Step-4 runtime (`python scripts/repo.py up --reuse` for the local harness) and run retained provider-independent registration/login/session/recovery/legal smoke checks;
7. on any reset/bootstrap/schema/smoke failure, block rollout. Recovery is recreate/restore of a matching application+database pair; never roll back only the image while keeping the Step-4 database.

The repository currently has no authoritative command for platform-specific shared pre-production process stop/database recreation. Document those operations as environment/operator prerequisites rather than fabricating commands. If deployment tooling later gains an authoritative command, reference that command instead of adding a second reset mechanism.

## Invariants

- ADR 0005 / design authority remains unchanged;
- docs checker still verifies every implemented SQLAlchemy table is documented;
- tooling no longer depends on CloudPayments/legacy schema;
- no historical source is promoted back into target authority.

## Out of scope

- generated DB/OpenAPI artifact regeneration — Step 9;
- provider integration/runtime;
- Step-11 final architecture consolidation.

## AI prompt

This prompt is intended for a **fresh Codex chat**. Work from the current ANY-522 branch/worktree, which must already contain every earlier numbered step. Do not rely on prior chat memory. The canonical plan must exist at `docs/exec-plans/completed/ANY-522-implementation-plan.md`. Read only Sections 3, 5.18–5.19 and the Step 8 section; do not reread the full plan or repeat ANY-509/ANY-510 architecture research. Inspect only the current Git state and directly relevant files needed to confirm the prerequisite checkpoint. If an earlier step is missing or the current source materially contradicts this step's fixed assumptions, stop and report the contradiction instead of implementing multiple steps or redesigning the architecture.

Implement only Step 8 of ANY-522: align repository tooling, architecture guards and current-state/reset documentation with the clean Step-4 schema and physical removal of the direct-provider architecture.

Do not perform broad repository research. Inspect only the repository harness, guard tests and current-state/operational documents directly affected by Steps 1–7.

Update `scripts/repo.py` and its focused tests so the broader harness no longer assumes:

- old billing persisted enums still exist;
- CloudPayments environment variables must be stripped or supported;
- `PaymentProviderRegistry` / adapter source remains current implementation;
- old catalog/provider/subscription tables are canonical metadata;
- removed lifecycle/provider scripts exist.

Preserve the Step-7 canonical clean-baseline source used by legal-version validation; do not recreate a second migration authority.

Preserve:

- canonical model ownership checks;
- still-valid Application/Presentation/Persistence dependency boundaries;
- ADR 0005 / external-billing documentation precedence;
- documentation coverage requiring every implemented SQLAlchemy metadata table to appear in the canonical data-model document.

Update architecture/static guards so they prevent reintroduction of executable:

- CloudPayments runtime;
- generic/direct payment-provider runtime as the External Billing boundary;
- legacy Portal Product/Plan/Order/Payment/Subscription/Entitlement/trial coupling;
- `external_billing_accounts`.

Do not make those guards require deleted implementation files to exist.

Rewrite `docs/architecture/payment-portal-data-model.md` as the current as-built clean schema reference for the ten retained and fifteen target tables.

Reclassify `docs/architecture/payment-providers.md` consistently with physical direct-provider removal.

Update `docs/product/ru-mvp.md`, `ARCHITECTURE.md`, `docs/PRODUCT.md`, `docs/RELIABILITY.md`, `README.md`, deployment docs and environment/CI examples only where the Step-4 changes make a current-state or operational statement false.

Retain historical/superseded ADRs and implementation plans as history.

Document the reset compatibility/recovery contract:

- pre-Step-4 application binaries must never run against the clean Step-4 database;
- databases stamped with discarded migration history are recreated, not upgraded/stamped through a compatibility bridge;
- image-only rollback across the reset is forbidden;
- rollback/recovery restores matching application and database state;
- reset/bootstrap failure blocks rollout.

Also add the executable one-time recreate/bootstrap runbook required by this plan. For the repository-managed local harness, record the exact supported sequence `python scripts/repo.py reset --confirm <worktree_id>` -> `python scripts/repo.py test-db up` -> `python scripts/repo.py migrate-api` -> Step-7 schema/bootstrap verification -> `python scripts/repo.py up --reuse`. State explicitly that the clean baseline migration owns configured-contour/legal bootstrap and that no separate bootstrap CLI should be invented. The runbook must still cover stop old DB consumers -> recreate the old-stamped database -> apply the new sole head/bootstrap from the matching Step-4 build -> verify one head, exact 25 tables, zero legacy tables, empty 15 target tables, configured-contour/legal bootstrap -> start matching runtime -> provider-independent auth/legal smoke. State the failure/recovery path explicitly: rollout remains blocked and recovery restores/recreates a matching application+database pair, never an image-only rollback. For shared pre-production stop/recreate operations, document operator/environment prerequisites unless an authoritative deployment command actually exists.

Do not regenerate generated DB/OpenAPI artifacts in this step; Step 9 owns final generation after source/docs/guards stabilize.

Implement only this step. Follow the decisions defined in this prompt. Do not perform broad repository research. Do not redesign the architecture. Do not perform unrelated refactoring. Do not work on future steps.

Do not run tests, linters, formatters, generators or other automated verification commands. Do not stage files. Do not create commits.

After implementation, report:

1. changed files;
2. removed harness assumptions;
3. new/revised architecture guards;
4. where the reset/recovery contract is documented;
5. a concise handoff for the next fresh Codex chat: prerequisite state now established and any intentional deferrals;
6. the exact manual verification commands below.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
npm run architecture:check
npm run docs:check
npm run test:api:fast
```

## Expected completion

Repository tooling, architecture guards and current-state documentation all describe and enforce the clean 25-table Step-4 baseline without depending on removed direct-provider/CloudPayments implementation.

## Proposed commit

```text
chore(repo): align clean persistence guards
```

---

# Step 9 — Regenerate Contracts and Perform Final Step-4 Verification

**Status:** `completed`

## Goal

Regenerate repository-owned DB/OpenAPI artifacts from the final source state, close any remaining Step-4-specific executable residue, and prove the complete ticket with the repository's normal verification suite. This is the first and only canonical CI/merge-ready boundary of the sequential implementation; Steps 1–8 are branch-local checkpoints under Section 5.18.

## Scope / affected code

Generated artifacts:

```text
docs/generated/db-schema.md
docs/generated/openapi.json
```

Potential narrow final guard/test changes are allowed only if generation/residue inspection exposes a Step-4-owned mismatch.

## Implementation decisions

Run the existing generation mechanism as an implementation action:

```bash
npm run generate
```

Never hand-edit generated DB/OpenAPI files.

Final OpenAPI must not contain removed billing APIs or session product-state contract.

Final generated DB schema must contain the clean 25-table application model.

Perform a targeted residue check for executable/current-state references to:

- CloudPayments;
- `PaymentProviderRegistry` / `PaymentProviderAdapter`;
- `entrypoint_sessions`;
- legacy Portal Product/Plan/Order/Payment/Refund/Subscription/Entitlement/trial ORM/runtime;
- removed billing endpoints/frontend calls;
- discarded migration filenames as current authority.

Historical/superseded docs may retain historical references where clearly classified as history.

Do not textually purge generic words such as "payment" or historical evidence merely because the old implementation is gone.

## Invariants

- generated artifacts are derived only from repository tooling;
- removed APIs cannot reappear in OpenAPI;
- legacy tables cannot reappear in generated DB schema;
- no later-step runtime is introduced;
- full backend/frontend/PostgreSQL/docs/architecture/generated checks pass.

## Out of scope

- LBX Phase 0;
- provider integration/runtime;
- target persistence behavior;
- cross-repository Step-11 E2E/launch consolidation.

## AI prompt

This prompt is intended for a **fresh Codex chat**. Work from the current ANY-522 branch/worktree, which must already contain every earlier numbered step. Do not rely on prior chat memory. The canonical plan must exist at `docs/exec-plans/completed/ANY-522-implementation-plan.md`. Read only Sections 3, 5.18–5.19 and the Step 9 section; do not reread the full plan or repeat ANY-509/ANY-510 architecture research. Inspect only the current Git state and directly relevant files needed to confirm the prerequisite checkpoint. If an earlier step is missing or the current source materially contradicts this step's fixed assumptions, stop and report the contradiction instead of implementing multiple steps or redesigning the architecture.

Implement only Step 9 of ANY-522: regenerate the final database/OpenAPI artifacts from the clean Step-4 source state and close only Step-4-owned executable residue exposed by that generation.

Do not perform broad repository research.

Run only this generation command as an implementation action:

```bash
npm run generate
```

Do not run `generate --check`, tests, linters, formatters or any other verification command.

Do not hand-edit:

- `docs/generated/db-schema.md`;
- `docs/generated/openapi.json`.

The generated DB schema must reflect exactly the final ten retained plus fifteen target application tables and no legacy Portal catalog/order/payment/subscription/entitlement/provider table.

The generated OpenAPI must preserve provider-independent Step-3 registration/login/logout/session/recovery/legal contracts and must not contain:

- legacy catalog endpoint;
- checkout-intent endpoint;
- payment-status endpoint;
- account-subscription endpoints;
- session `product` selector or `product_state`.

Perform only a targeted current-source/config/generated-contract residue inspection for:

- CloudPayments;
- `PaymentProviderRegistry`;
- `PaymentProviderAdapter`;
- removed provider DI/composition;
- removed legacy table/model imports;
- removed billing frontend calls;
- discarded migration filenames used as current authority.

If one narrow missing static guard would allow a removed executable architecture to return unnoticed, add only the smallest Step-4-specific regression necessary. Do not add speculative future-architecture checks.

Historical/superseded documentation may retain historical references when clearly classified as history.

Do not implement any ANY-504 Step-5–11 behavior.

Implement only this step. Follow the decisions defined in this prompt. Do not perform broad repository research. Do not redesign the architecture. Do not perform unrelated refactoring. Do not work on future steps.

Do not stage files. Do not create commits.

After implementation, report:

1. changed/generated files;
2. final residue-check findings;
3. any narrow final guard added;
4. a concise handoff for the next fresh Codex chat: prerequisite state now established and any intentional deferrals;
5. the exact manual verification commands below.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
npm run generate:check
npm run check
```

When the normal local harness stack is available and browser coverage is required for the retained neutral routes/auth surface:

```bash
npm run test:e2e
```

## Expected completion

- generated DB schema and OpenAPI match final source;
- complete repository verification passes;
- no executable/config/generated current-state dependency on the removed architecture remains;
- repository is ready for ANY-504 Step 5 without ANY-504 Step 5 repairing Step-4 persistence/runtime residue.

## Proposed commit

```text
chore(generated): refresh clean schema contracts
```

---

## 6. Final execution sequence

```text
Step 1 — public API/frontend consumer removal
    ↓
Step 2 — runtime/provider/CloudPayments physical removal
    ↓
Step 3 — final survivor ORM cleanup
    ↓
Step 4 — projection/mapping/customer/purchase foundation ORM
    ↓
Step 5 — access-scope/subscription/observation/reconciliation ORM graph
    ↓
Step 6 — paid-access state + invalidation outbox ORM
    ↓
Step 7 — destructive clean Alembic baseline + PostgreSQL schema proofs + minimal migration-source harness update
    ↓
Step 8 — broader harness/guards/docs/reset contract
    ↓
Step 9 — generated artifacts + full manual verification
```

This ordering ensures that:

- execution follows the current ANY-504 sequence and completed predecessor state;
- the approved clean-reset / recreate-only contract remains unchanged through the implementation;
- public consumers disappear before persistence/runtime they need is deleted;
- provider/runtime source disappears before canonical ORM is rebuilt;
- target ORM is complete before the fresh baseline is authored;
- FK cycles are introduced in one coherent metadata step;
- the approved pre-production recreate-only premise is treated as a fixed predecessor decision rather than redesigned during execution;
- the migration/legal-version harness cannot point at a file deleted by Step 7;
- broader repository tooling/docs are updated only after final code/schema shape is known;
- generated artifacts are produced last from stable source;
- Steps 1–8 are branch-local checkpoints and are not deployed or merged independently; Step 9 restores the full canonical `npm run check` green boundary.

---

## 7. Explicit deferrals after ANY-522

ANY-522 introduces no new target billing runtime. It installs the approved target storage baseline while the following runtime/evidence responsibilities remain later owners:

- ANY-504 Step 5 — LBX Phase 0 evidence and provider-specific gates;
- ANY-504 Step 6 — capability/catalog synchronization and mapping publication;
- ANY-504 Step 7 — PurchaseIntent/customer/agreement/subscription preparation and Widget flow;
- ANY-504 Step 8 — webhook/reconciliation/discovery/recovery workers;
- ANY-504 Step 9 — paid-access derivation, purchased allowances, revisions and invalidation production;
- ANY-504 Step 10 — Portal↔Kernel runtime transport, invalidation delivery and Kernel quota enforcement;
- ANY-504 Step 11 — final cross-repository E2E/launch/as-built consolidation.

ANY-522 must not add placeholder runtime for any of those later owners.

---

## 8. Validation result

This plan was revalidated after the final ANY-510 merge against:

- final `main` at `87dbb62301fcf25eedb86bb897bbe92e021d9886`;
- final Step-3 identity/session/legal handoff;
- completed ANY-509 persistence/reset handoff;
- current legacy API/runtime/ORM state;
- current migration/test/harness state;
- target FK dependency graph;
- ANY-522 acceptance criteria and explicit deferrals.

### Corrections made during validation

1. Removed the provisional PR #118 gate: ANY-510 is merged and its final state is authoritative.
2. Recorded the actual merge commit rather than the old provisional PR head.
3. Confirmed the final merged Step-3 handoff/ORM/API content did not materially change from the last reviewed PR head.
4. Reworked target ORM sequencing so the cyclic access-scope/subscription/observation FK graph is implemented in one step instead of leaving an incomplete intermediate metadata state.
5. Added the complete Step-3 survivor physical contract and a field-level target persistence traceability matrix so execution models do not need to rediscover ANY-509 requirements.
6. Removed obsolete external-ticket approval gates and made ANY-504 plus completed ANY-509/ANY-510 and current repository state the sole implementation authority for ANY-522.
7. Kept the clean-reset/recreate-only premise as an approved predecessor decision instead of making each Codex step revalidate settled external assumptions.
8. Corrected mapping revision wording so Step 4 enforces positive/scoped revision identity without implementing ANY-504 Step-6 monotonic publication behavior.
9. Replaced the old checkout-specific frontend verification with the surviving component suite, allowing `CheckoutClient` to be removed/replaced by the auth-only shell.
10. Moved the minimal `scripts/repo.py` migration/legal-version source update into Step 7 so the same commit that deletes the old migration history cannot leave the harness referencing a deleted file; broader harness/docs cleanup remains Step 8.
11. Added the focused target DDL immutability assignment required by the ANY-509/ANY-522 verification contract without introducing a generic immutability framework.
12. Made the cyclic Alembic DDL sequence explicit: the access-scope and subscription columns are created first, only the two cycle-closing composite FKs are deferred, and downgrade reverses those dependencies.
13. Expanded the Step-3 survivor traceability to exact retained columns, nullability/default semantics, FKs and index scopes, and removed remaining target-table "indexes from the handoff" placeholders in favor of concrete index coverage.
14. Added the one-time dev/test/pre-production recreate/bootstrap runbook contract, including stop/recreate/bootstrap/pre-start verification/smoke/failure-recovery sequencing and the prohibition on fabricated platform commands.
15. Defined Steps 1–8 as branch-local checkpoint commits and Step 9 as the sole canonical CI/merge-ready boundary, so intentionally stale docs/generated artifacts cannot be mistaken for a valid independently mergeable state.
16. Bound Step 2 to remove the current CloudPayments implementation-level `test_architecture.py` imports/test in the same change as the deleted source, while retaining implementation-independent prohibition guards.
17. Replaced remaining handoff-dependent Step-4 constraint placeholders with explicit ownership: no Step-4 `attempt_count >= 0` CHECK on `billing_work_items`, no premature manual-review resolution pairing CHECKs, and focused target DDL immutability protections only where the persistence handoff requires physical history/identity protection.
18. Added the exact Step-4 PostgreSQL concurrency/uniqueness proof set without pulling later application locking/idempotency workflows forward.
19. Grounded the reset/bootstrap runbook in the actual repository harness commands and made the clean Alembic baseline the bootstrap authority instead of leaving Codex to invent or rediscover a bootstrap command.
20. Corrected remaining `LATER_STEP_RUNTIME` validations so Step 4 creates approved storage/index shape without prematurely installing later-owned semantic CHECKs.
21. Clarified that Step-3 runtime/identity/legal behavior proofs survive the reset while discarded-history upgrade/backfill tests are replaced by clean-baseline/bootstrap proofs.
22. Added a fresh-chat Codex execution protocol and bounded plan-section reads so each numbered step can be implemented in a separate chat without relying on previous chat memory or repeating broad predecessor research.

### Execution readiness

This plan was executed sequentially through Step 9 and is retained as completed
implementation history. It must not be restarted. No additional Linear-ticket
prerequisite existed outside the authority chain defined in this plan.

No additional unresolved business, public API, persisted-data, security or architecture decision was found that should be delegated to the execution model.

---

# Definition of Done

ANY-522 is complete only when:

- final merged ANY-510 is the consumed retained baseline;
- ANY-504 plus completed ANY-509/ANY-510 and the current repository baseline remain the implementation authority;
- no external ticket outside the authority chain gates or redefines ANY-522;
- the approved clean-reset/recreate-only contract is preserved without adding a compatibility bridge, dual-write or legacy billing-data backfill;
- SQLAlchemy metadata contains exactly the ten retained Step-3 tables and fifteen approved target tables;
- every approved Step-4-safe target physical invariant is implemented and verified in PostgreSQL;
- every Phase-0-gated/provider-dependent rule remains intentionally unclosed;
- CloudPayments and direct-provider implementation/runtime/config/tests are physically removed;
- Portal-owned catalog/checkout/order/payment/refund/subscription/entitlement/trial authority is physically removed;
- one fresh first-install Alembic baseline/head exists and its cyclic access-scope/subscription/observation FKs are installed through the explicit two-phase DDL order without weakening the final graph;
- old-stamped dev/test/pre-production databases are recreate-only and an executable one-time reset/bootstrap/recovery runbook is documented;
- configured-contour/legal bootstrap succeeds from empty PostgreSQL;
- all target billing tables start empty;
- final Step-3 identity/session/recovery/legal behavior survives;
- current-state docs, architecture guards, DB schema and OpenAPI describe the clean baseline;
- partial Steps 1–8 were never treated as independent merge/deploy candidates, and the Step-9 integration boundary restores canonical generated/docs state;
- full repository verification passes;
- ANY-504 Step 5 can start without repairing legacy residue or inventing a missing Step-4 persistence decision.
