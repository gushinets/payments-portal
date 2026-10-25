# Payment Portal Data Model and Backend Invariants

Status: authoritative current-state schema reference
Last verified: 2026-10-21

> **CURRENT AS-BUILT SCHEMA REFERENCE**

This document describes the schema produced by the current Alembic chain:

```text
20260924_0001 -> 20261001_0002 -> 20261021_0003 -> 20261025_0004 (head)
```

`20260924_0001_clean_first_install` creates the 25-table first-install schema.
`20261001_0002_clear_false_email_verification` is a data-only forward migration
that clears predecessor registration-time `users.email_verified_at` values,
because those timestamps did not prove mailbox ownership.
`20261021_0003_purchase_scope_fencing` adds durable purchase-scope holds and
external-create fencing/recovery constraints. It backfills existing ownership
and fails on conflicting historical purchase scopes rather than choosing an
owner. `20261025_0004_optional_user_names` adds three nullable, bounded
registration-name columns without defaults/backfill; migration verification is
pending the human Step 6 run. The chain has one current head. This document is authoritative for the
implemented SQLAlchemy table inventory and physical persistence rules; the
generated column-level artifact remains `docs/generated/db-schema.md`.

Target commercial ownership and runtime behavior follow, in precedence order:

1. [ADR 0005](decisions/0005-external-billing-boundary.md);
2. [External Billing Boundary Design](../superpowers/specs/2026-09-15-external-billing-boundary-design.md);
3. [Portal <-> Kernel Access Contract Design](../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md).

The [accepted live-source admission amendment](../superpowers/specs/2026-10-15-live-source-commercial-admission-design-amendment.md)
narrowly supersedes source-catalog mirroring/new-sale TTL; it requires no schema
change. Subscription trust, reconciliation and AccessSnapshot are unchanged.

The schema is a provider-independent storage baseline. Its presence does not
mean provider integration, purchase orchestration, reconciliation workers,
paid-access derivation, or Kernel invalidation delivery is implemented.

## Physical baseline

A fresh database has exactly 26 application tables: ten retained
identity/session/legal tables and sixteen external-billing persistence
tables. Alembic has three revisions in one linear chain and one current head.

There is no Portal-owned product, plan, order, payment, refund, subscription,
entitlement, trial, provider-account, or direct-payment webhook table. There is
also no `external_billing_accounts` table. `external_billing_account_id` is an
opaque configuration-scope value wherever it appears; it is not a foreign key
to a Portal-managed routing catalog.

| Table | Group | Current purpose |
| --- | --- | --- |
| `regions` | Identity/contour | Configured contour identity and locale/currency metadata. |
| `country_region_rules` | Identity/contour | Country membership, market enablement, strict mismatch, and legal document-set selection. |
| `users` | Identity | Canonical contour-scoped Portal user. |
| `auth_sessions` | Identity | Hashed, expiring and revocable authenticated sessions. |
| `magic_link_tokens` | Identity | Purpose-bound hash-only password-reset and email-verification capabilities, including decoy-safe nullable user binding for password reset. |
| `password_reset_rate_limits` | Identity | Durable password-reset rate-limit windows. |
| `legal_entities` | Legal | Contour operator metadata. |
| `document_versions` | Legal | Versioned legal material and active-version selection. |
| `legal_acceptance_events` | Legal | User acceptance actions with immutable core evidence and clear-only IP/user-agent audit metadata. |
| `document_acceptances` | Legal | Append-only links from an acceptance event to exact legal document versions and text hashes. |
| `capability_manifest_projections` | Inert schema slot | Former complete Kernel manifest projection; no runtime reader/writer under live-source admission. |
| `external_billing_catalog_projections` | Inert schema slot | Former External Billing catalog projection; no runtime reader/writer under live-source admission. |
| `commercial_mapping_revisions` | Mapping | Immutable published mapping revisions that pin manifest and catalog evidence. |
| `external_billing_customers` | Purchase | Portal-owned binding from a user to an opaque External Billing customer identity. |
| `purchase_intents` | Purchase | Durable purchase orchestration state with immutable accepted commercial/legal evidence. |
| `billing_purchase_scope_holds` | Purchase | Durable user/product ownership reservation with fencing epochs and append-only release evidence. |
| `external_create_operations` | Recovery | Durable external-create attempt and unknown-outcome recovery state. |
| `billing_product_access_scopes` | Reconciliation | One user/product access scope and its selected primary external subscription. |
| `external_subscriptions` | Reconciliation | Normalized external-subscription projection with lifecycle and access statuses. |
| `billing_state_observations` | Evidence | Normalized evidence with immutable core fields and a one-time resulting-access revision assignment. |
| `purchased_allowances` | Reconciliation | Purchased metric quantities and their effective periods. |
| `external_billing_webhook_deliveries` | Operations | Redacted webhook receipt/correlation evidence; never raw payload or access authority. |
| `billing_work_items` | Operations | Shared durable scheduling/lease substrate; not business authority. |
| `manual_review_cases` | Operations | Durable conflict/uncertainty evidence and audited resolution slots. |
| `paid_access_states` | Access | Provider-neutral paid-access document storage with a required revision slot per user scope; runtime transition semantics are deferred. |
| `access_invalidation_outbox` | Access | Durable pending/delivered revision slots for later paid-access invalidation delivery. |

The documentation checker requires every implemented SQLAlchemy metadata table
to have a row in this inventory.

## Scope and identity invariants

- A production instance serves exactly one contour. The current clean migration
  accepts only configured `anytoolai` / `ru` and seeds its RU country
  membership; any other configured scope fails before bootstrap completes.
- `users` is unique by `(tenant_id, region, email_normalized)` and exposes the
  composite alternate key `(id, tenant_id, region)` to scoped dependants.
- Sessions, legal records, paid-access state, and invalidation state preserve
  explicit tenant/region/user scope through composite restrictive foreign keys.
- Customer, purchase, subscription, observation, mapping, and legal evidence
  links use composite foreign keys where a plain UUID would permit accidental
  cross-account, cross-user, cross-product, or cross-offer linkage.
- Platform Kernel `product_id` and `metric_key`, External Billing offer/object
  identifiers, and `external_billing_account_id` remain opaque external
  identifiers. The Portal does not create replacement catalog/account tables
  merely to give them foreign keys.

## Identity and legal tables

`regions` and `country_region_rules` are contour-local configuration state.
`country_region_rules` contains only `country_code`, `region`,
`market_enabled`, `strict_mismatch`, and `default_document_set` beyond its
identifier. Direct-provider defaults and region override flags do not exist.

`users`, `auth_sessions`, `magic_link_tokens`, and
`password_reset_rate_limits` retain the provider-independent authentication,
mailbox-verification, and recovery behavior. Session and capability secrets are
stored only as hashes. `magic_link_tokens.purpose` distinguishes
`password_reset` from `email_verification`; both capabilities are scoped to the
configured tenant/region and the canonical user when `user_id` is present.
Password-reset requests for unknown email addresses alone may use the nullable
user binding and one-way decoy email key. `users.email_verified_at IS NOT NULL`
is the single authoritative mailbox-verification fact. Nullable bounded
`users.user_surname`, `users.user_name`, and `users.user_patronymic` retain only
optional supplied registration names (migration `20261025_0004`, no backfill or
default). They are unverified profile data, excluded from session responses and
purchase/legal snapshots; registration does not create an LBX customer.

`legal_acceptance_events` is the acceptance-action parent. Its
`external_billing_account_id`, `billing_offer_id`, and
`accepted_commercial_fingerprint` fields are either all null or all non-empty.
DELETE is forbidden. Its identity, scope, user, commercial, and timestamp
fields (`id`, `tenant_id`, `region`, `user_id`, the three commercial fields,
`accepted_at`, and `created_at`) are immutable. The only permitted value change
is clearing `ip` or `user_agent` from a value to `NULL`; cleared values cannot
be restored, and non-null values cannot be replaced.

`document_acceptances` records the exact document version, acceptance kind and
acceptance-text hash for that event. PostgreSQL triggers reject every update or
delete of a document acceptance and prevent mutation of immutable
document-version material.

## Projection and mapping tables

`capability_manifest_projections` permits one row per `(tenant_id, region)`;
`external_billing_catalog_projections` permits one per configured billing
account. Their schema/version/timestamp/JSON columns remain physical storage
only. Both tables are inert: no startup/periodic synchronization or admission
reader is planned under the accepted amendment. Publication/new purchase read
sources live. Catalog browsing uses immutable approved mappings in PostgreSQL.

`commercial_mapping_revisions` is append-only publication evidence. A revision
is unique within `(external_billing_account_id, billing_offer_id)`, has a
positive `revision_number`, and pins manifest/catalog versions and digest plus
the typed mapping document and publishing principal. PostgreSQL triggers
prevent updates and deletes.

ANY-664 uses `catalog_version=NULL` and `catalog_digest` as the explicitly
scoped `selected_offer` evidence digest in `mapping_document`, not an account
catalog snapshot. That evidence includes the complete default-assigned service
composition and source provenance. Technical/commercial/legal approval versions
are pinned; changed commercial terms require new legal approval, while a purely
technical change does not. No existing revisions are rewritten.

## Purchase and external-create tables

`external_billing_customers` permits exactly one binding per billing account
and Portal user and a globally unique non-empty `billing_customer_key`. Its
closed binding states are `unbound`, `bound`, and `identity_conflict`.

`purchase_intents` ties one user/customer/account/product/offer to a published
mapping revision, exact legal acceptance event, accepted commercial
fingerprint, immutable accepted snapshot, and client idempotency key. Its
closed states are `created`, `preparing`, `awaiting_external_result`, `linked`,
`resolved_no_external_effect`, `failed_before_external_effect`, and
`manual_review`. PostgreSQL triggers keep the accepted evidence/provenance
fields immutable.

ANY-709 persists `accepted_snapshot_schema_version=v1`. The JSON document
contains `schema_version`, tenant/region/account/user scope, canonical request
(selected revision, public fingerprint, explicit confirmations and exact
document IDs/text hashes), the original review (mapping material/technical
allowance, seller reference/revision, exact initial money and legal pins),
source admission mapping/account-calendar date/timezone, and `accepted_at`.
Decimal amounts serialize as strings; a monotonic admission deadline is never
persisted. Widget Manage uses this original evidence and its purchase-specific
acceptance event, not current catalog pricing or newly invented consent.
Links without provable original acceptance remain not ready for Widget.

`billing_purchase_scope_holds` serializes purchase ownership independently of
access-primary selection. Its UUID primary key is `hold_id`;
`(user_id, product_id)` is unique across both `held` and `released` rows, regardless of
billing account. The row retains `tenant_id`, `region`, and
`external_billing_account_id`, nullable `purchase_intent_id` and
`subscription_id` owner links, `hold_state`, positive `ownership_epoch`
(initially `1`), and `created_at`, `updated_at`, and nullable `released_at`.
At least one owner link is required.

Composite restrictive foreign keys bind the user to its tenant/region and each
owner to the same billing account, user, and product. When both owner links are
present, a PostgreSQL trigger requires the subscription's purchase provenance
to match the linked intent. The account and product identifiers remain opaque;
the hold does not select a primary access subscription or grant paid access.

New rows start `held`. Scope identity is immutable and DELETE is forbidden.
Ownership epochs cannot decrease; changing an owner, billing account, or hold
state requires a greater epoch. A held row must be released before reassignment;
linking its subscription is allowed when that link was previously null and
matches the purchase provenance. Release retains the original owner links.
Reusing a released row advances the epoch and preserves its release audit.

Ownership survives unresolved external creates and nonterminal subscriptions;
elapsed time, source availability, payment state, and browser state do not prove
release. `release_evidence_schema_version` and JSONB
`release_evidence_document` are paired, with schema version `v1`. Release
requires `released_at` and an append-only `releases` audit containing typed
proof (`authoritative_no_effect`, `verified_terminal`, or `audited_support`),
a non-empty `proof_reference`, an audited `principal`, and the held ownership
epoch. The release helper also records the observation time and owner links.

For release without `audited_support`, PostgreSQL rejects any non-`ended`
subscription for the user/product or unresolved external create for that
user/product, including customer creates with no purchase intent.
`verified_terminal` additionally requires the linked subscription to be `ended`.
`audited_support` permits release despite those blockers but still requires the
typed proof and audit. A released row has a non-null `released_at`; a held row
has none.

`external_create_operations` records customer, agreement, or subscription
create work. Customer creation has no purchase intent; agreement and
subscription creation require one. Unknown timestamps are paired, the
PostgreSQL deadline is exactly two hours after `unknown_since`, and recovery
hint schema/document values are paired. One unresolved customer-create
operation is allowed per customer. ANY-709 owns the implemented
`unsent` → `possible_send` → `unknown`/`bound`/`manual_review` path and
`failed_before_send` outcomes. The committed send fence is the one CREATE
permission; unresolved outcomes permit only discovery/point reads, with one
coalesced work item and explicit two-hour escalation. No worker runs yet.
The [Step 8 handoff](../engineering/ANY-709-unknown-recovery.md#step-8-handoff)
records the reusable calls and retained ownership. Widget authorization writes
no credential or paid projection to these tables.

## Reconciliation and access tables

`billing_product_access_scopes` is unique by `(user_id, product_id)` and may
select one same-user/same-product primary subscription. The baseline creates
the scope/subscription/observation foreign-key cycle after all three tables
exist.

`external_subscriptions` links customer, optional purchase provenance, optional
mapping provenance, opaque external subscription/agreement IDs, last
authoritative-read freshness, reconciliation lease/fencing state, and the
latest observation. Closed provider-neutral status vocabularies are:

- lifecycle: `active`, `inactive`, `ended`;
- financial access: `allowed`, `blocked`;
- commercial access: `eligible`, `ineligible`.

`billing_state_observations` stores evidence whose core fields are immutable.
Its closed kinds are
`authoritative_subscription_read`, `target_product_discovery`,
`primary_selection`, and `deterministic_access_boundary`; database checks
enforce each kind's minimum provenance shape. DELETE is forbidden, and all
fields except `resulting_access_revision` are immutable. That field may be
assigned exactly once from `NULL` to a non-null value; once assigned, it cannot
be cleared or replaced. Positivity and semantic/causal validation of that
revision belong to ANY-504 Step 9 and are not current storage guarantees.

`purchased_allowances` links a source component and product/metric quantity to
an external subscription. Quantity is non-negative, provider-cycle bounds are
paired, and `period_start < period_end`. PostgreSQL triggers prevent
updates/deletes.

`paid_access_states` has at most one row per `(tenant_id, region, user_id)` and
stores a complete effective-state document with a non-null `access_revision`
slot. The current database does not enforce that slot as positive or enforce
monotonic state transitions; those runtime semantics belong to ANY-504 Step 9.
`access_invalidation_outbox` has the same unique scope. Its physical checks
require a positive pending revision and forbid `delivered_revision` from
exceeding it, but do not implement coalescing or delivery. Runtime derivation,
revision transitions, coalescing, and delivery are not implemented by this
baseline.

## Durable operational tables

`external_billing_webhook_deliveries` stores bounded, redacted correlation and
evidence documents, receipt/processing timestamps, and safe classifications.
It never stores authorization material, card/payment fields, or a raw provider
payload, and receipt alone never grants access.

`billing_work_items` stores open work/scope/state vocabularies, bounded typed
payloads, priority, due time, attempt count, and paired lease owner/expiry. It
is scheduling state, not commercial or access authority. Exact work kinds,
state transitions and coalescing rules are intentionally deferred.

`manual_review_cases` stores bounded evidence and optional resolution proof.
It cannot itself activate access, invent an allowance, or rewrite historical
purchase/mapping evidence.

## Persisted vocabularies

Closed text-backed enums are defined only in `app.models.enums`:

- identity/legal: `RegionStatus`, `UserStatus`, `MagicLinkPurpose`,
  `LegalEntityStatus`, `LegalEntityType`, `AcceptanceKind`;
- purchase: `ExternalBillingCustomerBindingState`, `PurchaseIntentState`,
  `ExternalCreateOperationKind`, `PurchaseScopeHoldState`,
  `PurchaseScopeReleaseKind`;
- reconciliation: `ExternalSubscriptionLifecycleStatus`,
  `ExternalSubscriptionFinancialAccessStatus`,
  `ExternalSubscriptionCommercialAccessStatus`,
  `BillingStateObservationKind`.

Other operational classifications remain open text until their owning runtime
step closes them. The repository guard prevents duplicate definitions of the
closed persisted vocabularies and prevents restoration of removed billing enum
facades.

## Bootstrap and runtime boundary

The first revision owns schema creation and deterministic bootstrap of the
currently supported configured `anytoolai` / `ru` contour, local RU country
membership, legal entity, and six current RU legal document versions. The
second revision clears every non-null predecessor `email_verified_at` value and
cannot reconstruct those false-positive values on downgrade. The API legal seed
is an idempotent, fail-closed runtime validation of the same canonical legal
material and rejects any other configured scope; it is not a second schema or
migration authority.

All sixteen billing tables are empty after fresh bootstrap. Step-4 application
runtime does not populate them. Browser returns, callbacks, webhook receipt,
outbound command success, or payment state alone never grant paid access.

The discarded Alembic history has no upgrade bridge into this baseline. Reset,
compatibility and recovery procedures are documented in
[Deployment Architecture](deployment.md#one-time-step-4-recreate-and-bootstrap).
