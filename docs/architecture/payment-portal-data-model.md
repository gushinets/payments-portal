# Payment Portal Data Model and Backend Invariants

Status: authoritative current-state schema reference
Last updated: 2026-10-29 (one consolidated ANY-709 migration, including active recovery windows)

> **CURRENT AS-BUILT SCHEMA REFERENCE**

This document describes the schema produced by the current Alembic chain:

```text
20260924_0001 -> 20261001_0002 -> 20261029_0003 (head)
```

`20260924_0001_clean_first_install` creates the 25-table first-install schema.
`20261001_0002_clear_false_email_verification` is a data-only forward migration
that clears predecessor registration-time `users.email_verified_at` values,
because those timestamps did not prove mailbox ownership.
`20261029_0003_normal_billing` consolidates all ANY-709 branch-local
operations into one forward migration after main's unchanged head. It adds one
small current-link pointer table, nullable provider-origin provenance and unique
`(provider_origin, product_id)` without backfilling or rewriting legacy mappings.
It also adds optional FIO, nullable customer origin, provider-ID uniqueness,
permanent customer-operation identity, send fencing and coalesced recovery-work
uniqueness. It neither guesses identity/origin nor creates provider objects.
It adds the purchase hold, scoped permanent financial identities/bindings and
immutable financial-send evidence. It backfills operation scope from its existing
customer and holds nonterminal purchases; ambiguous old holds/bindings fail the
upgrade without deletion or arbitrary adoption. It adds the explicit financial
`unverified` state. Clean and populated test upgrades have passed. The earlier
purchase-preparation schema was applied as the original four-revision chain to
the local development database under explicit owner authorization on 2026-10-27;
existing application row counts were preserved. This historical application does
not assert application of the final `20261029_0003` revision. Consolidation
retains every upgrade/downgrade operation. The
owner requested consecutive numbering after the initial consolidation: an
existing fully upgraded `20261027_0006` schema must be verified before changing
only its revision label to the then-current `20261027_0003`; its DDL must not be replayed.
This local transition completed under explicit owner authorization after an exact
schema comparison and protected backup; all rows in 27 application tables were
preserved and normal `upgrade head` passed afterward.
The final single migration also includes the former
`20261028_0004_financial_recovery_window`: nullable
`billing_work_items.active_recovery_deadline_at`, without rewriting existing rows.
NULL retains the original immutable financial deadline. Only a new fenced send
permitted by `proven_not_sent` establishes a fresh two-hour recovery window.
Upgrade operations are the exact concatenation of the former `0003` and `0004`;
downgrade executes `0004`'s inverse before `0003`'s inverse.

Both old `20261027_0003` and `20261028_0004` are retired revision IDs; normal
`upgrade head` rejects them without replaying DDL or silently skipping changes.
The former `0003` may lack the active-window column. Such databases must first
finish the old chain at `20261028_0004` using checkout `afb46c5`, then verify the
complete schema, retain a protected backup and change only the revision label
to the new `20261029_0003`. An old `0004` database needs the same verified label
transition, with no DDL replay or row rewrite. Retired earlier revisions must
follow their original upgrade path first; see the
[migration runbook](../engineering/ANY-709-billing-runbook.md#consolidated-any-709-migration).
No automatic compatibility stamp is performed. The chain has one current head.
This document is authoritative for the implemented SQLAlchemy
table inventory and physical persistence rules; the generated column-level
artifact remains `docs/generated/db-schema.md`.

Target commercial ownership and runtime behavior follow, in precedence order:

1. [ADR 0005](decisions/0005-external-billing-boundary.md);
2. [External Billing Boundary Design](../superpowers/specs/2026-09-15-external-billing-boundary-design.md);
3. [Portal <-> Kernel Access Contract Design](../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md).

The [accepted live-source admission amendment](../superpowers/specs/2026-10-15-live-source-commercial-admission-design-amendment.md)
narrowly supersedes source-catalog mirroring/new-sale TTL; it requires no schema
change. Subscription trust, reconciliation and AccessSnapshot are unchanged.

The schema is a provider-independent storage baseline. Its presence does not
itself establish runtime acceptance. ANY-709 Step 3 implements purchase preparation
with focused synthetic tests passing and real purchase/payment QA pending.
ANY-715 Steps 1–2 add shared reconciliation and embedded durable polling;
paid-access derivation and Kernel invalidation delivery remain future work.

## Physical baseline

A fresh database has exactly 27 application tables: ten retained
identity/session/legal tables, fifteen original external-billing persistence
tables, one current product-link pointer and one purchase mutex. Alembic has
three revisions in one linear chain and one current head; only the last revision
belongs to ANY-709.

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
| `commercial_product_heads` | Mapping | One current immutable revision per connection/product; product CAS sequence across offer retargets, no price catalog. |
| `external_billing_customers` | Purchase | Portal-owned binding from a user to an opaque External Billing customer identity. |
| `purchase_intents` | Purchase | Durable purchase orchestration state with immutable accepted commercial/legal evidence. |
| `billing_purchase_scope_holds` | Purchase | Unique user/product hold pointing to the accepted intent, independent of paid-access primary selection. |
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
is the single authoritative mailbox-verification fact.

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
sources live. ANY-709 discovery reads enabled Kernel products and selected
current LBX values; PostgreSQL retains immutable links/history.

`commercial_mapping_revisions` is append-only publication evidence. A revision
is unique within `(external_billing_account_id, billing_offer_id)`, has a
positive `revision_number`, and pins manifest/catalog versions and digest plus
the typed mapping document and publishing principal. PostgreSQL triggers
prevent updates and deletes.

Historical v1 ANY-664 uses `catalog_version=NULL` and `catalog_digest` as the explicitly
scoped `selected_offer` evidence digest in `mapping_document`, not an account
catalog snapshot. That evidence includes the complete default-assigned service
composition and source provenance. Technical/commercial/legal approval versions
are pinned; changed commercial terms require new legal approval, while a purely
technical change does not. No existing revisions are rewritten.

ANY-709 v2 uses `mapping_schema_version=product-link-v2`; its `catalog_digest`
is explicitly the **link identity digest**, not a price or whole-catalog digest.
The versioned document pins connection scope, selected Kernel product and LBX
service/tariff/period/quantity, independent source provenance, manifest evidence
and operator audit. It contains no price, approval certificates or invented
technical allowance. `commercial_product_heads` has primary key
`(external_billing_account_id, product_id)`, a restrictive composite FK to the
immutable revision in the same account, and a positive product revision counter.
Nullable `provider_origin` records only a proven canonical origin. Its unique
pair with product ID prevents two current heads for the same provider/product
under different historical storage scopes. It is not an account registry.
New scope IDs depend on origin and deployment, not credentials. A recognized
old credential-derived scope is retained, with its origin recorded only by an
authorized publish; immutable documents/FKs are untouched. Rotation after this
one-time binding preserves query/publication. Unknown or ambiguous old real
scopes fail explicitly rather than adopting external IDs for another provider.
Offer history numbering remains independent. Product lock/CAS protects first
publication and cross-offer retargeting; v1 rows are not auto-selected. Equal
link identity does not append on ordinary price changes. Accepted historical
rows and dependent purchase/legal keys remain unchanged.

## Purchase and external-create tables

`external_billing_customers` permits exactly one binding per billing account
and Portal user and a globally unique non-empty `billing_customer_key`. Its
closed binding states are `unbound`, `bound`, and `identity_conflict`. ANY-709
Step 2 adds nullable proven `provider_origin` and a unique account/provider ID
pair (NULL remains allowed). No legacy origin is guessed. `users.first_name`,
`surname` and `patronymic` are independent nullable strings bounded to 100
characters; existing users receive no fabricated names.

`purchase_intents` ties one user/customer/account/product/offer to a published
mapping revision, exact legal acceptance event, accepted commercial
fingerprint, immutable accepted snapshot, and client idempotency key. Its
closed states are `created`, `preparing`, `awaiting_external_result`, `linked`,
`resolved_no_external_effect`, `failed_before_external_effect`, and
`manual_review`. PostgreSQL triggers keep the accepted evidence/provenance
fields immutable.

`external_create_operations` records customer, agreement, or subscription
create work. Customer creation has no purchase intent; agreement and
subscription creation require one. Unknown timestamps are paired, the
PostgreSQL deadline is exactly two hours after `unknown_since`, and recovery
hint schema/document values are paired. ANY-709 Step 2 permanently limits
customer create to one operation per customer, including after resolution.
Nullable `send_fence` records the current owner; `pending`, `possible_send`,
`unknown`, `proven_not_sent`, `bound` and `manual_review` use the canonical Python
vocabulary over TEXT storage. The customer send claim atomically records its fence, per-attempt
two-hour deadline and one coalesced `external_create_recovery` work item. Its
existing paired lease fields protect active account-customer sends, and
`attempt_count` counts claimed attempts. Under the owner's 2026-10-28 amendment,
bounded same-opening recovery or a later explicit open can claim a retry after
fresh successful empty discovery and completion/expiry of the active lease,
retaining the same operation/key. A saved
receipt or identity conflict prevents another POST; point proof binds only against
the current fence. Financial operations have a unique intent/kind identity and a unique permanent
account/kind/provider-object binding. Their account/customer composite FK prevents
cross-connection ownership. Financial evidence guards prevent deletion, identity
changes, deadline/request replacement and resetting a possibly sent operation to
pending. A completed typed no-send result may persist `proven_not_sent`; a later
explicit advance claims the same immutable request/key/history with a fresh fence
and reused work item. Its new send has an independent two-hour active recovery
deadline on that work item; the original operation deadline stays immutable.
UNKNOWN, empty GET and deadline expiry never authorize this
transition or a replay. Customer retry semantics remain separate. No background
worker is enabled.

`billing_purchase_scope_holds` has `(user_id, product_id)` as its primary key,
a unique intent and a composite FK to its exact purchase scope. A linked unpaid
subscription keeps this hold without TTL. Step 3 releases only a purchase whose
accepted terms changed before any financial operation could have been sent, under
the same locks as send claims. Other release needs trustworthy audited proof; no
operator force-release command exists.

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
- financial access: `allowed`, `blocked`, `unverified`;
- commercial access: `eligible`, `ineligible`.

Account/provider subscription and agreement IDs are each unique, preserving the
dedicated agreement binding. Initial Step 3 preparation records `unverified`
financial status and an immediately expired projection, plus normalized effective
terms and nullable/sentinel calendar observations. It creates no access-primary,
paid state, grant or allowance, and never extends paid trust on Manage.

ANY-715 Step 1 uses the existing reconciliation lease/fence columns and appends
`subscription-reconciliation:v1` evidence through shared claim/read/apply logic.
It creates/reuses a product scope without selecting a primary. Complete matching
proof anchors at most six hours of source trust to read-set start; incomplete
attempts preserve the existing deadline and complete support, while decisive
owned negative/conflict evidence reduces usability. Subsequent preparation
cannot overwrite monitored facts. All resulting access revisions remain null.
There is no schema change or automatic worker in this step; see the
[operations runbook](../engineering/ANY-715-billing-operations.md).

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
payloads, priority, due time, attempt count, paired lease owner/expiry and nullable
`active_recovery_deadline_at` for the current financial send. The active deadline
is independent of mutable retry scheduling and changes only in the locked,
fenced financial send claim; GET recovery does not renew it. It
is scheduling state, not commercial or access authority. Its work/state
vocabularies remain open for concrete billing jobs. ANY-715 Step 2 adds
nonnegative `enqueue_generation`, nullable `last_attempt_started_at` and a partial
unique `(work_kind, coalescing_key)` index for subscription reconciliation/trust
expiry, enrollment sweep and the reserved inventory/create-deadline kinds.
ANY-715 Step 3 reuses permanent create-operation recovery keys for urgent GET
work and separate account/operation `external_create_deadline` keys for local
fixed two-hour escalation. Customer inventory coalesces by account/local customer,
while subscriptions retain account/local subscription keys. Recovery receipts,
original request/date/fences and customer active-send leases keep their existing
storage identity. No new table or migration is needed. Inventory observations
use `customer-inventory:v1`; conflicts never grant access or rewrite bindings.

The pre-existing create-recovery index and customer-send lease identity remain
unchanged. Claims use paired finite ownership; completion preserves newer enqueue
generations. Binding atomically enrolls new canonical subscriptions. Source apply
atomically reschedules monitoring and the local trust deadline, with no paid-state
or access-revision writes. Migration `20261028_0004` advances the schema from `0003`.

`manual_review_cases` stores bounded evidence and optional resolution proof.
It cannot itself activate access, invent an allowance, or rewrite historical
purchase/mapping evidence.

## Persisted vocabularies

Closed text-backed enums are defined only in `app.models.enums`:

- identity/legal: `RegionStatus`, `UserStatus`, `MagicLinkPurpose`,
  `LegalEntityStatus`, `LegalEntityType`, `AcceptanceKind`;
- purchase: `ExternalBillingCustomerBindingState`, `PurchaseIntentState`,
  `ExternalCreateOperationKind`, `ExternalCreateOperationState`;
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

All fifteen target billing tables are empty after bootstrap. Step-4 application
runtime does not populate them. Browser returns, callbacks, webhook receipt,
outbound command success, or payment state alone never grant paid access.

The discarded Alembic history has no upgrade bridge into this baseline. Reset,
compatibility and recovery procedures are documented in
[Deployment Architecture](deployment.md#one-time-step-4-recreate-and-bootstrap).
