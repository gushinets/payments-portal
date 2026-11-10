# Payment Portal Data Model and Backend Invariants

Status: authoritative current-state schema reference
Last updated: 2026-11-10 (ANY-766 scoped session delegation; ANY-812 policy clarification)

> **CURRENT AS-BUILT SCHEMA REFERENCE**

This document describes the schema produced by the current Alembic chain:

```text
20260924_0001 -> 20261001_0002 -> 20261029_0003 -> 20261028_0005 -> 20261031_0006 -> 20261110_0007 (head)
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

`20261031_0006_paid_access` adds lossless allowance cycles, nullable paid-projection
fields and monotonic storage guards. Its preflight refuses incompatible legacy
history without repair; legacy UTC values are preserved exactly. Downgrade
refuses to discard committed calendar, paid-state or primary-retirement meaning.

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
polling and audited operations. ANY-765 connects paid derivation to shared
reconciliation and first-primary selection to complete relevant shared inventory.
The existing local worker executes and repairs paid deadlines without source
configuration. Kernel invalidation delivery remains ANY-766 work.

## Physical baseline

A fresh database has exactly 28 application tables: ten retained
identity/session/legal tables, fifteen original external-billing persistence
tables, one current product-link pointer, one purchase mutex and one session
delegation table. Alembic has six revisions in one linear chain and one current head. Revision
`20261029_0003` belongs to ANY-709, `20261028_0005` to ANY-715 and
`20261031_0006` to ANY-765 and `20261110_0007` to ANY-766. The new migration
adds only `kernel_session_delegations`; it is not applied automatically by the API.

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
| `kernel_session_delegations` | Identity | Hash-only single-use PKCE codes and narrow Kernel tokens; parent-session deletion cascades. |
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
| `paid_access_states` | Access | Provider-neutral whole-user paid-access document and semantic revision, written atomically with supporting source facts. |
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
technical allowance. ANY-766 Step 3 adds `product-link-v3` in the same table;
its identity also pins one explicit fixed-per-cycle product/metric/unit/quantity
offer, with configured Kernel/LBX provenance. Historical documents are unchanged.
`commercial_product_heads` has primary key
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
fields immutable. ANY-765 writes `accepted-purchase:v2`, including the optional
SIMULATED technical terms and selected-meaning confirmation digest, separately
from full source/audit digests. Historical v2 full-digest acceptances and v1 stay
readable without invented limits; exact replay uses saved evidence rather than current
source configuration. The development fixture is disabled by default and
rejected in production.

ANY-766 Step 3 writes `accepted-purchase:v3` for v3 links, containing required
`purchased-technical-terms:v2` with `CONFIGURED_SOURCE` provenance. Terms pin the
mapping identity digest/revision, complete source/audit digest, account/selection,
commercial fingerprint and fresh manifest evidence. Buyer confirmation continues
to pin selected meaning separately. Quantities are strict integers in 0…2^53−1;
LBX commercial quantity retains its separate meaning. These versions require no
new table or migration. Readers predating Step 3 cannot consume these documents;
the reader compatibility floor must accompany the unchanged migration head.
Existing accepted subscriptions keep their quantity across republished links
and proven new cycles. Production derivation/HTTP delivery remains Step 5 work.

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
retaining the same operation/key. This policy applies only before the durable
deadline pause. Under the [2026-11-09 decision](decisions/0005-external-billing-boundary.md#accepted-unknown-recovery-and-lifecycle-metadata-decisions---2026-11-09),
a `paused` customer recovery row makes later explicit openings GET-only; empty
discovery and lease expiry cannot rearm CREATE. The original operation/evidence
remain intact. A saved receipt or identity conflict also prevents another POST;
point proof binds only against the current fence. Financial operations have a
unique intent/kind identity and a unique permanent account/kind/provider-object
binding. Their account/customer composite FK prevents
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
select one same-user/same-product primary subscription. Migration `20261031_0006`
adds nullable effective document/deadline, basis-observation reference and
primary-retirement fields. Shared source apply updates the effective projection
of an existing primary in its own transaction; it does not select a first primary.
The customer inventory job selects a first primary only after persisting bounded
product discovery and rechecking committed source observations, fences, purchase
versions and the current scope under the user lock. Hidden local nonterminal
sources remain relevant. Newcomers cannot replace an existing primary, and
retirement never promotes an older candidate automatically.
The baseline creates
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
positive proof anchors at most six hours of source trust to read-set start; incomplete
attempts preserve the existing deadline and complete support, while decisive
owned negative/conflict evidence reduces usability. Subsequent preparation
cannot overwrite monitored facts. ANY-765 assigns a resulting access revision
when the supporting observation causes a material paid-state change.
Step 1 alone added no DDL or worker; Steps 2–5 supply the running worker and
operations described below. See the
[operations runbook](../engineering/billing-background-operations.md).

`billing_state_observations` stores evidence whose core fields are immutable.
Its closed kinds are
`authoritative_subscription_read`, `target_product_discovery`,
`primary_selection`, and `deterministic_access_boundary`; database checks
enforce each kind's minimum provenance shape. DELETE is forbidden, and all
fields except `resulting_access_revision` are immutable. That field may be
assigned exactly once from `NULL` to a non-null value; once assigned, it cannot
be cleared or replaced. Migration `20261031_0006` requires an assigned revision
to be positive. The shared paid writer assigns the causal revision only when the
whole-user effective state changes; a semantic no-op retains the revision.
Versioned `target-product-discovery:v2` and `paid-access-cause:v1` evidence may
retain purchase provenance without an access scope.
`target-product-discovery:v3` stores scoped candidate conclusions and references
to the observations already committed by leased reconciliation. Inventory does
not apply those source facts again. A `primary-selection:v1` observation links
the chosen source to its discovery; selection, paid state, causal revision and
outbox share the final inventory transaction. Later inventory failures cannot
roll back earlier authoritative source/paid transactions.
Customer and financial restrictions retain their existing fence/lease
invalidation and reduce paid state in the same caller transaction. Customer
conflicts affect all dependent products; product restrictions preserve independent
products. Audited `select-primary` accepts only its subscription's primary case
and fresh original proof; unrelated financial reviews remain blocked.

`purchased_allowances` links a source component and product/metric quantity to
an external subscription. Quantity is non-negative. Migration `20261031_0006`
preserves existing UTC rows as `legacy-utc:v1` without inferring dates. New
`calendar:v1` rows retain inclusive dates and lossless calendar/accepted-terms
documents without UTC bounds; `timestamp:v1` rows retain explicitly zoned source
and frozen UTC bounds. Technical unit and terms are required for both new
shapes. Logical subscription/component/metric/cycle identity is unique.
PostgreSQL triggers prevent updates/deletes, including all new fields.

`paid_access_states` has at most one row per `(tenant_id, region, user_id)` and
stores a complete effective-state document with a non-null `access_revision`
slot. Migration `20261031_0006` enforces positive revisions, unchanged meaning
within a revision, increments of exactly one and no identity changes or deletes.
`access_invalidation_outbox` has the same unique scope. Its physical checks
require a positive pending revision and forbid `delivered_revision` from
exceeding it. Migration `20261031_0006` also requires nonnegative delivered
revisions and rejects identity changes, revision regression and deletion;
these guards do not implement delivery. The caller-transaction paid writer
canonicalizes the whole-user state, increments its revision and coalesces the
pending outbox revision atomically with source facts. Delivery remains later work.

## Durable operational tables

`external_billing_webhook_deliveries` retains bounded, redacted correlation and
evidence documents, receipt/processing timestamps and safe classifications from
older builds. The polling-only ANY-715 MVP retains this table/schema and all
history but has no receiver or inbox-processing writer. Historical JSON schemas
`billing-webhook-receipt:v1` / `billing-webhook-work:v1` and canonical text-backed
`WebhookDeliveryState` values (`pending`, `processed`, `ignored`) remain readable;
polling does not change those rows. No raw provider payload or authorization/card
material belongs here, and receipt state never grants access.

`billing_work_items` stores work/scope/state fields as plain text, bounded typed
payloads, priority, due time, attempt count, paired lease owner/expiry and nullable
`active_recovery_deadline_at` for the current financial send. This active deadline
is independent of mutable retry scheduling and changes only in the locked,
fenced financial send claim; GET recovery never renews it. It
is scheduling state, not commercial or access authority. The implemented
worker selects fixed work meanings; text storage does not make these decisions
semantically open. ANY-715 Step 2 adds
nonnegative `enqueue_generation`, nullable `last_attempt_started_at` and a partial
unique `(work_kind, coalescing_key)` index for subscription reconciliation/trust
expiry, enrollment sweep and the reserved inventory/create-deadline kinds.
ANY-715 Step 3 reuses permanent create-operation recovery keys for urgent GET
work and separate account/operation `external_create_deadline` keys for local
fixed two-hour escalation. Customer inventory coalesces by account/local customer,
while subscriptions retain account/local subscription keys. Recovery receipts,
original request/date/fences and customer active-send leases keep their existing
storage identity. Step 3 needs no additional table or migration beyond the
Step 2 worker migration `20261028_0005`. Inventory observations use
`customer-inventory:v1`; conflicts never grant access or rewrite bindings.

The pre-existing create-recovery index and customer-send lease identity remain
unchanged. Claims use paired finite ownership; completion preserves newer enqueue
generations. Binding atomically enrolls new canonical subscriptions. Source apply
atomically reschedules monitoring and the earliest supported trust/access deadline,
alongside paid state, causal revision and outbox writes for an existing primary.
Migration `20261028_0005` follows consolidated billing revision
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

Current plain-string state attributes are `BillingWorkItem.work_state` and
`ManualReviewCase.case_state`. Related work kinds, scope kinds, observation
completeness/result classifications, review reasons and error classifications
also retain plain-text representation. Recognized Portal decision subsets need
an explicit vocabulary owner; arbitrary source codes are not automatically
enums. This is existing representation debt under ANY-800 and the owning runtime
deliveries, not a permanent open-vocabulary exemption or permission for new
arbitrary states.

New/materially changed persisted contracts follow the
[internal-contract conventions](../engineering/CODING_CONVENTIONS.md#internal-contracts):
canonical enums with `PersistedEnumType`, symbolic use throughout producers,
consumers and active SQL, with focused parity checks when literal DDL is
necessary. PostgreSQL remains TEXT/VARCHAR. Frozen migrations and independent
wire/history assertions retain compatibility literals. Application retains
transition, transaction, lease and fencing ownership.

The repository guard derives the canonical inventory from the supplied root's
top-level declarations on every call. It prevents duplicate definitions and
protected imports through removed billing enum facades, including future
declarations without another inventory edit. Historical removed-enum
prohibitions remain independent. The guard is not a runtime assignment checker
or Python typechecker. This clarification does not implement enum narrowing,
change physical constraints or migrate any stored value.

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

## Kernel session delegation (ANY-766 Step 4)

`kernel_session_delegations` references `auth_sessions.id` with `ON DELETE CASCADE`.
It stores unique SHA-256 code/token hashes, the S256 challenge, fixed
`platform-kernel` audience and separate code/exchange/token deadlines. A check
constraint requires exchange time, token hash and token expiry to be either all
absent or all present. Raw credentials and a second user directory are absent.

Code issuance and atomic exchange acquire User → AuthSession → delegation locks
(the last lock applies to exchange), then recheck active status and parent
revocation/expiry. Codes last at most 60 seconds; tokens last at most 30 minutes
and never outlive the parent. `UserStatus.INACTIVE` is an explicit non-active
storage value; no deactivation endpoint is introduced. Existing password reset
revokes the parent sessions and logout deletes its parent.

Introspection uses one joined read of delegation/session/user, never updates
`last_seen_at` and never commits. Its deadline subtracts the configured
Portal–Kernel clock budget once. Internal reads share validation with existing
Portal identity without adopting public last-seen bookkeeping. Scope comes from
the existing user/session, and service permissions come from receiver settings.
The [contract bundle](../contracts/portal-kernel-paid/README.md#step-4-server-implementation)
records operation configuration, errors and remaining integration boundaries.
