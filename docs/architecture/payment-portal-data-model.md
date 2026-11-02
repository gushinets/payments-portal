# Payment Portal Data Model and Backend Invariants

Status: authoritative current-state schema reference
Last updated: 2026-11-02 (ANY-765 Step 4 local paid-state read)

> **CURRENT AS-BUILT SCHEMA REFERENCE**

This document describes the schema produced by the current Alembic chain:

```text
20260924_0001 -> 20261001_0002 -> 20261029_0003 -> 20261028_0005 -> 20261031_0006 (head)
```

`20260924_0001_clean_first_install` creates the 25-table first-install schema.
`20261001_0002_clear_false_email_verification` is a data-only forward migration
that clears predecessor registration-time `users.email_verified_at` values,
because those timestamps did not prove mailbox ownership.
`20261029_0003_normal_billing` consolidates the ANY-709 branch migrations after
main's unchanged head. It adds the current-link pointer, nullable proven origin,
optional FIO, customer/provider and permanent-operation uniqueness, send fences,
coalesced recovery work, user/product purchase holds, scoped financial bindings
and immutable financial-send evidence. Existing operation account/hold backfills
refuse ambiguous history without deletion or arbitrary adoption. The migration
creates no provider object and does not guess legacy origin or rewrite immutable
mapping/consent evidence.

Its nullable `billing_work_items.active_recovery_deadline_at` records the fixed
window for a genuinely new proven-unsent financial attempt; NULL retains the
original immutable deadline. Retired branch revision IDs are absent from the
current graph. Already-applied branch databases need the verified transition in
the [migration runbook](../engineering/ANY-709-billing-runbook.md#consolidated-any-709-migration),
never automatic stamping or replay of consolidated DDL. This document owns
persistence meaning; `docs/generated/db-schema.md` owns column-level output.

`20261028_0005_billing_worker` adds durable enqueue generations, attempt-start
timestamps and recurring-job uniqueness after consolidated revision
`20261029_0003`, preserving active deadlines and existing send leases. The chain
has one current head.

Target commercial ownership and runtime behavior follow, in precedence order:

1. [ADR 0005](decisions/0005-external-billing-boundary.md);
2. [External Billing Boundary Design](../superpowers/specs/2026-09-15-external-billing-boundary-design.md);
3. [Portal <-> Kernel Access Contract Design](../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md).

The [accepted live-source admission amendment](../superpowers/specs/2026-10-15-live-source-commercial-admission-design-amendment.md)
narrowly supersedes source-catalog mirroring/new-sale TTL; it requires no schema
change. Subscription trust, reconciliation and AccessSnapshot are unchanged.

The schema is a provider-independent storage baseline. Its presence does not
itself establish runtime acceptance. ANY-709 implements purchase preparation
and request-driven recovery. ANY-715 adds shared reconciliation, embedded durable
polling and audited operations; ANY-765 Steps 2–3 add local paid derivation,
revision/outbox commits, effective deadlines and audited recovery. Step 4 reads
committed paid state for the cabinet; Kernel delivery remains later work.

## Physical baseline

A fresh database has exactly 27 application tables: ten retained
identity/session/legal tables, fifteen original external-billing persistence
tables, one current product-link pointer and one purchase mutex. Alembic has
five revisions in one linear chain and one current head. Revision
`20261029_0003` belongs to ANY-709; revision `20261028_0005` belongs to ANY-715;
revision `20261031_0006` belongs to ANY-765 Step 2.

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
| `paid_access_states` | Access | Provider-neutral paid-access document storage with a required revision slot per user scope; positive monotonic semantic revisions are enforced. |
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
fingerprint, immutable accepted snapshot, and client idempotency key.
New ANY-765 Step 1 acceptances use `accepted-purchase:v2`: complete optional
technical terms, their independent expected digest, dev source version/content
digest, exact link/component/offer binding, Kernel evidence and SIMULATED
provenance are embedded in the existing JSON snapshot. Legacy v1 remains
readable without metering. Step 1 introduced no new columns or migration;
Step 2 derives allowances from this saved evidence.

The purchase closed states are `created`, `preparing`, `awaiting_external_result`, `linked`,
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
transition or a replay. Customer retry semantics remain separate. ANY-715 runs
GET-only background recovery and local deadlines through its embedded worker;
background execution never acquires CREATE authority.

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

Shared reconciliation uses the subscription lease/fence columns and appends
`subscription-reconciliation:v1` evidence. Complete matching proof anchors at
most six hours of source trust to read-set start. Incomplete attempts preserve
the existing deadline; owned negative/conflict evidence reduces usability.
Preparation cannot overwrite monitored facts. ANY-765 Step 2 integrates this
path with primary selection and the atomic paid writer; see the
[operations runbook](../engineering/billing-background-operations.md).

`billing_state_observations` stores evidence whose core fields are immutable.
Its closed kinds are
`authoritative_subscription_read`, `target_product_discovery`,
`primary_selection`, and `deterministic_access_boundary`; database checks
enforce each kind's minimum provenance shape. DELETE is forbidden, and all
fields except `resulting_access_revision` are immutable. That field may be
assigned exactly once from `NULL` to a non-null value; once assigned, it cannot
be cleared or replaced. ANY-765 Step 2 enforces positivity and links committed
semantic changes to these observations.

`purchased_allowances` freezes source component, product, metric, unit, quantity,
accepted terms/provenance and classified cycle meaning. Logical identity is unique
by `(subscription_id, source_component_id, metric_key, provider_cycle_key)`.
The immutable whole-row trigger covers all new fields. Storage distinguishes:

- `legacy-utc:v1`: original non-null UTC periods retained exactly; no inferred
  calendar dates, units or terms;
- `calendar:v1`: explicit inclusive `cycle_date_start/end`, versioned
  `calendar_document`, non-null cycle key/unit/terms, no fabricated UTC bounds;
- `timestamp:v1`: independently zoned source instants and frozen conservative
  effective UTC periods; no date-only fields. Naive/mixed precision never grants
  an allowance.

Cycle classification precedes insertion. Month/year arithmetic uses the frozen
original anchor, including month-end and leap-day clipping. Same-cycle recovery
reuses identity; a proven later current cycle issues only that cycle. Ambiguity
opens `subscription_metric` review and omits that metric, preserving product
access. Legacy purchases never acquire today's test quantities.

ANY-765 Step 2 persists `target-product-discovery:v2` before the final product
lock, including bounded normalized candidate conclusions, original provenance,
linked point proof and claim/fence evidence. Its scope ID may be absent before a
scope exists; a purchase reference remains mandatory. The decision unions it
with locally known nonterminal sources. Confirmed ended external candidates
are ineligible without requiring a local purchase. Unknown nonterminal
candidates remain incomplete. Scope rows retain the internal
`effective_access_document`, conservative `effective_access_until`, supporting
`access_basis_observation_id` and `primary_retired_at`. Complete reads may refresh
metadata without changing semantic state. Blocking retains primary identity;
terminal clearing prevents promotion of an old competitor.

`paid_access_states` stores one complete provider-neutral internal document per
user, schema `paid-effective-state:v1`. This is not an AccessSnapshot wire DTO.
No row is implicit empty revision zero. Material changes atomically write positive
revision 1, then exactly N+1, with causal observations and coalesced outbox.
Database guards forbid revision regression/skips, same-revision semantic changes,
identity replacement and deletion/reset. `resulting_access_revision` is positive
when present and can be populated once; a later change appends a causal
observation. `access_invalidation_outbox` preserves delivery bookkeeping while
coalescing `pending_revision = max(existing, committed)`; pending/delivered
regression and deletion are forbidden. Delivery/ack networking remains deferred.

Migration `20261031_0006` preserves legacy rows and preflights incompatible
non-null logical duplicates, nonpositive state/observation revisions and negative
delivered revisions. It fails without repair/deletion. Downgrade refuses to lose
new calendar, access or pre-scope discovery meaning. Step 3 reuses this schema
for worker deadlines and customer/operator integration. Step 4 adds a local
paid-state read over the same schema; no further migration or Kernel networking
is introduced. The read takes a shared user-row lock after identity bookkeeping
to stabilize revision/document, per-product evidence and deadlines against the
user-first writers. It does not modify billing, state, observations, allowances,
work or outbox. An overdue effective tuple refuses with
`503/paid_access_deadline_pending` until the worker commits the next revision.

## Durable operational tables

`external_billing_webhook_deliveries` stores bounded, redacted correlation and
evidence documents, receipt/processing timestamps, and safe classifications.
It never stores authorization material, card/payment fields, or a raw provider
payload, and receipt alone never grants access. ANY-715 Step 4 uses existing
JSON storage without a schema migration: `billing-webhook-receipt:v1` retains
only the allowlisted event; `billing-webhook-work:v1` retains a subject hash and,
for queued receipts, local subscription/work IDs and `enqueue_generation`.
The payload hash is diagnostic, never permanent deduplication. Processing states
are canonical text-backed `WebhookDeliveryState` values: `pending`, `processed`,
`ignored`. Complete fenced apply updates covered pending receipts atomically;
later generations and incomplete/crashed attempts stay pending.

`billing_work_items` stores open work/scope/state vocabularies, bounded typed
payloads, priority, due time, attempt count, paired lease owner/expiry and nullable
`active_recovery_deadline_at` for the current financial send. This active deadline
changes only in the locked send claim; GET recovery never renews it. It
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
atomically reschedules monitoring and the local trust deadline. Ordinary
reconciliation/inventory and Step 3 local deadline/customer/review/operator paths
commit paid state through the same caller-transaction writer. The existing
subscription expiry row schedules the earliest saved effective deadline; local
selection/repair uses persisted contour ownership rather than current account
configuration. Source-unconfigured startup retains local reductions. Migration `20261028_0005` follows consolidated billing revision
`20261029_0003` and preserves its active deadline and existing rows.

`manual_review_cases` stores bounded evidence and optional resolution proof.
It cannot itself activate access, invent an allowance, or rewrite historical
purchase/mapping evidence.
ANY-715 Step 5 records `billing-operator-resolution:v1` in those existing slots:
OS principal, reason/reference, command digest, before/after identities,
supporting observation and versioned fresh-proof summary. Original evidence is
preserved. Financial conflict evidence retains the prior operation state/send
fence to distinguish possible-send history from completed no-send. Known cases
without sufficient preserved proof refuse binding; no retrospective assertion
or force override supplies it. Audit, permitted shared apply/bind and scheduling
commit atomically; terminal holds remain. No Step 5 DDL is required.

## Persisted vocabularies

Closed text-backed enums are defined only in `app.models.enums`:

- identity/legal: `RegionStatus`, `UserStatus`, `MagicLinkPurpose`,
  `LegalEntityStatus`, `LegalEntityType`, `AcceptanceKind`;
- purchase: `ExternalBillingCustomerBindingState`, `PurchaseIntentState`,
  `ExternalCreateOperationKind`, `ExternalCreateOperationState`;
- reconciliation: `ExternalSubscriptionLifecycleStatus`,
  `ExternalSubscriptionFinancialAccessStatus`,
  `ExternalSubscriptionCommercialAccessStatus`,
  `BillingStateObservationKind`;
- webhook inbox: `WebhookDeliveryState`.

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
