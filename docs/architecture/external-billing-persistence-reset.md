# External Billing Persistence Reset

Status: implementation handoff under ADR 0005 and the accepted billing designs

## Authority and current baseline

This document is the durable `ANY-509` persistence and clean-reset handoff. It
is subordinate to, and cannot override, the following authority chain:

1. [ADR 0005: External Billing Boundary](decisions/0005-external-billing-boundary.md);
2. [External Billing Boundary Design](../superpowers/specs/2026-09-15-external-billing-boundary-design.md);
3. [Portal <-> Kernel Access Contract Design](../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md).

This is an implementation inventory, not a competing ADR. `ANY-504` controls
implementation order. `ANY-505` is complete and PR #113 is merged, so the
repository already classifies the direct-provider documentation and persistence
model as retained current-state context rather than target authority.

`ANY-457` is also complete. Normal API composition creates an empty
`PaymentProviderRegistry`; it does not initialize or mount CloudPayments, and
the frontend checkout path is deliberately unavailable. Retained
CloudPayments source, settings, ORM state, migrations, tests, and frontend code
are characterization and cleanup inputs only. External Billing is not, and
must never become, a `PaymentProviderAdapter`.

The current Portal-owned `Product`, `Plan`, `Order`, `Payment`, `Subscription`,
and `Entitlement` models describe the legacy implementation. They are not
target commercial authority.

## No-production reset premise

[ARCHITECTURE.md](../../ARCHITECTURE.md) states that Payment Portal is under
development and has no production CloudPayments subscribers or subscriptions.
[Product Scope](../PRODUCT.md) states that the Portal is not running as a
production billing service and has no production CloudPayments subscribers or
subscriptions to migrate. `ANY-504` and `ANY-509` therefore authorize a fresh
pre-production persistence baseline while those facts remain true. Existing
production deployment tooling does not, by itself, establish production
billing data or migration obligations.

**STOP condition:** if production billing data, customer data, active billing
clients, or another data-retention/cutover obligation appears before
`ANY-504` Step 4 begins destructive cleanup, Step 4 must stop. The clean-reset
strategy must then be replaced by an approved migration and cutover design;
the repository must not destroy or silently reinterpret that data.

No dual-write layer, old/new billing compatibility layer, or data-preserving
billing migration is required under the current premise.

## Current table disposition

The following classification covers all 26 current tables. `ANY-504` Step 3
may refine only the physical identity, session, and legal details explicitly
delegated to it.

| Current table | `ANY-509` disposition | Locked rationale |
| --- | --- | --- |
| `regions` | RETAIN WITH TARGET ADAPTATION | Contour identity remains valid; `ANY-504` Step 4 bootstrap must respect one-contour-per-instance rather than preserve cross-contour seed accidents. |
| `country_region_rules` | RETAIN WITH TARGET ADAPTATION | Local contour/country policy can remain; `default_payment_provider` is direct-provider legacy and is not part of the target model. |
| `users` | RETAIN WITH TARGET ADAPTATION | Canonical Portal UUID identity remains Portal-owned; `ANY-504` Step 3 owns final physical/runtime details. |
| `auth_sessions` | RETAIN WITH TARGET ADAPTATION | Portal auth/session is provider-independent; `ANY-504` Step 3 owns final characterization. |
| `magic_link_tokens` | RETAIN WITH TARGET ADAPTATION | Password-reset token storage is provider-independent; any checkout/entrypoint coupling is not a target invariant and is revalidated by `ANY-504` Step 3. |
| `password_reset_rate_limits` | RETAIN | Provider-independent identity/security infrastructure. |
| `legal_entities` | RETAIN WITH TARGET ADAPTATION | Portal legal identity remains Portal-owned; `ANY-504` Step 3 owns physical details. |
| `document_versions` | RETAIN WITH TARGET ADAPTATION | Versioned legal documents remain required. |
| `document_acceptances` | RETAIN WITH TARGET ADAPTATION | Append-only legal evidence remains required, but legacy `Plan.id`-bound recurring-consent semantics are transitional. `ANY-504` Step 3 must finalize provider-independent acceptance evidence that is directly bound to the exact accepted commercial fingerprint/offer and required legal-document versions. |
| `entrypoint_sessions` | RETAIN WITH TARGET ADAPTATION, ANY-504 STEP-3 HANDOFF | Retain only if `ANY-504` Step 3 confirms a provider-independent identity/legal/origin role. Current `Product`/`Bundle` foreign-key coupling must not survive as target commercial authority. |
| `products` | REPLACE WITH TARGET | Technical product identity comes from the Kernel capability manifest, not a Portal-owned commercial catalog. |
| `bundles` | REMOVE IN STEP 4 | Current Portal-owned bundle commerce is not target authority. No generic replacement is invented unless a later accepted product requirement needs one. |
| `bundle_products` | REMOVE IN STEP 4 | Depends on the obsolete Portal-owned bundle/product model. |
| `plans` | REPLACE WITH TARGET | External Billing owns commercial offers/tariffs; target Portal state is catalog projection + immutable mapping/purchase snapshot, not a Portal `Plan`. |
| `plan_price_components` | REPLACE WITH TARGET | Replaced by external catalog component facts and immutable mapping/purchase snapshots. |
| `plan_limits` | REPLACE WITH TARGET | Replaced by accepted fixed metric quantities and `purchased_allowances`; Portal does not own runtime remaining quota. |
| `checkout_sessions` | REMOVE IN STEP 4 | The target has `PurchaseIntent`; a linked prepared/unpaid subscription has no checkout-session TTL. |
| `orders` | REMOVE IN STEP 4 | There is no Portal-owned commercial Order in the target architecture. |
| `order_items` | REPLACE WITH TARGET | Commercial evidence becomes immutable accepted purchase snapshot/fingerprint, not an Order child model. |
| `payments` | REMOVE IN STEP 4 | External Billing owns payment lifecycle; Portal must not recreate a payment ledger. |
| `refunds` | REMOVE IN STEP 4 | External Billing owns refund/payment lifecycle; only necessary normalized evidence/conflicts belong in Portal. |
| `payment_provider_accounts` | REMOVE IN STEP 4 | One external billing account per contour is stable runtime/configuration scope, not a Portal-managed provider-account routing catalog. |
| `payment_webhook_events` | REPLACE WITH TARGET | Replace the direct-payment inbox with a minimal external-billing webhook delivery inbox containing safe correlation/evidence only. |
| `subscriptions` | REPLACE WITH TARGET | Replace Portal-owned lifecycle with a proven external-subscription projection and provider-neutral access statuses. |
| `entitlements` | REPLACE WITH TARGET | Replace old Plan/Order-derived entitlement rows with committed provider-neutral paid-access state and purchased allowances. |
| `subscription_events` | REPLACE WITH TARGET | Old Order/Payment/Refund audit chain is obsolete; target auditability comes from purchase snapshots, create-operation recovery state, webhook/reconciliation evidence, projection facts, and manual-review cases. |

`REPLACE WITH TARGET` records the Step-1 inventory decision. The target tables,
fields, constraints, provider-evidence gates, and reset sequence are defined in
the later sections of this completed handoff.

## Runtime and code-surface disposition

Every material current surface has an explicit owner and disposition. There is
no unowned "keep for now" category.

| Current surface | Disposition | Owner / boundary |
| --- | --- | --- |
| `app.models.identity` and `app.models.legal` | RETAIN / ADAPT | `ANY-504` Step 3 finalizes the physical identity/session/legal shape; `ANY-504` Step 4 carries that result into the clean baseline. |
| `app.models.catalog` | REPLACE WITH TARGET or REMOVE | `ANY-504` Step 4 removes the Portal-owned catalog graph; only target technical/catalog projections approved by the authoritative designs and completed `ANY-509` handoff replace it. |
| `app.models.commerce` | RETAIN / ADAPT `entrypoint_sessions`; otherwise REPLACE WITH TARGET or REMOVE | `ANY-504` Step 3 decides whether the provider-independent entrypoint role survives. `ANY-504` Step 4 removes checkout sessions, orders, payments, and refunds and adds only approved target persistence. |
| `app.models.providers` | REMOVE IN `ANY-504` STEP 4 | Portal-managed direct-provider accounts are not part of the target model. |
| `app.models.webhooks` and `app.models.subscriptions` | REPLACE WITH TARGET | `ANY-504` Step 4 removes the direct-payment inbox and Portal-owned subscription/entitlement graph and adds only the approved target projections and evidence storage. |
| `app.models.enums` | RETAIN / ADAPT IDENTITY AND LEGAL ENUMS; REMOVE OR REPLACE LEGACY BILLING ENUMS | `ANY-504` Step 3 owns final retained identity/legal vocabularies; Step 4 removes old catalog, commerce, provider, subscription, entitlement, and trial vocabularies instead of promoting them into target authority. |
| `app.models._shared` and `PersistedEnumType` | RETAIN / ADAPT | Preserve provider-independent SQLAlchemy and text-backed enum mechanics; Step 4 removes legacy subscription-scope/status SQL helpers with their consumers. |
| `app.models.__init__` | ADAPT IN `ANY-504` STEP 4 | Re-export the final retained Step-3 models and approved target models only; remove legacy billing exports. |
| Alembic revisions `20260707_0001` through `20260826_0005` | REPLACE WITH CLEAN BASELINE | `ANY-504` Step 4 replaces the pre-production migration chain after `ANY-504` Step 3 freezes retained identity/session/legal details; retained concepts are carried forward, not the legacy revision files as target authority. |
| `app.domains.identity.services.checkout` and its identity-router checkout presentation | REMOVE IN `ANY-504` STEP 4 | Remove the old direct-provider checkout. Target `PurchaseIntent` runtime is deferred to `ANY-504` Step 7. |
| `app.domains.identity.services.account` billing reads | REMOVE IN `ANY-504` STEP 4 | Remove old `Product` / `Plan` / `Order` / `Payment` / `Entitlement` lookups, including `load_payment_status()` and product-state resolution; preserve provider-independent authenticated user/session semantics. |
| `app.domains.billing.catalog` and `app.domains.billing.service.catalog` | REMOVE IN `ANY-504` STEP 4 | Remove the Portal-owned sellable catalog. Target catalog projection runtime is deferred to `ANY-504` Steps 6-7. |
| `app.domains.billing.service.account` and the current account router | REMOVE IN `ANY-504` STEP 4 | Remove Plan/Entitlement-shaped account subscription behavior. Any target account/billing projection is deferred to the applicable later runtime step. |
| Billing commercial-transition and lifecycle modules under `app.domains.billing.service` | REMOVE IN `ANY-504` STEP 4 | Remove behavior coupled to old Order/Payment/Refund/Subscription/Entitlement authority. Later external-billing ingestion and access derivation belong to `ANY-504` Steps 8-9. |
| Exported `start_trial()`, `SubscriptionStatus.TRIALING`, `EntitlementSource.TRIAL`, `Plan.trial_days`, and trial-backed entitlement reads | REMOVE IN `ANY-504` STEP 4 | The legacy trial lifecycle is Portal billing/access state. Free/guest/trial policy remains Kernel-owned unless `ANY-504` Step 3 reports a material, provider-independent contradiction. |
| `apps/api/app/commands/expire_subscriptions.py` | REMOVE IN `ANY-504` STEP 4 | It schedules the superseded Portal-owned subscription/entitlement lifecycle. It is not a target worker. |
| `app.payment_providers` registry/accounts/contracts stack | REMOVE IN `ANY-504` STEP 4 | Remove after old checkout consumers disappear. External Billing must not be registered or modeled as a `PaymentProviderAdapter`. |
| `app.integrations.cloudpayments/**` and `app.cloudpayments.py` | REMOVE IN `ANY-504` STEP 4 | Retained direct-provider implementation is deactivated characterization source only. It must not be generalized for External Billing. |
| `scripts/cloudpayments_sandbox_verify.py` and CloudPayments sandbox support | REMOVE IN `ANY-504` STEP 4 | Direct-provider sandbox verification is not part of the target integration. |
| Legacy order, payment, plan, product, subscription, webhook, and commercial persistence/query helpers | REMOVE or REPLACE IN `ANY-504` STEP 4 | Remove helpers whose only consumers are deleted; create only focused target query/storage mechanics justified by the approved target model. |
| Provider-independent identity, legal, password-reset, database, FastAPI DI, observability, Sentry, persistence-boundary, and architecture-guard code | RETAIN / ADAPT | Preserve these foundations; adapt only where removal of legacy billing callers or `ANY-504` Step 3's retained-shape decision requires it. |
| CloudPayments settings and retained manual-sandbox configuration | REMOVE IN `ANY-504` STEP 4 | Remove direct-provider configuration with its source. Remove `app.core.payment_api_limits` too if no provider-independent consumer survives. |

### Public API and frontend

The old public contracts are not compatibility requirements under the current
no-production premise.

| Current surface | Disposition | Owner / boundary |
| --- | --- | --- |
| `GET /api/catalog/products` | REMOVE IN `ANY-504` STEP 4 | Remove the Portal-owned sellable-catalog contract. Target catalog behavior belongs to `ANY-504` Steps 6-7. |
| `POST /api/auth/checkout-intent` | REMOVE IN `ANY-504` STEP 4 | Remove the direct-provider checkout contract. Target `PurchaseIntent` runtime belongs to `ANY-504` Step 7. |
| `GET /api/account/subscriptions` and `GET /api/account/subscriptions/{subscription_id}` | REMOVE IN `ANY-504` STEP 4 | Remove the Plan/Entitlement-shaped account contract. A target account/billing projection is deferred to later target runtime work. |
| `GET /api/auth/payment-status` | REMOVE IN `ANY-504` STEP 4 | Remove with `load_payment_status()` and the old Order/Payment model; no compatibility polling contract is retained. |
| `GET /api/auth/session` identity/session result | RETAIN / ADAPT | Preserve authenticated user/session semantics through `ANY-504` Step 3 and Step 4. |
| Optional `/api/auth/session?product=...` input and `product_state` output | REMOVE IN `ANY-504` STEP 4 | These are billing-derived extensions resolved through old Product/Plan/Order/Entitlement queries, not identity invariants. |
| Frontend catalog clients and presentation under `features/catalog` | REMOVE / REPLACE IN `ANY-504` STEP 4 | Stop consuming the removed Portal catalog API. Any target catalog client is deferred to `ANY-504` Steps 6-7. |
| Frontend checkout clients, ownership code, `provider-adapters.ts`, and `cloudpayments.d.ts` | REMOVE IN `ANY-504` STEP 4 | Remove direct-provider execution and types. A later target purchase flow must use the External Billing boundary, not this adapter. |
| Frontend account-subscription client and presentation | REMOVE / REPLACE IN `ANY-504` STEP 4 | Stop consuming the old subscription endpoints; target account projection is deferred to later target runtime work. |
| Payment-result polling of `/api/auth/payment-status` | REMOVE IN `ANY-504` STEP 4 | `/ru/payment-result` may remain only as a neutral informational shell until a later target flow explicitly owns replacement behavior. |
| Current `/ru`, `/ru/products`, `/ru/auth-checkout`, `/ru/account`, and `/ru/payment-result` route consumers | RETAIN NEUTRAL SHELL OR ADAPT IN `ANY-504` STEP 4 | They must not call removed APIs or retain CloudPayments execution code. Target catalog/purchase/account behavior remains owned by the named later runtime steps. |

### Tests and documentation

| Current surface | Disposition | Owner / boundary |
| --- | --- | --- |
| Old migration/schema tests and fixtures | REPLACE IN `ANY-504` STEP 4 | Verify the clean baseline and the retained Step-3 identity/session/legal shape instead of the old 26-table schema. |
| CloudPayments adapter, API, webhook, recurring, refund, sandbox, and deactivation tests/support | REMOVE IN `ANY-504` STEP 4 | Remove with retained direct-provider source; later External Billing tests must exercise the new boundary. |
| Old checkout, catalog, payment, refund, commercial-transition, subscription, entitlement, expiry, and trial tests | REMOVE or REPLACE IN `ANY-504` STEP 4 | Preserve only assertions that describe a retained provider-independent invariant; do not carry old commercial authority forward. |
| Identity, password-reset, legal, security, observability, persistence-boundary, and architecture tests | RETAIN / ADAPT | `ANY-504` Step 3 owns identity/session/legal changes; Step 4 adapts tests only where the clean baseline or removed billing extensions require it. |
| Frontend checkout-unavailable, payment-result, catalog, account-subscription, and provider tests | REMOVE or ADAPT IN `ANY-504` STEP 4 | Keep only neutral route/identity behavior that remains factual; target flow coverage belongs to later runtime steps. |
| `docs/architecture/payment-portal-data-model.md` | REWRITE IN `ANY-504` STEP 4 | Make it the authoritative current-state/as-built clean-schema reference, subordinate to the target authority chain for future billing semantics. |
| `docs/architecture/payment-providers.md` and its ANY-505 documentation guard | UPDATE IN `ANY-504` STEP 4 | Reclassify the document when direct-provider source is physically removed, and update the guard in the same change so it does not require a false retained-implementation classification. |
| `docs/product/ru-mvp.md` | UPDATE IN `ANY-504` STEP 4 | Remove stale ANY-71-era catalog/trial language and product-flow descriptions tied to old catalog/subscription contracts. |
| `ARCHITECTURE.md`, `docs/PRODUCT.md`, `docs/RELIABILITY.md`, and `README.md` | ADAPT IF FACTUALLY REQUIRED IN `ANY-504` STEP 4 | Update only current-state or operational claims changed by physical schema/runtime removal, including obsolete expiry/commercial-transition operations. |
| `docs/generated/db-schema.md` and `docs/generated/openapi.json` | REGENERATE IN `ANY-504` STEP 4 | Use repository generation tooling; never hand-edit generated documentation. |
| Superseded ADRs and historical billing plans | RETAIN AS HISTORY | They do not become target authority and must not be rewritten to compete with ADR 0005. |
| `docs/architecture/deployment.md` stale active-CloudPayments and ANY-71 statements | CORRECTED IN `ANY-509` STEP 1 | The current deployment description now records deactivated normal runtime and cites the accepted target authority without redesigning future topology. |

## Current durable-work gap

There is no durable PostgreSQL job queue, background-work table, reconciliation
scheduler, invalidation outbox, or target reconciliation subsystem in the
current repository. `apps/api/app/commands/expire_subscriptions.py` is retained
legacy scheduled behavior for the old subscription/entitlement model and is
removed in `ANY-504` Step 4; it is not a target work substrate.

Step 1 identified this gap without designing its replacement. The completed
handoff defines the shared durable work substrate, its persistence contract,
and its verification obligations in the target-model and verification sections
below; later `ANY-504` runtime steps still own scheduling behavior.

## Related roadmap and executable-plan disposition

| Work item | Disposition |
| --- | --- |
| `ANY-168` - Implement CloudPayments recurring payments integration | Still **In Progress**, but directly conflicts with the deactivated runtime and `ANY-504` Step 4 cleanup. It must be canceled, superseded, or otherwise made non-executable before Step 4 begins. `ANY-509` must not implement or revive it. |
| `ANY-163` | Blocked CloudPayments umbrella; historical/transitional context only and no authority for new direct-provider work. |
| `ANY-79`, `ANY-286`, and `ANY-287` | Must not execute as written against the old entitlement contract. Formal rewrite, close, or supersession remains owned by `ANY-504` Step 10. |
| `ANY-497` | Canceled; historical `ANY-407` context only. |
| `docs/exec-plans/active/ANY-135-split-alembic-baseline.md` | Describes completed current-state work. It is characterization evidence only, not executable target guidance. Broad exec-plan housekeeping is outside `ANY-509`. |
| `docs/exec-plans/active/ANY-76-refund-result-status.md` | Describes completed current-state work. It is characterization evidence only, not executable target guidance. Broad exec-plan housekeeping is outside `ANY-509`. |

## `ANY-504` Step 3 handoff boundary

`ANY-509` locks retention intent and provider-independent invariants. It does
not pre-empt `ANY-504` Step 3's ownership of the final physical and runtime
shape of identity, session, and legal persistence. Before destructive Step-4
work begins, Step 3's final repository state must be reread as the baseline for
all retained identity/session/legal tables.

Step 3 must leave append-only acceptance evidence that directly binds the exact
accepted commercial fingerprint or offer to the required set of versioned
legal documents. Legacy `Plan.id`-bound recurring consent is not the target
contract. `entrypoint_sessions` may survive only if Step 3 confirms a
provider-independent identity, legal, or origin role; current Product/Bundle
foreign keys do not carry target authority.

Step 3 must also resolve the transitional multi-contour identity behavior.
Registration currently accepts a client-supplied `region`, and current tests
allow independent `ru` and `eu` accounts for the same email, while the target
deployment permits one contour per instance. `ANY-504` Step 4 must not delete
the `eu`, DE, or ES bootstrap rows while identity regression tests approved by
Step 3 still require that behavior.

If Step 3 discovers a provider-independent Portal obligation that genuinely
requires retained non-billing trial state, it must report that as a material
contradiction. It must not silently preserve the old Plan/Subscription/
Entitlement trial model.

## Target persistence contract

The planned clean baseline will add exactly these 15 target tables; none is
implemented by `ANY-509`:

1. `capability_manifest_projections`
2. `external_billing_catalog_projections`
3. `commercial_mapping_revisions`
4. `external_billing_customers`
5. `billing_product_access_scopes`
6. `purchase_intents`
7. `external_create_operations`
8. `external_subscriptions`
9. `billing_state_observations`
10. `purchased_allowances`
11. `paid_access_states`
12. `external_billing_webhook_deliveries`
13. `billing_work_items`
14. `access_invalidation_outbox`
15. `manual_review_cases`

External Billing remains the commercial authority. These tables hold only
validated projections, Portal orchestration, normalized evidence, and the
provider-neutral paid-access result. They do not form a shadow catalog,
invoice, payment, refund, or provider-account ledger. Kernel remains the
authority for technical product and metric identity and for actual usage and
remaining quota.

There is one configured external billing account per deployed contour for
MVP. `external_billing_account_id` is a stable, non-secret text configuration
value used as persistence scope; there is no `external_billing_accounts`
table. Provider credentials, webhook secrets, Widget signing material, card
data, payment credentials, authorization headers, and raw tokens must never be
stored in these tables.

Complete manifest/catalog projections and immutable mapping, accepted
purchase, observation, work-payload, review-evidence, and effective-access
documents below are schema-versioned structured JSON, not arbitrary
dictionaries. Their owning runtime step must define explicit Pydantic
contracts and validate the whole document before persistence or use.

### Relational scope-integrity strategy

Surrogate UUIDs remain the row identities, but a surrogate-only FK is
insufficient where the referencing row also carries correctness-critical
semantic scope. Step 4 therefore creates narrow composite alternate keys and
composite FKs for these chains:

- mapping revision -> exact billing account and offer on a purchase;
- customer -> exact billing account and canonical user on a purchase or
  subscription;
- purchase -> exact customer/account/user/product/mapping provenance on a
  linked subscription;
- subscription -> exact user/product on a primary access-scope selection;
- subscription -> exact product on a purchased allowance.

The repeated subscription `user_id` is deliberate: without it PostgreSQL could
not prove that `billing_product_access_scopes.primary_subscription_id` belongs
to that exact user/product row. It is not an independent source of truth because
the composite customer FK forces it to equal the canonical customer-slot user.
These alternate keys exist only as FK targets; they do not introduce new
business identities, Portal-owned product/catalog rows, or provider-specific
semantics. Scope-bearing evidence references follow the same rule below; opaque
audit/work references that carry no duplicated relational scope remain ordinary
surrogate FKs.

Reviewing all 15 tables under this rule yields no reason to add another table or
remove a scope column. The three projection/revision tables have no Portal-owned
catalog FK; the customer/purchase/subscription/access/allowance chain receives
the composite guards above; observation references enforce scope where scope is
repeated; `paid_access_states` and `access_invalidation_outbox` already require
the same finalized Step-3 tenant/region/user representation; webhook, work, and
manual-review scope references remain intentionally typed/opaque because they do
not repeat relational account/user/product columns. Nullable relationships
remain nullable only for the stated lifecycle reason: no selected primary yet,
no linked purchase for a discovered subscription, optional evidence/work links,
or later-proven provider bindings. Required provenance and accepted evidence
remain non-null or are covered by the explicit Step-3 -> Step-4 handoff.

### Matrix conventions

- `UUID`, `text`, `integer`/`bigint`, `timestamptz`, and `jsonb` name storage
  type families; exact SQLAlchemy spelling and incidental constraint/index
  names follow repository conventions. If a row does not state a default,
  there is no database default.
- `RESTRICT` means referenced correctness/audit history cannot be deleted;
  `SET NULL` is used only where losing a convenience linkage cannot alter the
  retained evidence meaning.
- Evidence is classified independently as
  `ACCEPTED_ARCHITECTURE_REQUIREMENT`, `DOCUMENTED_PROVIDER_FACT`,
  `VENDOR_CONFIRMED`, `CONFIRMED_ON_TEST`, or `GATED / UNVERIFIED`.
- The implementation gate is independently `STEP_4_SAFE`,
  `PHASE_0_GATED`, or `LATER_STEP_RUNTIME`; the owning later `ANY-504` step is
  named for every `LATER_STEP_RUNTIME` entry. `LATER_STEP_RUNTIME` columns are
  still created in the Step-4 baseline unless the row explicitly says
  otherwise; the classification defers behavior, not the physical slot.
- Closed provider-neutral vocabularies named here are canonical text-backed
  `StrEnum` values in `app.models.enums`. Open, later-owned vocabularies remain
  `text` with no enum or database check until the named owner closes them.
- Canonical ORM ownership remains in `app.models`. Application services own
  transactions, idempotency, and state transitions; focused persistence
  helpers own SQL mechanics. No provider network call may run inside an open
  business transaction, and this model does not imply a repository per table,
  generic unit of work, parallel pure-domain entity graph, or provider
  framework.
- Unless a narrative invariant is explicitly classified otherwise, it is an
  `ACCEPTED_ARCHITECTURE_REQUIREMENT`; its gate is the `STEP_4_SAFE` DDL
  constraint or the `LATER_STEP_RUNTIME` owner named in that table/paragraph.

### `capability_manifest_projections`

**Owner/source of truth.** Portal owns the current last-known-good (LKG)
projection; Kernel's complete capability manifest is the source. There is one
atomically replaced row per tenant/contour. A failed or partial sync changes
neither the row nor freshness.

| Field | Storage; null/default | Key / FK delete behavior | Constraint or index | Mutability | Evidence | Gate / owner |
| --- | --- | --- | --- | --- | --- | --- |
| `projection_id` | UUID; not null | PK | Unique identity | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `tenant_id` | text; not null | Scope key | With `region`, unique LKG scope and lookup index | Immutable for row; changed scope replaces row | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `region` | text; not null | Scope key | With `tenant_id`, unique LKG scope | Immutable for row | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `schema_version` | integer; not null | - | Matches the numeric Portal <-> Kernel capability-manifest wire field | Replaced atomically | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 6) |
| `manifest_version` | text; not null | - | Non-empty; deterministic version lookup index | Replaced atomically | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 6) |
| `generated_at` | timestamptz; not null | - | - | Replaced atomically | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 6) |
| `last_complete_sync_at` | timestamptz; not null | - | Freshness lookup index | Advances only with complete replacement | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 6) |
| `manifest_document` | jsonb; not null | - | Whole typed document validated against `schema_version` | Replaced atomically | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 6) |

The document contains only tenant/region scope, products (`product_id`,
`enabled`), and usage metrics (`metric_key`, owning `product_id`, `unit`,
`enabled`). `product_id` and `metric_key` stay Kernel identifiers and never
gain Portal-catalog FKs. The row is current projection authority for admission,
not historical commercial authority; pinned mapping/purchase documents are the
historical evidence. Retain the current LKG row until a complete replacement
commits. A `last_complete_sync_at` older than 24 hours blocks only new mapping
publication and purchases; it never rewrites or revokes pinned history. That
24-hour rule is `ACCEPTED_ARCHITECTURE_REQUIREMENT` and
`LATER_STEP_RUNTIME` (`ANY-504` Steps 6-7).

### `external_billing_catalog_projections`

**Owner/source of truth.** Portal owns a normalized complete LKG projection;
External Billing owns the catalog facts. There is one atomically replaced row
per configured billing account.

| Field | Storage; null/default | Key / FK delete behavior | Constraint or index | Mutability | Evidence | Gate / owner |
| --- | --- | --- | --- | --- | --- | --- |
| `projection_id` | UUID; not null | PK | Unique identity | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `external_billing_account_id` | text; not null | Configuration scope | Unique LKG scope | Immutable for row | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `schema_version` | text; not null | - | Non-empty | Replaced atomically | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 6) |
| `catalog_version` | text; nullable | - | Lookup index when present | Replaced atomically | `GATED / UNVERIFIED` | `STEP_4_SAFE` opaque slot; semantics closed by `ANY-504` Steps 5-6 |
| `catalog_digest` | text; not null | - | Deterministic normalized digest; indexed | Replaced atomically | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 6) |
| `last_complete_sync_at` | timestamptz; not null | - | Freshness lookup index | Advances only with complete replacement | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 6) |
| `catalog_document` | jsonb; not null | - | Whole typed document validated against `schema_version` | Replaced atomically | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 6) |

Opaque offer/component identifiers and normalized material commercial facts
may appear in the document, but vendor payloads and status enums may not become
Application contracts. The row is current admission input, not historical
commercial authority. Retain the current LKG row until complete replacement.
The same 24-hour new-sales rule and classification as the capability manifest
applies. External offer/component IDs never receive FKs to a Portal-owned
catalog.

### `commercial_mapping_revisions`

**Owner/source of truth.** Portal owns the privileged publication decision;
the revision pins Kernel manifest and normalized External Billing catalog
inputs. Published rows are immutable, append-only historical authority for
the purchases that reference them.

| Field | Storage; null/default | Key / FK delete behavior | Constraint or index | Mutability | Evidence | Gate / owner |
| --- | --- | --- | --- | --- | --- | --- |
| `mapping_revision_id` | UUID; not null | PK; part of composite purchase/subscription-reference targets | `UNIQUE(mapping_revision_id, external_billing_account_id)` and `UNIQUE(mapping_revision_id, external_billing_account_id, billing_offer_id)` in addition to PK | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `external_billing_account_id` | text; not null | Configuration scope; part of composite purchase-reference target | Part of offer/revision unique key and current-selection index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `billing_offer_id` | text; not null | Opaque external identity, no catalog FK; part of composite purchase-reference target | With account and revision, unique | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `revision_number` | bigint; not null | Publication sequence | `> 0`; `UNIQUE(account, offer, revision_number)` | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `manifest_version` | text; not null | Pinned external version, no projection FK | Indexed with publication scope | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `catalog_version` | text; nullable | Pinned external version, no projection FK | - | Immutable | `GATED / UNVERIFIED` | `STEP_4_SAFE` opaque slot; semantics closed by `ANY-504` Steps 5-6 |
| `catalog_digest` | text; not null | Pinned digest, no projection FK | - | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `mapping_schema_version` | text; not null | - | Non-empty | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `mapping_document` | jsonb; not null | - | Whole typed immutable document validated against schema version | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 6) |
| `published_at` | timestamptz; not null | - | Current-selection/audit index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 6) |
| `published_by_principal` | text; not null | Provider-neutral audited actor identity; no customer `users` FK | Non-empty; audit lookup index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 6 finalizes authentication/principal integration) |

The mapping document covers the whole offer/component set and uses the closed
component vocabulary `UNCLASSIFIED | CAPABILITY_BEARING | COMMERCIAL_ONLY`,
plus external-usage-reporting classification and resolved Kernel
`product_id`/`metric_key` bindings. Publication inserts the next monotonic
revision; there are no draft rows or mutable `is_current` flag. The highest
revision in the exact account/offer scope is current. Direct row edits are not
the production workflow. Revisions are retained while referenced and purchases
never rebind. `published_by_principal` is a stable provider-neutral audit
principal, not a customer identity or a new operator-account model; Step 6
maps the authenticated publishing actor into that value.

### `external_billing_customers`

**Owner/source of truth.** Portal owns the durable customer slot and binding
integrity; External Billing owns provider customer lifecycle truth. The slot is
identity/correlation, not customer-profile authority.

| Field | Storage; null/default | Key / FK delete behavior | Constraint or index | Mutability | Evidence | Gate / owner |
| --- | --- | --- | --- | --- | --- | --- |
| `customer_id` | UUID; not null | PK; part of composite scope-reference target | `UNIQUE(customer_id, external_billing_account_id, user_id)` in addition to PK | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `external_billing_account_id` | text; not null | Configuration scope | In both required unique keys | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `user_id` | UUID; not null | FK `users.id`; `RESTRICT` | `UNIQUE(account, user_id)` | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `billing_customer_key` | text; not null | Portal allocation identity | Non-empty; `UNIQUE(account, billing_customer_key)` | Immutable; never reused | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `provider_customer_id` | text; nullable | Opaque external binding | Indexed when present; no pre-Phase-0 uniqueness | Bind once or change only through audited recovery | `GATED / UNVERIFIED` | `STEP_4_SAFE` nullable slot; identity constraints are `PHASE_0_GATED` and owned by `ANY-504` Step 5 |
| `binding_state` | text-backed enum; not null, default `unbound` | - | Check `unbound | bound | identity_conflict`; state lookup index | Application transition only | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 7) |
| `binding_updated_at` | timestamptz; not null | - | - | Updated with binding state | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 7) |
| `created_at` | timestamptz; not null | - | - | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |

`identity_conflict` is durable and fail-closed; it is not merely a log entry.
This state is not outbound-create uncertainty, which belongs only in
`external_create_operations`. Customer-slot rows cannot be hard-deleted in a
way that permits key reuse and are retained for the life of the key plus
correctness/audit obligations. Email, phone, and name are neither stored here
nor used as identity. Exact `outer_id` behavior, provider-side restoration,
and any provider-ID uniqueness are `GATED / UNVERIFIED`, `PHASE_0_GATED`, and
owned by `ANY-504` Step 5 before Step 7 uses them.

### `billing_product_access_scopes`

**Owner/source of truth.** Portal owns this provider-neutral serialization
scope. It is the row-lock boundary for purchase ownership and deterministic
primary selection, not commercial authority.

| Field | Storage; null/default | Key / FK delete behavior | Constraint or index | Mutability | Evidence | Gate / owner |
| --- | --- | --- | --- | --- | --- | --- |
| `access_scope_id` | UUID; not null | PK; part of composite observation-reference target | `UNIQUE(access_scope_id, user_id, product_id)` in addition to PK | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `user_id` | UUID; not null | FK `users.id`; `RESTRICT` | With `product_id`, unique serialization scope | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `product_id` | text; not null | Kernel identity; no Portal catalog FK | `UNIQUE(user_id, product_id)` | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `primary_subscription_id` | UUID; nullable | Composite FK `(primary_subscription_id, user_id, product_id)` to `external_subscriptions(subscription_id, user_id, product_id)`; `RESTRICT` | Index for reverse lookup; FK deletion cannot clear the primary | Only audited deterministic Application transition | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` FK; transition is `LATER_STEP_RUNTIME` (`ANY-504` Steps 7-9) |
| `updated_at` | timestamptz; not null | - | - | Updated with primary decision | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 7-9) |

The canonical first-row acquisition protocol is a short PostgreSQL transaction:

1. `INSERT` the `(user_id, product_id)` scope with
   `ON CONFLICT (user_id, product_id) DO NOTHING`;
2. `SELECT` the unique row by `(user_id, product_id) FOR UPDATE`, whether this
   transaction inserted it or a concurrent transaction won the insert;
3. while holding that row lock, acquire/create the canonical
   `(external_billing_account_id, user_id)` customer slot using the customer
   protocol below and lock that customer row `FOR UPDATE`;
4. inspect/reuse/create the single unresolved customer-create operation, then
   inspect the current purchase, subscription, and create-operation state for
   the product scope and create or reuse the scope-holding `PurchaseIntent` and
   any other required durable local state;
5. commit all required local intent/state before any external call; only after
   commit may provider I/O occur.

PostgreSQL's unique-index conflict handling makes a concurrent losing insert
wait for the winner and converge on the same committed row. No caller may
create a scope-holding purchase flow or make an external create call before it
has completed this acquire/get-and-lock sequence. After the transaction, only
the purchase/create operation that the transaction durably established as the
scope-holding flow may proceed; a concurrent attempt must reuse the applicable
idempotent flow or return the provider-neutral occupied-scope result. This
ownership is represented by the existing purchase, operation, and linked-
subscription state; it does not add an owner column or table. Rollback leaves
no newly established scope-holding flow and grants no permission for an
external effect. This protocol also applies when the scope row already exists
and requires no separate lock table. The global lock order for a normal purchase
is therefore `product access scope -> customer slot`; no purchase path may
acquire those two locks in the reverse order.

Before locking this row, Step 8 performs the Step-5-proven complete discovery
and authoritative point reads, normalizes the complete target-product
candidate set, and durably inserts the observation. The short decision
transaction then locks this row and re-reads the union of observed candidates
and known local non-terminal candidates. The zero/one/many algorithm applies
only to first-primary selection when no trusted primary exists:

- zero eligible candidates leaves `primary_subscription_id = NULL`;
- exactly one eligible candidate selects it only when it is the linked
  purchase subscription;
- exactly one eligible candidate that is another subscription leaves
  `primary_subscription_id = NULL` and retains or creates conflict/manual-review
  evidence;
- two or more eligible candidates leave `primary_subscription_id = NULL` and
  retain or create conflict/manual-review evidence.

When a trusted primary already exists, a newly discovered eligible competitor
does not clear or replace it. The competitor contributes no access and produces
conflict/manual-review evidence. A financially or commercially blocked primary
remains selected but produces no paid access while blocked. The primary is
cleared only by the accepted authoritative terminal transition or an explicit
audited resolution allowed by the architecture, and clearing it never
auto-promotes another known candidate.

The decision is persisted as a second observation. Amount, agreement age, row
age, and worker completion order are forbidden heuristics. No separate
primary-decision generation/digest/attempt subsystem is created. The algorithm
is `ACCEPTED_ARCHITECTURE_REQUIREMENT` and `LATER_STEP_RUNTIME` (`ANY-504`
Steps 8-9). Scope rows are retained while any purchase, subscription, access,
observation, or review history depends on them. Every change to
`primary_subscription_id` must commit through that audited deterministic
Application transition before any referenced subscription could be deleted;
the `RESTRICT` FK prevents a delete from bypassing primary-selection evidence
or paid-access consequences. Ended subscription history remains retained.

### `purchase_intents`

**Owner/source of truth.** Portal owns the purchase orchestration intent and
immutable evidence of what the user accepted. External Billing remains the
commercial authority; this row replaces legacy `CheckoutSession` and `Order`
without becoming either.

| Field | Storage; null/default | Key / FK delete behavior | Constraint or index | Mutability | Evidence | Gate / owner |
| --- | --- | --- | --- | --- | --- | --- |
| `purchase_intent_id` | UUID; not null | PK | Unique identity | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `user_id` | UUID; not null | FK `users.id`; part of composite customer-scope FK; `RESTRICT` | User/product orchestration index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `external_billing_account_id` | text; not null | Configuration scope; part of composite customer and mapping FKs | Account/offer lookup index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `customer_id` | UUID; not null | Composite FK `(customer_id, external_billing_account_id, user_id)` to `external_billing_customers(customer_id, external_billing_account_id, user_id)`; `RESTRICT` | Customer/purchase lookup index; part of composite subscription-reference target | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `product_id` | text; not null | Kernel identity; no Portal catalog FK | User/product orchestration index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `billing_offer_id` | text; not null | Opaque external identity; no catalog FK | Account/offer lookup index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `mapping_revision_id` | UUID; not null | Composite FK `(mapping_revision_id, external_billing_account_id, billing_offer_id)` to `commercial_mapping_revisions(mapping_revision_id, external_billing_account_id, billing_offer_id)`; `RESTRICT` | Lookup index; with purchase scope, composite subscription-reference target | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `accepted_commercial_fingerprint` | text; not null | - | Non-empty; audit lookup index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `client_idempotency_key` | text; not null | Client request identity | Non-empty; `UNIQUE(external_billing_account_id, user_id, client_idempotency_key)` | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE`; replay/conflict behavior is `LATER_STEP_RUNTIME` (`ANY-504` Step 7) |
| `state` | text-backed enum; not null, default `created` | - | Check `created | preparing | awaiting_external_result | linked | resolved_no_external_effect | failed_before_external_effect | manual_review`; state index | Application transition only | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 7) |
| `accepted_snapshot_schema_version` | text; not null | - | Non-empty | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `accepted_snapshot` | jsonb; not null | - | Whole typed immutable document validated against schema version | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 7) |
| Accepted legal-evidence binding (logical requirement; physical field names deferred) | Final columns, type family, cardinality, and nullability are the Step-3 -> Step-4 handoff; no single UUID column is assumed here | Must directly reference the append-only legal/commercial acceptance evidence finalized by Step 3 with deletion behavior that cannot orphan an accepted purchase | Every accepted purchase must have a durable complete binding to the exact accepted commercial fingerprint/offer and all required versioned legal-document evidence | Immutable after acceptance | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` only after `ANY-504` Step 3 supplies the physical FK/cardinality/nullability shape to Step 4 |
| `created_at` | timestamptz; not null | - | - | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `state_updated_at` | timestamptz; not null | - | State/recovery index | Updated with state | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 7) |
| `resolved_at` | timestamptz; nullable | - | - | Set once on terminal resolution | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 7-8) |

The typed accepted snapshot pins exact external component references, the
mapping revision, Kernel `product_id`/`metric_key` bindings, fixed accepted
integer quantities, the material commercial fingerprint, and the exact legal
acceptance/document-version evidence finalized by Step 3. Copying a legacy
generic or `Plan.id`-bound consent after the fact is insufficient. Business
serialization uses `billing_product_access_scopes(user_id, product_id)`. The
semantic idempotency identity is exactly
`(external_billing_account_id, user_id, client_idempotency_key)`: one key names
one logical public purchase request by one canonical user inside one configured
billing boundary, independent of product or offer. An exact replay returns the
same flow; reuse of that identity with different immutable request semantics is
an idempotency conflict rather than a new purchase. Step 4 installs the unique
constraint; Step 7 owns request comparison and the transport/runtime result.
Rows and accepted evidence are retained for recovery and commercial/legal
audit; accepted fields never rebind or mutate. The accepted legal-evidence
binding is mandatory semantically, but Step 3 alone decides its final columns,
FK target/cardinality, and nullability. Step 4 must implement that result
without adding another target table, weakening append-only evidence, or
permitting an accepted purchase to become unbound.

Step 4 also installs composite alternate keys
`UNIQUE(purchase_intent_id, customer_id)` and
`UNIQUE(purchase_intent_id, external_billing_account_id, user_id, product_id)`,
plus
`UNIQUE(purchase_intent_id, customer_id, external_billing_account_id, user_id,
product_id, mapping_revision_id)`. The leading UUID remains the purchase
identity; these wider keys exist only as relational targets so create operations
and linked subscriptions cannot contradict the purchase's scope or mapping
provenance.

The canonical purchase-to-subscription relationship is
`external_subscriptions.purchase_intent_id`. `purchase_intents` carries no
independent subscription FK; its optional proven linked subscription is
derived by the reverse relationship. Linking and the purchase state transition
commit atomically in the owning Application transaction.

### `external_create_operations`

**Owner/source of truth.** Portal owns one unified uncertainty record for
customer, agreement, and subscription create calls. The provider owns whether
an external object was actually created. This is not a generic job queue.

| Field | Storage; null/default | Key / FK delete behavior | Constraint or index | Mutability | Evidence | Gate / owner |
| --- | --- | --- | --- | --- | --- | --- |
| `create_operation_id` | UUID; not null | PK | Unique identity | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `operation_kind` | text-backed enum; not null | - | Check `customer | agreement | subscription` | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `customer_id` | UUID; not null | FK `external_billing_customers.customer_id`; `RESTRICT`; with `purchase_intent_id`, composite purchase/customer FK when the purchase is present | Customer/state lookup index; partial `UNIQUE(customer_id) WHERE operation_kind = 'customer' AND resolved_at IS NULL` | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `purchase_intent_id` | UUID; nullable | Composite FK `(purchase_intent_id, customer_id)` to `purchase_intents(purchase_intent_id, customer_id)`; `RESTRICT` | Purchase lookup index; required for `agreement` and `subscription`, forbidden for `customer` | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `request_correlation_key` | text; not null | Outbound request identity | Non-empty; indexed; exact provider correlation semantics not constrained | Immutable | `GATED / UNVERIFIED` | `STEP_4_SAFE` opaque slot; semantics closed by `ANY-504` Steps 5 and 7 |
| `operation_state` | text; not null | - | Open vocabulary; state/recovery index; must represent durable `unknown` | Application transition only | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 7-8 close the vocabulary) |
| `unknown_since` | timestamptz; nullable | - | Paired with deadline when state is `unknown` | Set when outcome becomes ambiguous; then immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 7-8) |
| `unknown_recovery_deadline_at` | timestamptz; nullable | - | When present equals `unknown_since + 2 hours`; deadline index | Set with `unknown_since`; immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` constraint; recovery owned by `ANY-504` Step 8 |
| `recovery_hint_schema_version` | text; nullable | - | Required with recovery document | Immutable after UNKNOWN | `GATED / UNVERIFIED` | `STEP_4_SAFE` bounded opaque slot; schema closed by `ANY-504` Steps 5 and 8 |
| `recovery_hint_document` | jsonb; nullable | - | Bounded, safe typed document; paired with schema version | Immutable after UNKNOWN | `GATED / UNVERIFIED` | `STEP_4_SAFE` bounded opaque slot; semantics owned by `ANY-504` Step 8 |
| `bound_external_object_id` | text; nullable | Opaque proven external identity | Indexed when present; no pre-Phase-0 uniqueness | Set only from proof; thereafter immutable | `GATED / UNVERIFIED` | `STEP_4_SAFE` nullable slot; identity constraints are `PHASE_0_GATED`, owned by `ANY-504` Step 5 |
| `created_at` | timestamptz; not null | - | - | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `updated_at` | timestamptz; not null | - | Recovery scan index with state/deadline | Updated with transition | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 7-8) |
| `resolved_at` | timestamptz; nullable | - | - | Set once on proven resolution | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |

`unknown_since` and its deadline are both null or both present; the two-hour
interval is fixed. An ambiguous call keeps its business scope held, permits
read-only recovery, survives restart, and never blind-retries create. Zero
matches is never proof of absence. At the fixed deadline it escalates to
manual review. `billing_work_items` schedules recovery. Records remain for
identity/recovery/audit after resolution.

The customer row supplies cross-product serialization specifically for customer
creation; it does not replace product-scope business serialization. For a normal
purchase, the customer sub-protocol runs only after the transaction has locked
the canonical `(user_id, product_id)` access-scope row:

1. Generate a `billing_customer_key` only as a candidate for insertion of an
   absent customer slot, then attempt the insert with
   `ON CONFLICT (external_billing_account_id, user_id) DO NOTHING`.
2. Select the canonical `(external_billing_account_id, user_id)` customer row
   `FOR UPDATE`. If the insert lost to an existing slot, discard the losing
   candidate without comparing it to the persisted key. The immutable key
   already stored on the canonical row is the sole Portal key and is reused by
   this purchase flow.
3. A `UNIQUE(external_billing_account_id, billing_customer_key)` conflict with
   another customer slot is instead a local key-allocation collision. It never
   reuses the other customer's row and never becomes `identity_conflict`; before
   any external effect, the owning Step-7 implementation may fail the local
   allocation or retry with a new candidate while restarting the transaction in
   the same `product access scope -> customer slot` lock order.
4. Inspect unresolved `operation_kind = customer` operations for the canonical
   `customer_id` and either reuse/block on the existing operation or insert the
   sole unresolved customer-create operation. Create or reuse the
   `PurchaseIntent` and remaining product-scope state in the same short
   transaction, then commit before provider I/O.
5. Perform provider I/O only after commit; record a definite result or durable
   `unknown` in a later short transaction. While the operation is unresolved,
   every product flow for that customer reuses or waits on it; an ambiguous
   result is recovered by reads and is never blind-retried.

Two first purchases for different products may hold different product-scope
rows and then contend on the same customer row. The loser waits, discards its
candidate key if the winner inserted the slot, and reuses the canonical slot and
any unresolved customer-create operation. A customer-recovery worker that does
not mutate product-scope state may lock only the customer/create-operation
state; it must never acquire a product-scope lock afterward, so it cannot create
a reverse `customer slot -> product access scope` path.

The partial unique constraint on unresolved customer-create rows is
`STEP_4_SAFE`: it uses the closed operation kind and `resolved_at`, not the
later-owned operation-state vocabulary. An audited safe release or proven bind
sets `resolved_at`; `unknown` and escalated manual-review operations remain
unresolved and continue to hold the customer slot. This closes the cross-product
race without assuming provider `outer_id` uniqueness or deduplication.

### `external_subscriptions`

**Owner/source of truth.** External Billing is subscription/commercial truth;
Portal owns a normalized provider-neutral projection. A row exists only after
the external subscription is proven and uses a Portal UUID independent of any
unproven provider identifier.

| Field | Storage; null/default | Key / FK delete behavior | Constraint or index | Mutability | Evidence | Gate / owner |
| --- | --- | --- | --- | --- | --- | --- |
| `subscription_id` | UUID; not null | PK; part of composite scope-reference targets | `UNIQUE(subscription_id, product_id)`, `UNIQUE(subscription_id, user_id, product_id)`, and `UNIQUE(subscription_id, external_billing_account_id, user_id, product_id)` in addition to PK | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `external_billing_account_id` | text; not null | Configuration scope; part of composite customer, purchase, and mapping FKs | Account/customer index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `customer_id` | UUID; not null | Composite FK `(customer_id, external_billing_account_id, user_id)` to `external_billing_customers(customer_id, external_billing_account_id, user_id)`; `RESTRICT` | Account/customer index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `user_id` | UUID; not null | With customer and account, composite FK to `external_billing_customers`; `RESTRICT` | `UNIQUE(subscription_id, user_id, product_id)` in addition to PK; user/product/status index | Immutable; deliberate denormalized scope protected by FK | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `product_id` | text; not null | Kernel identity; no Portal catalog FK; part of composite purchase FK and primary-subscription reference target | Customer/product/status index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `purchase_intent_id` | UUID; nullable | Composite FK `(purchase_intent_id, customer_id, external_billing_account_id, user_id, product_id, mapping_revision_id)` to the same columns on `purchase_intents`; `RESTRICT` | Partial `UNIQUE(purchase_intent_id)` when non-null; provenance/reverse-link lookup index | Set only as part of the proven-link Application transition; thereafter immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` FK/uniqueness; linking is `LATER_STEP_RUNTIME` (`ANY-504` Steps 7-8) |
| `mapping_revision_id` | UUID; nullable | Composite FK `(mapping_revision_id, external_billing_account_id)` to `commercial_mapping_revisions(mapping_revision_id, external_billing_account_id)`; `RESTRICT`; participates in the purchase FK when linked | Provenance lookup index | Immutable once set; required when `purchase_intent_id` is set | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `external_subscription_id` | text; nullable | Opaque external binding | Indexed when present; no pre-Phase-0 uniqueness/check | Set only from proof; correction only through audited recovery | `GATED / UNVERIFIED` | `STEP_4_SAFE` nullable slot; canonical identity is `PHASE_0_GATED`, owned by `ANY-504` Step 5 |
| `external_agreement_id` | text; nullable | Opaque external binding | Indexed when present; no pre-Phase-0 uniqueness/check | Set only from proof; correction only through audited recovery | `GATED / UNVERIFIED` | `STEP_4_SAFE` nullable slot; lifetime/isolation uniqueness is `PHASE_0_GATED`, owned by `ANY-504` Step 5 |
| `lifecycle_status` | text-backed enum; not null | - | Check `active | inactive | ended`; projection index | Authoritative transition only | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 8-9) |
| `financial_access_status` | text-backed enum; not null | - | Check `allowed | blocked`; projection index | Authoritative transition only | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 8-9) |
| `commercial_access_status` | text-backed enum; not null | - | Check `eligible | ineligible`; projection index | Authoritative transition only | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 8-9) |
| `last_authoritative_read_at` | timestamptz; not null | - | Freshness/reconciliation index | Advances with successful authoritative read | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |
| `projection_valid_until` | timestamptz; not null | - | Freshness/deadline index | Recomputed only by authoritative transition | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 8-9) |
| `reconciliation_lease_owner` | text; nullable | - | Lease scan index with expiry; paired-nullability `CHECK` with expiry | Claim/release only | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` check; behavior is `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |
| `reconciliation_lease_expires_at` | timestamptz; nullable | - | Paired-nullability `CHECK` with owner; expiry index | Claim/renew/release only | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` check; behavior is `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |
| `reconciliation_fencing_token` | bigint; not null, default `0` | - | `>= 0`; monotonically increases on claim | Monotonic only | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |
| `latest_observation_id` | UUID; nullable | Composite FK `(latest_observation_id, subscription_id)` to `billing_state_observations(observation_id, subscription_id)`; `RESTRICT` | Observation lookup index; referenced row must be `authoritative_subscription_read` | Updated only with the authoritative read that produced the current projection | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` FK; kind validation/transition is `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |
| `created_at` | timestamptz; not null | - | - | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `updated_at` | timestamptz; not null | - | - | Updated with projection | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 8-9) |

The nullable external identifier slots are safe to create, but Step 4 installs
no provider-specific canonical-identity, `outer_id`, agreement lifetime,
terminal-revival, or provider-ID uniqueness rule. A proven row must carry the
identity evidence required by the Step-5 result before Step 8 inserts it.
Ended rows are not automatically hard-deleted; identity, provenance, recovery,
and audit history is retained. Raw provider statuses remain Integration-owned.
This table's canonical nullable FK is the only persisted
PurchaseIntent-to-subscription link. The partial uniqueness rule makes the
reverse relationship zero-or-one and prevents contradictory links; no mirror
FK exists on `purchase_intents`. The composite FK guarantees that a linked
subscription and purchase have the same canonical customer, billing account,
user, product, and mapping provenance. The separate composite customer FK makes
the deliberately repeated subscription `user_id` structural rather than
independent truth. A Step-4 `CHECK` requires `mapping_revision_id` whenever
`purchase_intent_id` is present. Reconciliation lease owner and expiry are
either both null or both non-null, enforced by
`(reconciliation_lease_owner IS NULL AND reconciliation_lease_expires_at IS
NULL) OR (reconciliation_lease_owner IS NOT NULL AND
reconciliation_lease_expires_at IS NOT NULL)`.

`latest_observation_id` names only the
`authoritative_subscription_read` whose normalized facts produced the current
subscription projection. The composite FK enforces subscription ownership;
Step 8 enforces the referenced observation kind and projection-causality
invariant in the same Application transition. No observation-kind discriminator
is duplicated on this table.

### `billing_state_observations`

**Owner/source of truth.** Portal owns append-only, minimized, normalized
evidence explaining decisions; it is not commercial/access authority, a raw
provider event store, or a second business state machine.

| Field | Storage; null/default | Key / FK delete behavior | Constraint or index | Mutability | Evidence | Gate / owner |
| --- | --- | --- | --- | --- | --- | --- |
| `observation_id` | UUID; not null | PK; part of composite observation-reference targets | `UNIQUE(observation_id, access_scope_id)` and `UNIQUE(observation_id, subscription_id)` in addition to PK | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `observation_kind` | text-backed enum; not null | - | Check `authoritative_subscription_read | target_product_discovery | primary_selection | deterministic_access_boundary`; kind/time index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `external_billing_account_id` | text; not null | Configuration scope | Account/kind/time index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `user_id` | UUID; nullable | FK `users.id`; `RESTRICT` | User/product/time audit index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `product_id` | text; nullable | Kernel identity; no Portal catalog FK | User/product/time audit index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `access_scope_id` | UUID; nullable | Composite FK `(access_scope_id, user_id, product_id)` to `billing_product_access_scopes(access_scope_id, user_id, product_id)`; `RESTRICT` | Scope/time audit index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `subscription_id` | UUID; nullable | Composite FK `(subscription_id, external_billing_account_id, user_id, product_id)` to the same columns on `external_subscriptions`; `RESTRICT` | Subscription/time audit index; mutually exclusive with `purchase_intent_id` | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `purchase_intent_id` | UUID; nullable | Composite FK `(purchase_intent_id, external_billing_account_id, user_id, product_id)` to the same columns on `purchase_intents`; `RESTRICT` | Purchase/time audit index; `CHECK(subscription_id IS NULL OR purchase_intent_id IS NULL)` | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `work_item_id` | UUID; nullable | FK `billing_work_items.work_item_id`; `SET NULL` | Work/audit index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `basis_observation_id` | UUID; nullable | Composite self-FK `(basis_observation_id, access_scope_id)` to `billing_state_observations(observation_id, access_scope_id)`; `RESTRICT` | Basis/decision lookup index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `observed_at` | timestamptz; not null | - | Kind/time and scope/time indexes | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `effective_at` | timestamptz; nullable | - | Effective-boundary index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `evidence_schema_version` | text; not null | - | Non-empty | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `evidence_document` | jsonb; not null | - | Whole bounded typed document validated for kind/schema | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 8-9) |
| `completeness_classification` | text; not null | - | Open vocabulary; audit index | Immutable | `GATED / UNVERIFIED` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 5 and 8 close the vocabulary) |
| `result_classification` | text; not null | - | Open vocabulary; audit index | Immutable | `GATED / UNVERIFIED` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 5 and 8 close the vocabulary) |
| `resulting_access_revision` | bigint; nullable | Logical link to same user scope in `paid_access_states`; physical FK shape follows Step-3/4 scope handoff | `> 0` when present; user/revision audit index | Null or set once; never changed | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 9) |
| `created_at` | timestamptz; not null | - | - | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |

Step 4 must install a provider-independent kind-shape `CHECK` that enforces at
least these row-local non-null requirements (additional references remain
allowed when meaningful):

- `authoritative_subscription_read`: `subscription_id IS NOT NULL`;
- `target_product_discovery`: `user_id`, `product_id`, and `access_scope_id`
  are all non-null;
- `primary_selection`: `access_scope_id` and `basis_observation_id` are both
  non-null;
- `deterministic_access_boundary`: `access_scope_id`, `subscription_id`, and
  `effective_at` are all non-null, so the affected product scope, durable source
  fact, and access-reducing boundary are identifiable.

It also requires `user_id` and `product_id` whenever `access_scope_id`,
`subscription_id`, or `purchase_intent_id` is present. The composite FKs then
force every repeated account/user/product value to agree with every referenced
scope-bearing row. A basis observation is forced into the same access scope as
the decision, and a subscription's `latest_observation_id` can reference only
an observation for that subscription. A separate Step-4 `CHECK` enforces
`subscription_id IS NULL OR purchase_intent_id IS NULL`: when an observation
references a subscription, its purchase provenance is derived exclusively
through the subscription's immutable nullable
`external_subscriptions.purchase_intent_id`. An observation may reference a
purchase directly only when it does not also reference a subscription. This
keeps discovered subscriptions with no linked purchase valid while making a
contradictory `S2`/`P1` pair unrepresentable.

The Step-4 `CHECK` enforces the provider-independent row-local shape and
non-contradictory provenance, and the composite FKs enforce existence plus
relational scope agreement. Two cross-row observation-kind invariants remain
with their runtime owners because a normal FK cannot inspect the referenced
row's kind without duplicating that state:

- a `primary_selection.basis_observation_id` must have
  `observation_kind = target_product_discovery`; Steps 8-9 own validation before
  insert and the corresponding application/audit verification;
- `external_subscriptions.latest_observation_id` must have
  `observation_kind = authoritative_subscription_read`; Step 8 owns validation
  before updating the current projection pointer and verifies that the same
  authoritative read produced the stored projection.

The composite FKs already enforce the same access scope or subscription for
these references. No `observation_kind` copy is added to another table. The
remaining later-owned kind checks and provider-specific result/completeness
vocabularies do not make observations event-sourced authority or duplicate
mutable subscription/access state.

An authoritative-read document contains only normalized material facts needed
to reproduce the Application decision, including commercial verification and
required source/cycle facts. A discovery document contains the complete
normalized target-product candidate set. A primary-selection document records
the deterministic zero/one/many result and selected/retained outcome and links
to its discovery through `basis_observation_id`. A deterministic-boundary
document records the local fact/deadline that allowed an access-reducing commit
without provider HTTP. Payloads are bounded and redacted: no raw response,
webhook body, payment history, or invoice ledger. Evidence meaning is immutable;
only the one-time resulting-revision linkage may be populated. Rows remain
queryable while current/historical subscriptions, purchases, access revisions,
reviews, or operational audit depend on them.

### `purchased_allowances`

**Owner/source of truth.** Portal owns the stable allowance identity and frozen
provider-neutral purchased fact. External Billing owns source commercial/cycle
facts; Kernel owns actual usage and remaining quota.

| Field | Storage; null/default | Key / FK delete behavior | Constraint or index | Mutability | Evidence | Gate / owner |
| --- | --- | --- | --- | --- | --- | --- |
| `allowance_id` | UUID; not null | PK | Unique stable usage identity | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `subscription_id` | UUID; not null | Composite FK `(subscription_id, product_id)` to `external_subscriptions(subscription_id, product_id)`; `RESTRICT` | Subscription/cycle lookup index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `source_component_id` | text; not null | Opaque concrete external component identity; no catalog FK | Subscription/component/cycle lookup index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `product_id` | text; not null | Kernel identity; no Portal catalog FK | Product/metric lookup index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `metric_key` | text; not null | Kernel identity; no Portal catalog FK | Product/metric lookup index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `quantity` | bigint; not null | - | `quantity >= 0` | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE`; authoritative source is `PHASE_0_GATED`, owned by `ANY-504` Step 5 |
| `provider_cycle_key` | text; nullable | Opaque cycle correlation | Indexed; no pre-Phase-0 unique constraint | Immutable once proven | `GATED / UNVERIFIED` | `STEP_4_SAFE` nullable slot; cycle identity/uniqueness is `PHASE_0_GATED`, owned by `ANY-504` Step 5 |
| `provider_cycle_start` | timestamptz; nullable | Raw normalized source bound | Paired with provider cycle end | Immutable | `GATED / UNVERIFIED` | `STEP_4_SAFE` nullable slot; semantics owned by `ANY-504` Steps 5 and 9 |
| `provider_cycle_end` | timestamptz; nullable | Raw normalized source bound | Paired with provider cycle start | Immutable | `GATED / UNVERIFIED` | `STEP_4_SAFE` nullable slot; semantics owned by `ANY-504` Steps 5 and 9 |
| `period_start` | timestamptz; not null | Frozen AccessSnapshot wire bound | With `period_end`, check `period_start < period_end` | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `period_end` | timestamptz; not null | Frozen AccessSnapshot wire bound | With `period_start`, check `period_start < period_end` | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `created_at` | timestamptz; not null | - | - | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |

Raw cycle bounds are both null or both present. A collapsed/invalid effective
interval is never widened into a usable row. Same-cycle block/unblock reuses
the same `allowance_id` and Kernel usage identity. Step 4 deliberately omits a
logical provider-cycle uniqueness constraint until Phase 0 proves the cycle
key and same/new-cycle behavior. There is no `remaining` field.
Allowance rows are retained with their source subscription and paid-access
audit history.

### `paid_access_states`

**Owner/source of truth.** Portal owns the current committed provider-neutral
paid-access snapshot. External Billing facts are inputs; Kernel consumes the
result and remains usage/quota authority. Absence means implicit revision `0`
with empty grants and allowances and causes no write. A row is created only by
the first material paid-access transition.

| Field | Storage; null/default | Key / FK delete behavior | Constraint or index | Mutability | Evidence | Gate / owner |
| --- | --- | --- | --- | --- | --- | --- |
| `paid_access_state_id` | UUID; not null | PK | Unique row identity | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `tenant_id` | Logical text scope value; explicit-column nullability is the Step-3/4 handoff | Canonical user/contour scope | Part of required semantic uniqueness | Immutable scope | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` after `ANY-504` Step 3 fixes physical representation |
| `region` | Logical text scope value; explicit-column nullability is the Step-3/4 handoff | Canonical user/contour scope | Part of required semantic uniqueness | Immutable scope | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` after `ANY-504` Step 3 fixes physical representation |
| `user_id` | UUID; not null | FK to the Step-3 canonical Portal user; `RESTRICT` | With the finalized tenant/region representation, one row per semantic scope | Immutable scope | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` after `ANY-504` Step 3 fixes FK/unique shape |
| `access_revision` | bigint; not null | Scope-local revision | `access_revision > 0`; monotonic | Incremented only with semantic document change | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 9) |
| `effective_state_schema_version` | text; not null | - | Non-empty | Updated only with semantic document change | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 9) |
| `effective_state_document` | jsonb; not null | - | Whole typed provider-neutral document validated against schema version | Updated atomically with revision and outbox | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 9-10) |
| `committed_at` | timestamptz; not null | - | - | Updated with semantic commit | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 9) |

The only intentionally delegated physical decision in the target billing model
is whether `tenant_id` and `region` are columns here or are losslessly implied
by the canonical Step-3 user/contour key. Step 4 must install a PK/FK/unique
shape that serializes exactly `(tenant_id, region, canonical Portal user_id)`
and use the identical shape in `access_invalidation_outbox` and AccessSnapshot.
The effective document contains no provider IDs or statuses. Every semantic
grant/allowance change updates the document, increments revision, and upserts
the outbox in one transaction. GET/read paths never create or mutate this row.
The current row is access authority; immutable mapping, purchase, observation,
and review evidence supplies history, so there is no row per old revision.
The current row is retained while the canonical user is known.

All writers that can commit a semantic paid-access change for a scope must use
one serialization protocol. In a short transaction they first lock the
existing canonical Step-3 user row that anchors the finalized
`(tenant_id, region, user_id)` scope with `SELECT ... FOR UPDATE`, then read the
latest committed `paid_access_states` row and all relevant committed facts,
derive the complete effective state, and compare it with the current semantic
document. The user row is the stable lock anchor even when the access-state row
does not yet exist; locking it is intentionally slightly broader than locking
one product because the stored snapshot is the complete effective state across
independent products for that user scope. The final one-contour Step-3 mapping
must provide an existing canonical user-row anchor deterministically identified
by every semantic access scope. Step 4 installs the persistence structure and
constraints needed to support this protocol; Step 9 implements the runtime
paid-access writer and serialization behavior. Sharing an anchor may serialize
more work but cannot weaken safety.

If the effective state changed, the same transaction inserts revision `1` when
the state row is absent, or updates revision `N` to `N + 1` when it exists, and
upserts `access_invalidation_outbox.pending_revision` to the maximum of its
current value and the new revision. It then commits state, revision, causative
observation linkage, and outbox together. If the state is semantically
unchanged, it creates no revision. Every access writer acquires the canonical
user lock before reading/locking access state or outbox rows, so two independent
product transitions cannot derive from the same stale snapshot or overwrite
one another. Provider I/O and other long-running work occur before this short
transaction; facts used for derivation are re-read after acquiring the lock.

A deadlock, serialization failure, or unexpected uniqueness conflict aborts
the whole transaction. The worker must retry by reacquiring the same user lock
and re-deriving from newly read committed facts and effective state; it must
never retry only the failed `UPDATE`, reuse a previously derived whole-state
document, or advance the outbox separately. This is a focused PostgreSQL
row-lock contract, not a generic locking framework.

### `external_billing_webhook_deliveries`

**Owner/source of truth.** Portal owns receipt/processing evidence. External
Billing owns the event. The inbox is a correlation and priority hint only;
neither delivery nor payload grants access.

| Field | Storage; null/default | Key / FK delete behavior | Constraint or index | Mutability | Evidence | Gate / owner |
| --- | --- | --- | --- | --- | --- | --- |
| `delivery_id` | UUID; not null | PK, local durable inbox identity | Unique identity | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `external_billing_account_id` | text; not null | Configuration scope | Account/receipt index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `provider_event_id` | text; nullable | Opaque external correlation | Indexed when present; no pre-Phase-0 uniqueness | Immutable | `GATED / UNVERIFIED` | `STEP_4_SAFE` nullable slot; dedup semantics are `PHASE_0_GATED`, owned by `ANY-504` Step 5 |
| `payload_hash` | text; not null | Redacted body correlation | Non-empty; indexed | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `correlation_schema_version` | text; not null | - | Non-empty | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `correlation_document` | jsonb; not null | - | Whole bounded typed safe-hints document | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |
| `evidence_schema_version` | text; not null | - | Non-empty | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `evidence_document` | jsonb; not null | - | Whole bounded/redacted typed document; never raw payload | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |
| `processing_state` | text; not null | - | Open vocabulary; processing/receipt index | Application transition only | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8 closes the vocabulary) |
| `received_at` | timestamptz; not null | - | Receipt scan index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `processing_started_at` | timestamptz; nullable | - | - | Set by processing transition | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |
| `processed_at` | timestamptz; nullable | - | - | Set once on terminal processing result | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |
| `last_error_classification` | text; nullable | - | Safe classification only | Updated by processing transition | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |

Full provider bodies, authorization material, secrets, card/payment fields, and
payment history are forbidden. Delivery evidence is retained for deduplication,
correlation, incident reconstruction, and the applicable operational/legal
period; it never replaces authoritative reads or `billing_state_observations`.

### `billing_work_items`

**Owner/source of truth.** Portal owns one shared PostgreSQL durable work
substrate for create recovery, discovery, reconciliation, and deterministic
access-reducing deadlines. It is scheduling state, not business authority.

| Field | Storage; null/default | Key / FK delete behavior | Constraint or index | Mutability | Evidence | Gate / owner |
| --- | --- | --- | --- | --- | --- | --- |
| `work_item_id` | UUID; not null | PK | Unique identity | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `work_kind` | text; not null | - | Open vocabulary; kind/due/state index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8 closes the vocabulary) |
| `scope_kind` | text; not null | Typed local reference discriminator | Open vocabulary; scope lookup index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8 closes the vocabulary) |
| `scope_reference` | text; not null | Stable local scope/reference value | With kind, scope lookup index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |
| `coalescing_key` | text; nullable | Scheduling identity | Indexed; exact partial uniqueness deferred until applicable work kinds/states close | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8 installs reviewed coalescing constraints) |
| `payload_schema_version` | text; not null | - | Non-empty | Immutable for the scheduled item | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `payload_document` | jsonb; not null | - | Whole bounded safe typed document | Immutable for the scheduled item | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |
| `priority` | integer; not null, default `0` | - | Due-work index with kind/state/time | Set on scheduling; may increase when urgent evidence arrives | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |
| `next_attempt_at` | timestamptz; not null | - | Due-work index with state/priority | Updated on retry/reschedule | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |
| `attempt_count` | integer; not null, default `0` | - | `>= 0` | Monotonic | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |
| `work_state` | text; not null | - | Open vocabulary; due-work index | Claim/transition only | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8 closes the vocabulary) |
| `lease_owner` | text; nullable | - | Paired-nullability `CHECK` with expiry; claim index | Claim/renew/release only | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` check; behavior is `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |
| `lease_expires_at` | timestamptz; nullable | - | Paired-nullability `CHECK` with owner; expiry index | Claim/renew/release only | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` check; behavior is `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |
| `last_error_classification` | text; nullable | - | Safe classification only | Updated after attempts | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |
| `created_at` | timestamptz; not null | - | - | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `updated_at` | timestamptz; not null | - | - | Updated with scheduling state | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |

Urgency is a priority/cadence on this table, never a second queue. In-memory
work, FastAPI `BackgroundTasks`, RabbitMQ, or Kafka cannot be correctness
authority for MVP. Invalidation remains in its dedicated coalesced outbox.
Open work-kind/state values intentionally receive no premature persisted enum
or database check. Step 4 nevertheless installs the provider-neutral lease
shape check
`(lease_owner IS NULL AND lease_expires_at IS NULL) OR (lease_owner IS NOT NULL
AND lease_expires_at IS NOT NULL)`. Pending/retry history is retained until
safely resolved; operational cleanup may later remove unreferenced terminal
scheduling rows without deleting business/evidence records.

### `access_invalidation_outbox`

**Owner/source of truth.** Portal owns durable, coalesced notification delivery
state. `paid_access_states` owns the semantic revision being notified.

| Field | Storage; null/default | Key / FK delete behavior | Constraint or index | Mutability | Evidence | Gate / owner |
| --- | --- | --- | --- | --- | --- | --- |
| `outbox_id` | UUID; not null | PK | Unique row identity | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `tenant_id` | Logical text scope value; explicit-column nullability is the Step-3/4 handoff | Canonical user/contour scope | Part of required semantic uniqueness | Immutable scope | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` after `ANY-504` Step 3 fixes physical representation |
| `region` | Logical text scope value; explicit-column nullability is the Step-3/4 handoff | Canonical user/contour scope | Part of required semantic uniqueness | Immutable scope | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` after `ANY-504` Step 3 fixes physical representation |
| `user_id` | UUID; not null | Same canonical user FK/delete rule as `paid_access_states` | `UNIQUE` on the finalized semantic tenant/region/user scope | Immutable scope | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` after `ANY-504` Step 3 fixes FK/unique shape |
| `pending_revision` | bigint; not null | Scope-local revision | `>= 0`; `pending_revision >= delivered_revision` | Monotonic maximum only | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 9-10) |
| `delivered_revision` | bigint; not null, default `0` | Scope-local acknowledgement | `>= 0`; never beyond revision actually sent | Monotonic only | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 10) |
| `attempt_count` | integer; not null, default `0` | - | `>= 0` | Reset/increment only by delivery transition | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 10) |
| `next_attempt_at` | timestamptz; not null | - | Due-delivery index | Updated on coalesce/retry | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 10) |
| `last_error_classification` | text; nullable | - | Safe classification only | Updated on delivery attempt | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 10) |
| `created_at` | timestamptz; not null | - | - | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `updated_at` | timestamptz; not null | - | - | Updated on state change | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 10) |

The scope representation must exactly match `paid_access_states` and
AccessSnapshot. A semantic access commit atomically upserts the maximum pending
revision. An acknowledgement can advance only through the revision actually
sent; it cannot clear a newer in-flight commit or move backward. The coalesced
row is retained while a paid-access state exists or delivery is outstanding.

### `manual_review_cases`

**Owner/source of truth.** Portal owns durable operational evidence and an
audited resolution trail for conflicts/uncertainty. A case is never access or
commercial authority.

| Field | Storage; null/default | Key / FK delete behavior | Constraint or index | Mutability | Evidence | Gate / owner |
| --- | --- | --- | --- | --- | --- | --- |
| `review_case_id` | UUID; not null | PK | Unique identity | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `reason_code` | text; not null | - | Stable open vocabulary; reason/state index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 7-9 close codes when workflows exist) |
| `scope_kind` | text; not null | Local reference discriminator | Open vocabulary; scope index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 7-9) |
| `scope_reference` | text; not null | Stable local scope/reference value | With kind, scope lookup index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 7-9) |
| `evidence_schema_version` | text; not null | - | Non-empty | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `evidence_document` | jsonb; not null | - | Whole bounded/redacted typed document | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 7-9) |
| `case_state` | text; not null | - | Open vocabulary; state index | Audited transition only | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 7-9 close the vocabulary) |
| `created_at` | timestamptz; not null | - | State/time index | Immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `STEP_4_SAFE` |
| `resolved_at` | timestamptz; nullable | - | - | Set once with resolution | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 7-9) |
| `resolved_by_principal` | text; nullable | Provider-neutral audited actor identity; no customer `users` FK | Non-empty and required when `resolved_at` is set; operator audit index | Set once with resolution | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 7-9 finalize authentication/principal integration) |
| `resolution_schema_version` | text; nullable | - | Required with resolution document | Set once | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 7-9) |
| `resolution_document` | jsonb; nullable | - | Whole bounded/redacted typed audited proof; paired with schema version and resolution timestamp | Set once; immutable | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 7-9) |

A resolution may bind a proven object or release a held scope after audited
proof. It cannot directly activate entitlement, invent allowance quantity, or
rebind historical mapping/purchase evidence. Cases and their resolution proof
are retained for the correctness/audit period of the affected history.
`resolved_by_principal` is a stable provider-neutral audit principal, not a
customer identity or a new operator-account subsystem; the owning runtime step
maps its authenticated resolving actor into that value.

## Durable evidence-source matrix

Current mutable projections and logs alone are never sufficient to explain a
material paid-access transition.

| Fact or decision to reconstruct | Durable source | Authority role | Evidence | Gate / runtime owner |
| --- | --- | --- | --- | --- |
| Accepted mapping, commercial fingerprint, fixed quantities, and legal-document versions | Immutable `commercial_mapping_revisions`, `purchase_intents.accepted_snapshot`, and Step-3 append-only acceptance evidence | Historical acceptance/provenance, not current provider truth | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 3, 6, and 7) |
| Ambiguous create and recovery decision | `external_create_operations` | Portal uncertainty/recovery authority; not provider object truth | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 7-8) |
| Webhook receipt and correlation | `external_billing_webhook_deliveries` | Evidence/priority hint only | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |
| Successful authoritative read or reconciliation facts | `billing_state_observations(authoritative_subscription_read)` linked to local subscription/purchase/work | Normalized evidence; External Billing remains fact authority | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 8-9) |
| Complete candidate discovery before first-primary decision | `billing_state_observations(target_product_discovery)` linked to user/product scope | Immutable decision input, not current subscription authority | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 8) |
| Deterministic zero/one/many primary decision | `billing_state_observations(primary_selection)` linked to its basis observation and scope | Immutable decision evidence; current primary remains in the scope row | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 8-9) |
| Deterministic access-reducing due boundary | `billing_state_observations(deterministic_access_boundary)` with affected fact/deadline | Immutable local-boundary evidence | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Step 9) |
| Conflict and operator resolution | `manual_review_cases` with bounded evidence and audited resolution | Operational evidence only | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 7-9) |
| Current effective semantic state and notification progress | `paid_access_states` plus atomic `access_invalidation_outbox`; causative observation carries `resulting_access_revision` | Current Portal paid-access authority and delivery state | `ACCEPTED_ARCHITECTURE_REQUIREMENT` | `LATER_STEP_RUNTIME` (`ANY-504` Steps 9-10) |

## Phase 0 provider-evidence gate register

Provider-neutral nullable opaque slots identified above are safe in the clean
baseline. The provider-specific rule in each row below remains absent until
`ANY-504` Step 5 retains sufficient stand evidence. Step 5 owns evidence and
the reviewed forward migration, if any; the named consumer step owns runtime
use. Provider-specific identifiers stay at the Integration/persistence edge as
opaque evidence/bindings and may not appear in Portal-Kernel contracts or
canonical provider-neutral Application/Domain contracts.

| Gated question or constraint | Current evidence | Safe Step-4 storage | Forbidden before evidence | Later owner |
| --- | --- | --- | --- | --- |
| Exact Widget `ident_type` | `DOCUMENTED_PROVIDER_FACT`: `ident_type=6` is a candidate only, never accepted production truth | No canonical enum/check required | Hard-coding `6` as production identity semantics | `PHASE_0_GATED`: `ANY-504` Step 5; Widget use in Step 7 |
| Exact `billing_customer_key` to LBX `users.outer_id` behavior, drift/recovery, and provider-side restoration | `GATED / UNVERIFIED` | Customer key plus nullable opaque provider customer ID and durable conflict state | Treating `outer_id` as proven identity, auto-rebinding, or profile matching | `PHASE_0_GATED`: Step 5; customer runtime Step 7 and recovery Step 8 |
| Widget/server authorization independent of presentation flags | `GATED / UNVERIFIED` | No extra persistence required | Treating hidden/disabled UI controls as authorization | `PHASE_0_GATED`: Step 5; enforcement Step 7 |
| Maximum Widget credential lifetime and old-token overlap/remint behavior | `GATED / UNVERIFIED` | Credentials remain runtime secrets; no token persistence here | Persisting signing material or assuming a safe lifetime/overlap | `PHASE_0_GATED`: Step 5; Widget runtime Step 7 |
| Canonical LBX subscription identity and whether `subscriptions.subscription_id` is binding while `outer_id` is only recovery hint | `GATED / UNVERIFIED` | Portal UUID plus nullable opaque subscription/agreement slots | Provider-ID uniqueness, canonical binding, or `outer_id` recovery semantics | `PHASE_0_GATED`: Step 5; discovery/reconciliation Step 8 |
| Agreement isolation, stable subscription-to-agreement binding, and no agreement reuse across historical subscriptions | `GATED / UNVERIFIED` | Nullable opaque agreement slot and retained historical subscription rows | Lifetime agreement/subscription uniqueness or reuse assumptions | `PHASE_0_GATED`: Step 5; creation Step 7 and reconciliation Step 8 |
| Authoritative material-term read set and complete match/mismatch/incomplete semantics | `GATED / UNVERIFIED` | Typed observation slots with open completeness/result text | Treating an incomplete or non-authoritative read as commercial proof | `PHASE_0_GATED`: Step 5; normalization/reconciliation Step 8 and access Step 9 |
| Prepaid blocking semantics | `GATED / UNVERIFIED` | Provider-neutral financial status and normalized observation evidence | Mapping a vendor payment/status field directly to access | `PHASE_0_GATED`: Step 5; access projection Step 9 |
| Fixed quantity authoritative source | `GATED / UNVERIFIED` | Immutable non-negative integer `quantity` | Deriving quantity from an unproven field or mutable runtime remaining | `PHASE_0_GATED`: Step 5; purchase Step 7 and allowance projection Step 9 |
| Provider cycle identity/bounds and same-cycle/new-cycle behavior | `GATED / UNVERIFIED` | Nullable opaque cycle key/raw bounds and immutable effective bounds | Provider-cycle unique constraint or new usage identity rule | `PHASE_0_GATED`: Step 5; allowance projection Step 9 and Kernel runtime Step 10 |
| Actual deployed customer subscription-list completeness, visibility, and concurrency behavior | `GATED / UNVERIFIED` | Discovery observation can store a bounded complete normalized candidate set | Assuming list completeness or using list order as primary selection | `PHASE_0_GATED`: Step 5; discovery/reconciliation Step 8 |
| Provider-specific safe absence predicate for automatic scope release, if one exists | `GATED / UNVERIFIED` | Held scope, UNKNOWN operation, work item, observation, and manual review | Inferring absence from zero matches or automatically releasing scope | `PHASE_0_GATED`: Step 5; recovery Step 8 |
| Provider webhook event identity and deduplication semantics | `GATED / UNVERIFIED` | Local delivery UUID plus nullable event ID and payload hash | Provider-event uniqueness or treating dedup as access proof | `PHASE_0_GATED`: Step 5; webhook runtime Step 8 |

Provider-dependent unknowns in this register do not block this persistence
handoff. They block only the corresponding production constraint or runtime
interpretation.

## Schema evolution and later ownership

`ANY-504` Step 4 freezes this provider-independent clean baseline. Phase 0 and
Steps 6-10 may add reviewed provider-facing fields, indexes, or constraints by
ordinary forward migration when retained evidence requires them. Such changes
must not alter the accepted authority boundaries or silently recreate
Portal-owned catalog, order, payment/refund, provider-account, or authoritative
remaining-quota semantics.

Runtime ownership is fixed as follows: Step 3 finalizes identity/session/legal
and the legal-acceptance FK; Step 4 creates the clean physical baseline and
only `STEP_4_SAFE` constraints; Step 5 closes provider evidence; Step 6 owns
manifest/catalog import and mapping publication; Step 7 owns purchase,
customer/create preparation, idempotency, and Widget flow; Step 8 owns webhook,
discovery, reconciliation, recovery, and durable worker execution; Step 9 owns
subscription access projection, allowances, effective revision, and atomic
outbox production; Step 10 owns the Portal-Kernel HTTP and quota runtime. The
webhook and reconciliation paths must feed the same Application transition.

## Implementation gates

Evidence strength and implementation timing are independent. A documented or
accepted fact can still have later runtime ownership, and a provider-neutral
storage slot can be safe before its provider-specific meaning is proven.

| Gate | Meaning | What `ANY-504` Step 4 may do |
| --- | --- | --- |
| `STEP_4_SAFE` | Provider-neutral physical shape or invariant is fully decided without LBX production evidence. | Create the named table, column, FK, uniqueness rule, index, or closed provider-neutral vocabulary in the clean baseline. It does not authorize later runtime behavior. |
| `PHASE_0_GATED` | The production rule depends on retained LBX evidence that is not yet sufficient. | Create only the explicitly approved opaque/nullable provider-neutral slot. Do not add the provider-specific constraint, interpretation, or production flow until `ANY-504` Step 5 closes the gate. |
| `LATER_STEP_RUNTIME` | The physical slot is part of the approved baseline, but its validation, transitions, network behavior, or public contract belongs to the named later step. | Create the storage shape and Step-4-safe constraints only. Do not populate it, introduce its runtime, or close an intentionally open vocabulary in Step 4. |

## Clean-reset and bootstrap contract

The clean reset is conditional, not an unconditional authorization to destroy
data. `ANY-504` Step 4 must revalidate the no-production premise immediately
before destructive work. If production billing/customer data, an active client,
or a retention/cutover obligation exists, Step 4 must stop and obtain an
approved migration and cutover design.

When the premise remains true, Step 4 must apply this contract:

1. Consume the merged `ANY-504` Step 3 repository state as the final physical
   identity/session/legal baseline and complete the handoff checklist below.
2. Remove or neutralize old backend public consumers and frontend calls before
   deleting persistence symbols they require. Preserve core
   `GET /api/auth/session` user/session behavior, but remove its optional
   `product` input and billing-derived `product_state` result. Remove
   `GET /api/auth/payment-status` and its payment-result polling. A frontend
   route may remain only as a neutral unavailable/informational shell that
   calls none of the removed billing APIs.
3. Remove the old Portal-owned catalog, checkout, order, payment, refund,
   subscription, entitlement, trial, direct-provider, CloudPayments,
   configuration, integration, and provider-registry consumers described by
   the disposition matrices above. The legacy trial lifecycle is removed
   Portal-owned access state, not a target paid-access or compatibility path.
4. Install the retained Step-3 identity/session/legal model and the 15 target
   tables in this document, with only `STEP_4_SAFE` constraints and the
   explicitly approved safe slots for later-owned semantics.
5. Treat revisions `20260707_0001` through `20260826_0005` only as the
   researched baseline. Replace the **entire pre-reset Alembic history present
   when Step 4 starts**, including any Step-3 identity/session/legal revisions,
   with one fresh first-install baseline and one Alembic head.
6. Do not build a data-preserving forward business migration, dual write,
   legacy backfill, old/new coexistence layer, or billing compatibility layer
   while the no-production premise holds. Recreate development, test, and
   pre-production databases from the new baseline.
7. Seed no Portal-owned product, plan, bundle, or provider-account catalog.
   Capability/catalog projections, mappings, purchases, customer/subscription
   state, observations, allowances, access state, work items, outbox rows, and
   manual-review cases all start empty and are populated only by their later
   runtime owners.
8. Keep the canonical legal source and manifest as the legal bootstrap input,
   using the final Step-3 physical shape and deterministic bootstrap behavior.
   Bootstrap only contour-local configuration allowed by the final one-contour
   contract. In particular, a `ru` data plane must not retain `eu`, DE, or ES
   seed rows merely because the former initial migration contained them.
9. Rewrite or remove obsolete persistence, migration, provider, backend, and
   frontend tests; add the Step-4 target schema and PostgreSQL concurrency
   proofs assigned below.
10. Regenerate database-schema and OpenAPI artifacts only through repository
    generation tooling. Never hand-edit generated files.
11. Finish with no live import, configuration requirement, API/frontend call,
    test, generated artifact, or current-state documentation that still
    requires removed `Product`, `Plan`, `Order`, `Payment`, subscription/
    entitlement, trial, `PaymentProvider`, or CloudPayments semantics.

After the reset, later steps use ordinary reviewed forward migrations for
newly proven requirements. Another squash or reset would require a separate,
explicit pre-production decision.

### `ANY-504` Step 4 dependency and removal order

The following order is mandatory so deleted persistence is never kept alive by
an accidental consumer:

1. Reverify the no-production premise and consume the `ANY-504` Step 3 handoff.
2. Remove or neutralize old backend public consumers and all affected frontend
   calls, including session product-state, payment-status polling, catalog,
   checkout, and account-subscription calls.
3. Remove old billing Application/runtime, integration, provider, configuration,
   command, persistence-helper, and export consumers.
4. Install the final retained identity/session/legal models and the approved
   target models/enums without later-step runtime behavior.
5. Replace the complete then-current Alembic history with the clean baseline
   and contour-local/legal bootstrap.
6. Delete or rewrite old persistence/migration/provider tests and add the
   target schema and concurrency tests owned by Step 4.
7. Regenerate schema/OpenAPI references and update affected current-state
   documentation and guards.
8. Prove that no removed import, configuration key, public API, frontend call,
   test assumption, generated contract, or architecture classification remains.

Target catalog, purchase, account, subscription-projection, and Portal-Kernel
surfaces are introduced only by their named later owners. Step 4 must not hide
their runtime implementation inside the reset merely because their storage
exists.

## `ANY-504` Step 3 to Step 4 handoff checklist

Before schema implementation, Step 4 must complete every item:

- [ ] Re-read only the retained identity/session/legal rows affected by the
  merged Step-3 change and update their physical details in the current-table
  disposition matrix; do not reopen unaffected target-billing decisions.
- [ ] Confirm the retained append-only acceptance evidence directly binds the
  exact accepted commercial fingerprint or offer to the complete required set
  of versioned legal documents. A copied generic acceptance or legacy
  `Plan.id`-bound recurring consent is insufficient.
- [ ] Decide whether `entrypoint_sessions` retains a provider-independent
  identity/legal/origin role and remove all Product/Bundle authority from any
  retained shape.
- [ ] Confirm the final one-contour registration, user, session, region, and
  country bootstrap behavior. Step 4 must not remove the old `eu`/DE/ES seeds
  while Step-3-approved identity tests still require `ru`+`eu` seed or
  cross-contour registration behavior.
- [ ] Resolve only the physical representation of the already-locked semantic
  paid-access scope `(tenant_id, region, canonical Portal user_id)`: explicit
  `tenant_id`/`region` columns or lossless derivation through the final canonical
  user/contour key.
- [ ] Apply exactly that same physical scope and serialization to
  `paid_access_states`, `access_invalidation_outbox`, and the future
  AccessSnapshot contract, including compatible FKs and uniqueness.
- [ ] Confirm Step 3 found no separate provider-independent obligation for the
  old Portal trial lifecycle. If it did, stop and report the material
  contradiction instead of preserving the billing model implicitly.
- [ ] Confirm direct-CloudPayments work such as `ANY-168` is canceled,
  superseded, or otherwise non-executable before Step 4 begins.

Step 3 may refine these retained physical details without invalidating the
target billing design. It may not reopen External Billing ownership, the 15
target table boundaries, provider-neutral invariants, or Phase 0 gates without
a concrete contradiction.

## Security, audit, and retention rules

- Persist no billing secret, Widget signing material, card/payment credential,
  authorization header, raw token, or unredacted payment field. Secret material
  remains outside the database in the approved runtime secret boundary.
- `billing_customer_key` is an opaque, immutable, non-PII correlation key. It
  must not encode email, phone number, legal name, or another mutable/customer-
  meaningful identifier.
- Webhook delivery, create-recovery, work-item, observation, and manual-review
  evidence is bounded, schema-versioned, minimized, and redacted. Raw provider
  bodies, provider payment history, and invoice/refund ledgers are not retained.
- Durable evidence must be sufficient to reconstruct why paid access was
  granted, omitted, reduced, blocked, or placed into manual review, including
  the accepted mapping/purchase/legal provenance and the observation or local
  deterministic boundary that caused a semantic revision.
- Current projections and application logs are not audit history. Immutable
  purchase/mapping evidence, normalized observations, create-operation state,
  review resolutions, access revision, and outbox state carry the meanings
  assigned in the durable evidence-source matrix.
- This handoff defines no legal or regulatory retention duration. Deletion and
  archival periods require explicit Legal/Finance authority plus a reviewed
  operational policy that preserves referential and audit obligations.

## Future verification matrix

`ANY-509` defines these obligations but implements none of the tests or runtime
behavior. A proof with more than one owner is completed incrementally: the
earlier step proves its physical/static part and the later step proves runtime
semantics.

| Required proof | Proof class | Owner |
| --- | --- | --- |
| A fresh database reaches the sole new Alembic head and contains exactly the retained Step-3 tables plus the 15 target tables. | Migration/schema test | `ANY-504` Step 4 |
| Retained identity/session/legal behavior survives the baseline; core `/api/auth/session` remains while `product`/`product_state` is absent. | Migration/schema + contract tests | Steps 3-4 |
| Legacy Portal trial persistence/lifecycle is absent and never produces a free/trial grant through paid AccessSnapshot. | Architecture/static + contract tests | Removal in Step 4; paid-contract proof in Steps 9-10 |
| The one-contour identity baseline no longer depends on `eu`/DE/ES rows in a `ru` data plane. | Migration/schema + identity contract tests | Steps 3-4 |
| No old Portal catalog, provider, commerce, subscription, or entitlement table remains. | Migration/schema + architecture/static checks | Step 4 |
| No CloudPayments/provider-registry runtime, configuration, test, or frontend dependency remains, and `ANY-168` cannot execute into Step 4. | Architecture/static check + roadmap gate evidence | Step 4 |
| Exactly one customer slot exists per `(external_billing_account_id, user_id)`, persisted customer-key reuse is rejected, and concurrent purchases for different products follow `product access scope -> customer slot`, discard a losing insertion candidate without comparing it to the canonical key, reuse the persisted slot/key, and converge on at most one unresolved customer-create operation. A collision with another slot's persisted key fails/reallocates locally before external effect and never becomes `identity_conflict`. | Migration/schema + PostgreSQL cross-product concurrency + application/idempotency tests | DDL in Step 4; runtime in Step 7 |
| Two concurrent first purchase attempts against an initially absent `(user_id, product_id)` scope converge through insert-on-conflict/get-and-lock on exactly one scope row; before either external call, at most one scope-holding `PurchaseIntent` / create operation owns permission to proceed and the other reuses it or receives the occupied-scope result. | Migration/schema + PostgreSQL concurrency + application/idempotency tests | DDL in Step 4; runtime in Steps 7-8 |
| Composite scope FKs reject mismatched mapping account/offer, customer account/user, linked-purchase account/user/product/provenance, primary-subscription user/product, allowance product, and scope-bearing observation references. Observation rows also reject simultaneous subscription/direct-purchase references and derive subscription purchase provenance through `external_subscriptions.purchase_intent_id`, including when that link is null. | Migration/schema negative tests | Step 4 |
| Duplicate client retries are unique on `(external_billing_account_id, user_id, client_idempotency_key)`; exact replay converges and same-identity/different-request reuse conflicts. | Migration/schema + application/idempotency + PostgreSQL concurrency tests | DDL in Step 4; runtime in Step 7 |
| An ambiguous external create persists `UNKNOWN`, survives restart, retains its scope, and is recovered without blind retry. | Application/idempotency + restart/integration tests | Steps 7-8 |
| Mapping revisions and accepted purchase snapshots remain immutable. | Migration/schema + application tests | DDL in Step 4; behavior in Steps 6-7 |
| `billing_state_observations` survive restart and mutable-projection replacement, reject rows missing the kind-specific structural links, require primary-selection basis to be a discovery in the same scope, require every subscription `latest_observation_id` to be the same-subscription `authoritative_subscription_read` that produced the current projection, retain normalized authoritative-read/discovery/primary/deterministic-boundary evidence, and link causative evidence to the resulting access revision without retaining raw provider/payment history. | Migration/schema + application/audit tests | DDL in Step 4; kind/causality behavior in Steps 8-9 |
| Purchased quantity and effective allowance tuple are immutable, and Portal persists no runtime `remaining`. | Migration/schema + architecture/static + contract tests | DDL in Step 4; behavior in Steps 9-10 |
| Same-cycle block/unblock preserves `allowance_id` and Kernel usage identity. | Contract + E2E evidence | Phase 0 prerequisite in Step 5; runtime in Steps 9-10 |
| A known user with no `paid_access_states` row receives implicit revision zero and a read causes no database write. | Contract + application/database tests | Step 10 |
| Starting from absent revision zero and separately from existing revision `N`, two concurrent independent product-access transitions serialize on the canonical user row, each re-derive from the latest committed complete state, and commit revisions `1` then `2` (or `N+1` then `N+2`); the final complete state contains both changes and the atomic coalesced outbox retains at least the newer revision despite an older acknowledgement. | PostgreSQL concurrency/atomicity + application tests | Step 9, with delivery-race completion in Step 10 |
| Duplicate and out-of-order webhooks never directly grant access and converge through the same transition used by reconciliation. | Application/idempotency + contract tests | Steps 8-9 |
| Work claims/retries and reconciliation fencing prevent a stale worker from committing. | PostgreSQL concurrency + application tests | Step 8 |
| Subscription and work-item lease owner/expiry columns reject either half-populated form. | Migration/schema negative tests | Step 4 |
| Deterministic due-time work removes only the due paid fact without provider HTTP. | Application + contract tests | Steps 8-9 |
| Invalidation coalescing and in-flight acknowledgement races cannot lose a newer revision. | PostgreSQL concurrency/atomicity + contract tests | Production in Step 9; delivery in Step 10 |
| Manual review cannot directly create entitlement or allowance authority. | Application + architecture/static checks | Steps 7-9 |
| Stale or conflicting provider facts fail closed at the affected fact/metric scope while independent proven facts remain available. | Application + contract + E2E evidence | Steps 8-11 |
| Generated schema/OpenAPI, current-state documents, and architecture guards describe the clean baseline and no removed contract. | Architecture/static + documentation/generated-artifact checks | Step 4, consolidated in Step 11 |

## Later-step ownership and deferrals

| `ANY-504` step | Owned work | Explicit deferral / boundary |
| --- | --- | --- |
| Step 3 | Final physical identity/session/legal baseline; provider-independent legal acceptance directly bound to exact commercial and versioned-document evidence; one-contour identity behavior. | Does not redesign target billing persistence. Its approved physical refinements are consumed before Step 4. |
| Step 4 | Conditional clean reset; legacy commerce/direct-provider removal; retained + target baseline; `STEP_4_SAFE` DDL; clean bootstrap; Step-4 schema/concurrency proof; affected docs/generated artifacts. | No LBX production semantics and no runtime owned by Steps 5-10. |
| Step 5 | LBX Phase 0 evidence and final provider-dependent identity, agreement, subscription, Widget, cycle, webhook, and authoritative-fact constraints; reviewed forward migrations where evidence warrants them. | No speculative provider rule may be promoted before retained evidence closes its gate. |
| Step 6 | Capability-manifest and external-catalog LKG imports, freshness, typed projection documents, and privileged immutable mapping publication. | Does not create purchase/customer/subscription runtime. |
| Step 7 | `PurchaseIntent`, customer binding/preparation, outbound-create idempotency/uncertainty, accepted snapshots, and Widget flow. | Does not treat browser return, outbound success, Widget callback, or payment status as paid-access authority. |
| Step 8 | Webhook receipt, complete discovery, authoritative reads, reconciliation, recovery, normalized observations, manual-review orchestration, and durable worker claiming/fencing. | Webhooks are priority/evidence only; access derivation remains Step 9. |
| Step 9 | External-subscription access projection, purchased allowances, fact-scoped fail-closed behavior, effective access revisions, and atomic invalidation-outbox production. | Does not own Kernel quota usage/remaining or the Portal-Kernel transport. |
| Step 10 | Portal <-> Kernel HTTP contract, implicit revision-zero read behavior, invalidation delivery, and Kernel quota runtime. Rewrite, close, or supersede `ANY-79`, `ANY-286`, and `ANY-287`; they must not execute as currently written. | Does not revive the old entitlement contract. |
| Step 11 | Final as-built consolidation, architecture guards, transitional-debt cleanup, and end-to-end evidence. | Canceled `ANY-497` remains historical only; it is not an implementation contract. |

Before Step 4, `ANY-168` and the direct-CloudPayments roadmap must no longer be
executable. No later-step runtime may be included in Step 4 merely because its
table or safe storage slot is present.

## Documentation and guard handoff

| Surface | Required owner/action |
| --- | --- |
| `docs/architecture/payment-portal-data-model.md` | `ANY-504` Step 4 rewrites it as the authoritative current-state/as-built clean-schema reference, still subordinate to the target authority chain for future billing behavior. |
| `docs/architecture/payment-providers.md` | Step 4 updates/reclassifies it when direct-provider source is removed. |
| ANY-505 documentation/architecture guards | Step 4 updates any guard whose retained-direct-provider classification becomes false; it must not weaken the canonical precedence checks. |
| `docs/product/ru-mvp.md` | Step 4 removes stale ANY-71 catalog/trial and old catalog/subscription journey claims. |
| `ARCHITECTURE.md`, `docs/PRODUCT.md`, `docs/RELIABILITY.md`, and `README.md` | Step 4 updates only factual current-state/operational claims changed by physical removal, including obsolete subscription-expiry or commercial-transition operations. |
| `docs/generated/db-schema.md` and `docs/generated/openapi.json` | Step 4 regenerates both through repository tooling after schema/API removal; neither is hand-edited. |
| Superseded ADRs and historical billing plans | Retain as clearly subordinate history; do not rewrite them as target authority. |

No new `ANY-509`-specific architecture guard is required. Existing `ANY-505`
precedence checks remain authoritative. Executable schema/runtime guards belong
to `ANY-504` Step 4 and the later step that owns the behavior.

## `ANY-504` Step 4 readiness checklist

- [ ] The no-production premise has been revalidated immediately before work;
  otherwise Step 4 is stopped for a new approved cutover design.
- [ ] The Step-3 identity/session/legal handoff checklist is complete, and its
  affected retention-matrix rows reflect the final physical repository state.
- [ ] Exact commercial/legal acceptance binding and the disposition of
  `entrypoint_sessions` are known from Step 3.
- [ ] One-contour identity/bootstrap tests no longer require the obsolete
  `ru`+`eu` seed/registration behavior before foreign-contour rows are removed.
- [ ] The physical `(tenant_id, region, user_id)` representation is fixed and
  identical for paid access, invalidation, and future AccessSnapshot scope.
- [ ] `ANY-168`/direct-CloudPayments work is non-executable; `ANY-79`,
  `ANY-286`, and `ANY-287` are reserved for Step-10 rewrite/supersession; the
  canceled `ANY-497` remains historical only.
- [ ] The public/API/frontend removal order, complete pre-reset Alembic-history
  replacement, empty-target bootstrap, test replacement, generated-artifact
  regeneration, documentation updates, and final dependency proof are scoped
  together for Step 4.
- [ ] Every target field/constraint is classified as `STEP_4_SAFE`,
  `PHASE_0_GATED`, or `LATER_STEP_RUNTIME`, with no unowned provider-independent
  design question.
- [ ] Remaining unknowns are limited to Step-3 physical refinements captured by
  this checklist, the named Phase 0 evidence gates, or named later-runtime
  behavior. None authorizes Step 4 to invent a new target rule.
