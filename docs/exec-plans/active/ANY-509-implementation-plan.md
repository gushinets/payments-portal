# ANY-509 - Target Persistence Model and Clean Reset / Legacy Removal Contract

## Plan Overview

| Field | Value |
| --- | --- |
| Parent | `ANY-504` Step 2 |
| Ticket | `ANY-509` |
| Overall status | `complete` |
| Execution order | Sequential only: `ANY-509 Step 1` -> manual verification -> commit -> `ANY-509 Step 2` -> manual verification -> commit -> `ANY-509 Step 3` -> manual verification -> commit |
| Steps / commits | 3 |
| Primary durable artifact | `docs/architecture/external-billing-persistence-reset.md` |
| Scope | Design / documentation only; no destructive schema rewrite and no production LBX behavior |
| Predecessor | `ANY-505` / PR #113 merged and complete |
| Main consumer | `ANY-504` Step 4 after the `ANY-504` Step 3 identity/session/legal handoff |

## How to Use This File

1. Work from an up-to-date branch for `ANY-509` after merged `ANY-505` / PR #113.
2. The three implementation steps were completed sequentially; their scoped
   prompts remain below as historical execution records, not pending work.
3. The implementation model must use the decisions in this plan instead of repeating broad repository research or redesigning the persistence model.
4. After each step, review the diff and run the listed manual verification commands yourself.
5. Commit the step only after manual review and verification.
6. Before `ANY-504` Step 4 performs destructive cleanup, the final repository state produced by `ANY-504` Step 3 must be re-read as the physical baseline for retained identity/session/legal tables. That handoff does not reopen the target billing model designed here.

### Step terminology

This file has two step namespaces and they must never be conflated:

- `ANY-509 Step 1`, `ANY-509 Step 2`, and `ANY-509 Step 3` are the three execution steps of this implementation plan.
- `ANY-504 Step 3` is the subsequent identity/session/legal baseline step in the parent program.
- `ANY-504` Step 4 is the subsequent clean-schema / legacy-removal implementation step.
- `ANY-504` Step 5 is LBX Phase 0; `ANY-504` Steps 6-11 are the later runtime and consolidation steps.

All parent-program references below use the explicit `ANY-504 Step N` form. Unqualified `Step 1/2/3` references are reserved for the local `ANY-509` execution steps only.

## Research Baseline and Locked Decisions

### Authority and sequencing

Target billing work follows this authority chain, in order:

1. `docs/architecture/decisions/0005-external-billing-boundary.md`;
2. `docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md`;
3. `docs/superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md`.

`ANY-504` controls implementation order. `ANY-509` is a subordinate implementation handoff under those sources, not a new competing ADR.

`ANY-505` is complete and PR #113 is merged. The current `main` branch already classifies the old direct-provider documentation and persistence model as retained current-state context rather than target authority.

### Evidence and implementation-gate taxonomy

Every persistence field, constraint, identity rule, and provider-facing assumption documented by `ANY-509 Step 2` must carry two independent classifications. Do not collapse evidence strength into implementation timing.

**Evidence level** must use exactly one of:

- `ACCEPTED_ARCHITECTURE_REQUIREMENT` - required by ADR 0005 or an accepted design baseline;
- `DOCUMENTED_PROVIDER_FACT` - stated by current provider documentation/Swagger but not yet proven against the target stand;
- `VENDOR_CONFIRMED` - explicitly confirmed by the provider/vendor through an authoritative support or implementation channel;
- `CONFIRMED_ON_TEST` - reproduced on the target/demo stand with retained evidence;
- `GATED / UNVERIFIED` - unresolved or insufficiently proven and therefore not safe to encode as production truth.

**Implementation gate** must use exactly one of:

- `STEP_4_SAFE` - provider-independent storage/constraint safe for `ANY-504` Step 4;
- `PHASE_0_GATED` - must not be enforced as provider-specific production semantics before `ANY-504` Step 5 evidence;
- `LATER_STEP_RUNTIME` - storage may exist earlier, but runtime semantics are owned by the explicitly named later `ANY-504` step.

The durable artifact must show both axes wherever semantics are not purely structural. A documented provider value is not automatically safe to enforce, and a `STEP_4_SAFE` structural slot does not imply that the provider-specific meaning stored in it is already proven.

### Clean-reset premise

The clean-reset premise is currently valid and is not an assumption invented by this plan:

- `ARCHITECTURE.md` states that Payment Portal is still under development and has no production CloudPayments subscribers or subscriptions;
- `docs/PRODUCT.md` states that Payment Portal is not running as a production billing service and that there are no production CloudPayments subscribers or subscriptions to migrate;
- `ANY-504` and `ANY-509` explicitly authorize a fresh pre-production baseline while that remains true.

Production deployment tooling exists, but it is not evidence of production billing data or migration obligations.

If this premise changes before destructive `ANY-504` Step 4 work starts, `ANY-504` Step 4 must stop and replace this reset strategy with a real migration/cutover design.

### Current runtime baseline

`ANY-457` is complete. Normal runtime has an empty `PaymentProviderRegistry`, does not initialize or mount CloudPayments, and the frontend checkout path is deliberately unavailable. The retained CloudPayments source, settings, old ORM model, migrations, tests, and frontend/provider code therefore exist for characterization and cleanup, not because they still own production behavior.

One current-state documentation inconsistency remains: `docs/architecture/deployment.md` still depicts active CloudPayments widget/webhook traffic and still contains a stale future-access reference to the old ANY-71-era contract. That is stale relative to `ANY-457`, current code/tests, ADR 0005, the accepted Portal-Kernel design, `ARCHITECTURE.md`, and `docs/PRODUCT.md` and must be corrected as part of `ANY-509 Step 1` without redesigning future deployment topology.

### Existing persistence architecture that must survive

The following already-established mechanics remain valid for the target implementation:

- `app.models` is the canonical SQLAlchemy persisted-model layer;
- confirmed closed persisted vocabularies are `StrEnum` values stored through the existing text-backed enum mechanism;
- provider/vendor vocabularies stay at Integration boundaries and are not promoted into canonical model enums;
- Application owns business decisions, idempotency, state transitions, and outer business transactions;
- `app.infrastructure.queries` owns focused query mechanics;
- `app.infrastructure.persistence` is used only for storage mechanics that justify it, not as a repository-per-table layer;
- persistence helpers do not own the outer commit/rollback;
- Presentation remains thin and uses normal FastAPI DI/resource composition;
- no external network request is made inside an open business transaction;
- webhook and reconciliation inputs must converge through the same Application transition rather than separate state machines;
- last-write-wins synchronization is forbidden.

There is currently no durable PostgreSQL job queue, reconciliation scheduler, invalidation outbox, or generic background-work table in the repository. The target model therefore needs one shared durable work substrate rather than preserving or creating multiple independent schedulers.

### Current 26-table disposition

The durable artifact must classify every current table. The classification below is locked for `ANY-509`; `ANY-504` Step 3 may refine only the physical identity/session/legal details explicitly delegated to it.

| Current table | ANY-509 disposition | Locked rationale |
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

### Legacy runtime and API disposition

`ANY-504` Step 4 is expected to physically remove, rather than generalize, the dead direct-provider stack once `ANY-504` Step 3 has stabilized retained identity/legal behavior:

- `apps/api/app/integrations/cloudpayments/**`;
- `apps/api/app/cloudpayments.py`;
- `scripts/cloudpayments_sandbox_verify.py`;
- the old `app.payment_providers` registry/accounts/contracts stack once old checkout no longer consumes it;
- CloudPayments settings, `app.core.payment_api_limits` if it has no surviving non-legacy consumer, and retained manual-sandbox configuration;
- old direct-provider query/persistence helpers whose only remaining consumers disappear;
- old billing lifecycle/catalog/account code that is structurally coupled to `Product` / `Plan` / `Order` / `Payment` / `Subscription` / `Entitlement`, including `apps/api/app/commands/expire_subscriptions.py` once the old subscription/entitlement model is removed;
- CloudPayments and old commerce tests/fixtures that no longer describe a retained target invariant;
- frontend CloudPayments adapter/widget/types and direct-provider payment-result behavior.

Current provider-independent identity, legal, security, observability, database, FastAPI DI, persistence-boundary, and architecture-guard code is not removed merely because old billing callers disappear.

The old public contracts are not compatibility requirements because there is no production billing client/data obligation:

- `/api/catalog/products` is removed as a Portal-owned sellable-catalog contract in `ANY-504` Step 4; its target replacement belongs to `ANY-504` Steps 6-7;
- `/api/auth/checkout-intent` is removed with the old direct-provider checkout; target `PurchaseIntent` runtime belongs to `ANY-504` Step 7;
- `/api/account/subscriptions*` is removed as the old Plan/Entitlement-shaped account contract; a target billing/account projection belongs to later steps;
- `GET /api/auth/payment-status` and `app.domains.identity.services.account.load_payment_status()` are removed with the old `Order` / `Payment` model; `/ru/payment-result` becomes a neutral informational surface with no old payment-status polling until a later target flow explicitly owns replacement behavior;
- `GET /api/auth/session` itself is retained as an identity/session API, but its optional `product` query and legacy `product_state` projection are not identity invariants. `app.domains.identity.services.account` currently resolves that state through old `Product` / `Plan` / `Order` / `Entitlement` queries; `ANY-504` Step 4 must remove that billing-derived extension while preserving authenticated session/user semantics;
- frontend routes may keep neutral unavailable shells if still needed for navigation, but must not call removed APIs or retain CloudPayments execution code. This applies at least to `/ru`, `/ru/products`, `/ru/auth-checkout`, `/ru/account`, and `/ru/payment-result`, whose current clients consume the old catalog/subscription/session-product/payment-status contracts.

The current Portal trial implementation is also legacy billing/access state, not a target paid-access primitive:

- `start_trial()`, `SubscriptionStatus.TRIALING`, `EntitlementSource.TRIAL`, `Plan.trial_days`, and trial-backed `Entitlement` reads belong to the retained Portal-owned `Plan` / `Subscription` / `Entitlement` model;
- current `main` exports and tests this lifecycle, but there is no normal public trial-start HTTP endpoint;
- the accepted target keeps free/guest/trial policy Kernel-owned and outside the paid `AccessSnapshot` unless a separate approved decision says otherwise;
- therefore `ANY-504` Step 4 removes the old Portal trial persistence/lifecycle together with the superseded subscription/entitlement model. If `ANY-504` Step 3 discovers a separate provider-independent Portal obligation that genuinely requires retained non-billing trial state, it must surface that as a material contradiction rather than silently preserving the old billing model.

No dual-write layer, old/new billing compatibility layer, or data-preserving migration path is required under the current no-production baseline.

### Related roadmap and executable-plan disposition

Repository and Linear research found old executable work that can conflict with the clean-reset program even though it is not target authority:

- `ANY-168` (`Implement CloudPayments recurring payments integration`) is still **In Progress** in Linear. It directly conflicts with the deactivated-runtime baseline and the `ANY-504` Step 4 removal of direct CloudPayments. It must not continue as executable implementation work. Before `ANY-504` Step 4 begins, it must be explicitly canceled, superseded, or otherwise blocked from execution by the ANY-504 program; no ANY-509 code step implements or revives it.
- `ANY-163` remains a blocked CloudPayments umbrella and is historical/transitional program context only; it must not authorize new direct-provider work.
- `ANY-79` is still Planned and `ANY-286` / `ANY-287` remain backlog items for the old entitlement contract. They must not execute as written; formal rewrite/close/supersede ownership remains `ANY-504` Step 10.
- `ANY-497` is already canceled and is retained only as historical ANY-407 context.
- `docs/exec-plans/active/ANY-135-split-alembic-baseline.md` and `docs/exec-plans/active/ANY-76-refund-result-status.md` describe already-completed current-state work even though their files still sit under `active/`. They are characterization evidence only and cannot override the ANY-504/ADR-0005 reset contract. ANY-509 does not perform broad exec-plan housekeeping; the durable artifact must classify these conflicting current-state plans so `ANY-504` Step 4 does not treat them as executable target guidance.

### Documentation disposition discovered during research

The `ANY-504` Step 4 handoff must explicitly classify the current documentation surfaces that will become stale when the old schema/runtime is removed:

- `docs/architecture/payment-portal-data-model.md` -> rewrite in `ANY-504` Step 4 as the authoritative **current-state/as-built clean schema reference**, while remaining subordinate to the target authority chain for future billing semantics;
- `docs/architecture/payment-providers.md` -> update/reclassify when retained direct-provider source is physically removed; the ANY-505 documentation guard must be updated in the same `ANY-504` Step 4 change so it no longer requires a false "retained current-state implementation" classification;
- `docs/product/ru-mvp.md` -> update in `ANY-504` Step 4 because it still contains stale ANY-71-era catalog/trial language and current product-flow descriptions tied to the old catalog/subscription contracts;
- `ARCHITECTURE.md`, `docs/PRODUCT.md`, `docs/RELIABILITY.md`, and `README.md` -> update only where the `ANY-504` Step 4 as-built runtime/schema removal changes factual current-state/operational statements; in particular, remove retained subscription-expiry/commercial-transition operational guidance that no longer has executable code;
- `docs/generated/db-schema.md` and `docs/generated/openapi.json` -> regenerate through repository tooling, never edit by hand;
- superseded ADR/history documents remain historical and must not be rewritten into target authority.

### Target persistence shape

The `ANY-509 Step 2` artifact must define a small target model. Complete all-or-nothing projections and immutable snapshots should use validated, schema-versioned structured JSON where that avoids unnecessary table fan-out; arbitrary untyped JSON must not leak into Application logic. Pydantic contracts should validate those structured snapshots at the boundary.

The target physical table set introduced by the clean baseline is:

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

The fifteenth table is intentional rather than speculative: the accepted architecture requires durable, minimized evidence for authoritative reads, complete target-product discovery observations, first-primary decisions, and deterministic access-reducing transitions even after mutable projections are replaced. That audit requirement cannot be satisfied reliably by the latest `external_subscriptions` row, transient worker state, or application logs alone. `billing_state_observations` is an append-only provider-neutral evidence boundary, not a payment ledger, raw provider event archive, or second business state machine.

This list is intentionally much smaller than a table-per-concept/provider design. It must not be expanded with provider-account catalogs, payment/refund ledgers, separate customer/agreement/subscription UNKNOWN state machines, per-entity repositories, speculative provider abstractions, or table-per-provider observation stores. Later evidence may add reviewed fields/indexes/constraints through ordinary forward migrations, but must not silently recreate Portal-owned commerce or change the authority boundaries fixed by ADR 0005.

### Stable target storage contracts

The artifact must lock the following contracts so `ANY-504` Step 4 can implement them without redesign.

#### Configuration scope

- There is exactly one configured external billing account per deployed contour for MVP.
- `external_billing_account_id` is a stable non-secret configuration value used in persisted keys/audit where billing scope is needed.
- Provider credentials, webhook secrets, Widget signing material, and payment credentials remain runtime secrets and are never stored in these tables.
- There is no `external_billing_accounts` routing/catalog table in MVP.

#### `capability_manifest_projections`

- One current LKG row per tenant/contour scope.
- Stores supported `schema_version`, deterministic `manifest_version`, source `generated_at`, `last_complete_sync_at`, and the complete validated manifest payload.
- The payload is an internal typed snapshot of the accepted manifest contract: tenant/region scope, products with `product_id` / `enabled`, and usage metrics with `metric_key` / owning `product_id` / `unit` / `enabled`. Do not invent additional manifest fields.
- Replacement is atomic; failed/partial sync does not alter the LKG row or freshness.
- The accepted admission invariant is preserved for later runtime implementation: a projection older than `new_sales_projection_max_age = 24h` blocks new mapping publication and new purchases, while staleness or `enabled=false` never retroactively revokes already-pinned historical mapping/purchase/subscription/access meaning.
- `product_id` and `metric_key` are canonical Kernel-owned technical identifiers stored directly where needed. They are validated against the fresh manifest at publication/purchase boundaries and do not acquire foreign keys to a new Portal-owned `products`/`metrics` catalog or to JSON children inside this projection.
- Historical mappings do not rely on mutable foreign keys to current projection contents; they pin the manifest version and exact mapping document.

#### `external_billing_catalog_projections`

- One current complete LKG normalized catalog row per `external_billing_account_id`.
- Stores normalized catalog version when available, a deterministic normalized catalog digest, `last_complete_sync_at`, and the complete validated provider-neutral catalog snapshot.
- Failed/partial sync keeps the previous LKG row and does not advance freshness.
- The same `new_sales_projection_max_age = 24h` admission rule applies to the complete billing-catalog projection: stale catalog blocks new mapping publication/purchase but does not rewrite or revoke historical pins.
- `billing_offer_id` and external component identifiers remain opaque external identifiers stored directly in target rows/snapshots where needed; they do not become foreign keys into a Portal-owned commercial catalog table.
- The snapshot may contain opaque external offer/component identifiers and normalized material commercial facts, but vendor protocol payloads/status enums do not become Application contracts.

#### `commercial_mapping_revisions`

- Append-only immutable published revisions scoped by `external_billing_account_id` and the mapped external `billing_offer_id`; a purchase must be able to select the one currently published revision for its exact account/offer without relying on creation timestamp/row age or an implicit global latest row.
- The physical schema must use an explicit monotonic `revision_number` (or equivalent immutable publication sequence) with `UNIQUE(external_billing_account_id, billing_offer_id, revision_number)`. The current published mapping for an account/offer is the highest `revision_number` in that scope; unpublished drafts are not rows in this published-revision table. Publishing a new revision inserts a new immutable row; it never mutates a prior revision merely to toggle a `current` flag.
- Each revision records the exact capability `manifest_version`, normalized billing-catalog version when available, and billing-catalog digest used for validation.
- The revision stores one typed immutable mapping document covering the offer/component set required for that offer, component classification (`UNCLASSIFIED`, `CAPABILITY_BEARING`, `COMMERCIAL_ONLY`), external usage-reporting classification, and resolved `product_id` / `metric_key` bindings.
- Mapping publication is privileged/audited later runtime (`ANY-504` Step 6); direct row edits are not the production publication workflow.
- Later catalog/manifest changes create a new revision; existing purchases never rebind.
- Historical mapping revisions remain queryable while referenced.

#### `external_billing_customers`

- Owns the Portal customer slot, not provider customer lifecycle truth.
- Required stable constraints: `UNIQUE(external_billing_account_id, user_id)` and `UNIQUE(external_billing_account_id, billing_customer_key)`.
- `billing_customer_key` is immutable, opaque, non-PII, and never reused after allocation. The customer-slot allocation record must not be hard-deleted in a way that permits key reuse; retention/non-reuse is part of the identity invariant, not merely a transient uniqueness check.
- `provider_customer_id` may be nullable until proven/bound.
- Persist a provider-neutral **binding/integrity** state that durably distinguishes at least `unbound`, `bound`, and `identity_conflict` (or an equivalent closed provider-neutral vocabulary finalized by the `ANY-509 Step 2` physical-schema matrix). This is not an outbound-create state machine: customer/agreement/subscription create uncertainty remains exclusively in `external_create_operations`. `identity_conflict` is fail-closed and must survive restart/retry; it cannot exist only in logs or transient exceptions. The exact LBX `outer_id` / Widget identity proof remains `PHASE_0_GATED`.
- Do not add email/phone/name matching fallback.

#### `billing_product_access_scopes`

- One serialization row for `(user_id, product_id)` with a unique constraint on that pair.
- Holds nullable `primary_subscription_id` and is the row-lock scope for purchase ownership and later primary decisions.
- Linking a subscription never automatically makes it primary.
- First-primary selection must follow the accepted observe-then-lock algorithm rather than worker order or incidental local row age:
  1. outside the product-scope lock, run the customer/subscription discovery semantics proven by `ANY-504` Step 5 and authoritative point reads needed to build a complete normalized observation for the target product;
  2. durably persist the normalized observation/evidence before entering the short product-scope decision transaction;
  3. lock the `(user_id, product_id)` scope row and re-read the union of the just-observed target-product candidates plus known local non-terminal candidates;
  4. decide deterministically: zero eligible candidates -> `primary_subscription_id = NULL`; exactly one eligible candidate and it is the linked subscription -> select it; exactly one eligible candidate but it is another subscription -> keep/enter conflict/manual review; two or more eligible candidates -> `primary_subscription_id = NULL` and create/retain conflict/manual-review evidence.
- An already trusted primary is not silently replaced because a newcomer appears. A blocked primary does not auto-promote another candidate, and clearing/ending a primary does not auto-promote an older candidate without a fresh authoritative decision.
- No amount, agreement age, row creation order, worker order, or other heuristic may select a primary.
- No extra generation/digest/attempt subsystem is introduced for first-primary selection.

#### `purchase_intents`

- Replaces `CheckoutSession` + `Order` as Portal orchestration intent; it is not commercial authority.
- Persists user, billing-account scope, Kernel `product_id`, external `billing_offer_id`, mapping revision, accepted commercial fingerprint, client idempotency identity, orchestration state/timestamps, optional proven linked subscription, and one immutable typed `accepted_snapshot`.
- The accepted snapshot pins exact external component references, mapping revision IDs, `product_id` / `metric_key` bindings, fixed accepted integer quantities, material commercial fingerprint, and the legal acceptance/document-version evidence finalized by `ANY-504` Step 3.
- Accepted snapshot/fingerprint fields are immutable after creation.
- The purchase references the append-only legal/commercial acceptance evidence finalized by `ANY-504` Step 3 that directly proves acceptance of this exact commercial fingerprint/offer and required document versions; merely copying a legacy generic or `Plan.id`-bound acceptance into the purchase after the fact is not sufficient. `ANY-504` Step 3 owns the physical representation of that evidence.
- Business serialization is `(user_id, product_id)` through `billing_product_access_scopes`; exact public Idempotency-Key uniqueness scope is finalized with the `ANY-504` Step 7 API contract rather than guessed here.
- Persisted states follow the accepted design: `created`, `preparing`, `awaiting_external_result`, `linked`, `resolved_no_external_effect`, `failed_before_external_effect`, `manual_review`.

#### `external_create_operations`

- One unified durable model for customer, agreement, and subscription create attempts.
- Closed `operation_kind`: `customer`, `agreement`, `subscription`.
- Stores the affected customer slot and, where applicable, purchase intent; request/correlation identity; operation state; `unknown_since`; fixed accepted two-hour `unknown_recovery_deadline_at`; bounded safe recovery hints; and proven bound external object ID when available.
- Timeout/ambiguous outcome keeps the affected scope held, permits read-only recovery, never blind-retries create, and never treats zero matches as proof of absence.
- It is business uncertainty state, not a generic job queue; recovery scheduling is delegated to `billing_work_items`.

#### `external_subscriptions`

- A row exists only for a proven external subscription.
- Uses an internal Portal UUID primary key and stores billing-account/customer scope, Kernel `product_id`, pinned purchase/mapping provenance, opaque external subscription/agreement identifiers, normalized provider-neutral lifecycle/financial/commercial access statuses, `last_authoritative_read_at`, and `projection_valid_until`.
- Stores the PostgreSQL reconciliation lease owner/expiry and monotonic fencing token needed by later reconciliation, plus an optional reference to the latest durable normalized observation that produced the current projection.
- The accepted closed provider-neutral vocabularies are locked now: `lifecycle_status = active | inactive | ended`, `financial_access_status = allowed | blocked`, and `commercial_access_status = eligible | ineligible`. These are canonical Application/persisted vocabularies; raw vendor statuses remain Integration-owned. The exact provider facts that map into these values are later-step/Phase-0 concerns.
- Terminal/ended subscription rows are not automatically hard-deleted. Historical identity/provenance must remain available for recovery/audit and for any Phase-0-proven agreement/subscription non-reuse uniqueness rule. Retention duration beyond correctness/audit needs is a later operational/legal decision and must not be invented here.
- The exact canonical LBX subscription identifier, `outer_id` correlation role, agreement lifetime uniqueness, and terminal-revival semantics are Phase 0 gated and must not be encoded as pre-Phase-0 production truth.

#### `billing_state_observations`

- Append-only, minimized, provider-neutral evidence records used to explain authoritative state transitions after mutable projections are replaced. This table is evidence, not access/commercial authority and not a generic event-sourcing subsystem.
- Covers at least four closed evidence kinds: `authoritative_subscription_read`, `target_product_discovery`, `primary_selection`, and `deterministic_access_boundary`. The physical matrix may use equivalent provider-neutral names, but must not create provider-specific per-event tables.
- Stores billing-account scope, canonical Portal user/product scope where applicable, optional local subscription/purchase/work references, observation/effective time, one schema-versioned normalized evidence document, completeness/result classification, and optional `resulting_access_revision` when the evidence directly caused a semantic paid-access commit.
- `authoritative_subscription_read` stores only the normalized material facts needed to reproduce the Application decision (including commercial verification result and source/cycle facts needed by the accepted design), not raw provider payloads or payment history.
- `target_product_discovery` persists the complete normalized candidate set used by first-primary selection before the product-scope lock; `primary_selection` durably records the deterministic zero/one/many decision and selected/retained primary outcome against that observation.
- `deterministic_access_boundary` records the local fact/deadline responsible for an access-reducing commit that required no provider HTTP.
- Evidence rows are immutable after commit except for narrowly scoped linkage metadata that cannot change their normalized meaning. They remain queryable while referenced by current/historical subscription, purchase, access-revision, conflict/manual-review, or operational audit requirements.
- Evidence is bounded/minimized/redacted and must never become a raw webhook/provider response archive, invoice/payment ledger, or alternate source of access truth.

#### `purchased_allowances`

- `allowance_id` is a Portal-owned stable UUID identity.
- Stores source subscription, concrete source component identity, Kernel `product_id`, `metric_key`, immutable accepted non-negative integer quantity, provider cycle correlation, raw provider cycle bounds, and frozen effective wire `period_start` / `period_end`.
- `quantity >= 0` and `period_start < period_end` are provider-independent persisted invariants for any materialized allowance. A collapsed/invalid effective interval is not widened into a stored usable allowance.
- Portal never stores authoritative runtime `remaining`.
- Product/metric/quantity/effective wire bounds are immutable for a given `allowance_id`.
- Same-cycle block/unblock must reuse the same allowance and Kernel usage identity.
- Exact provider cycle identity and the final logical uniqueness constraint using the provider cycle key remain Phase 0 gated.

#### `paid_access_states`

- One current committed provider-neutral effective-access snapshot per known user only after the first material paid-access transition. The cross-service semantic scope is locked as `(tenant_id, region, canonical Portal user_id)`.
- `ANY-509` deliberately does **not** pre-empt the `ANY-504` Step 3 physical identity/contour decision by guessing whether `tenant_id` / `region` must be redundantly stored in `paid_access_states`. The Step-2 physical matrix must mark this one physical key representation as an explicit `ANY-504 Step 3 -> Step 4` handoff: after Step 3 finalizes canonical user/contour persistence, Step 4 must choose a physical uniqueness/FK shape that provably serializes the same semantic `(tenant_id, region, user_id)` scope and exactly matches `access_invalidation_outbox`/AccessSnapshot serialization. No other target-billing ownership decision is reopened by that handoff.
- Absence of a row means implicit revision `0`, empty grants, and empty allowances.
- A persisted row always has `access_revision > 0` and stores one typed provider-neutral effective-state document suitable for AccessSnapshot serialization; no provider IDs/statuses appear in that document.
- Any semantic grant/allowance change must atomically update the effective-state document, increment the revision, and upsert the invalidation outbox in the same transaction.
- A read/GET never creates revision state and never changes semantic state.
- Historical access snapshots do not require one row per revision; business/reconciliation evidence provides audit history while the revision contract protects the current semantic state.

#### `external_billing_webhook_deliveries`

- Local `delivery_id` is the durable inbox identity.
- Stores billing-account scope, safe normalized correlation hints, payload hash, bounded/redacted evidence, receipt/processing timestamps, and processing state.
- Full unredacted provider bodies, secrets, card/payment credentials, and a shadow payment ledger are forbidden.
- Webhook persistence is a priority hint only; webhook payload alone never grants access.
- Exact provider event identifiers/dedup semantics remain Integration/Phase-0 evidence where provider-specific.

#### `billing_work_items`

- One shared PostgreSQL durable background-work substrate for external-create recovery, discovery, subscription reconciliation, and deterministic access-reducing deadlines.
- Stores work kind, typed scope/reference, coalescing key where applicable, durable `next_attempt_at`, attempts, state, lease/claim metadata, and only bounded safe typed payload data.
- Urgent work is a scheduling priority/cadence on this same substrate, not a second queue.
- FastAPI `BackgroundTasks`, process memory, RabbitMQ, or Kafka are not correctness authority for MVP.
- Invalidation delivery remains represented by its dedicated outbox row rather than duplicating every invalidation as a generic job.

#### `access_invalidation_outbox`

- One coalesced row per tenant/region/user scope with a physical uniqueness constraint on that scope.
- Stores non-negative `pending_revision`, non-negative `delivered_revision`, attempt count, `next_attempt_at`, safe last-error classification, and timestamps; local acknowledgement is monotonic and must never move `delivered_revision` backward or beyond the revision actually sent.
- Coalesces to the maximum pending revision.
- The acknowledgement of an in-flight revision may acknowledge only the revision actually sent and can never clear a newer revision committed while the request was in flight.

#### `manual_review_cases`

- Durable operational evidence for conflicts/uncertainty, never access authority.
- Stores stable reason code, scope kind/reference, safe evidence, state, creation/resolution timestamps, and audited resolution evidence.
- A resolution may bind a proven object or release a scope after audited proof, but cannot directly set entitlement active, invent allowance quantity, or silently rebind historical mapping/purchase semantics.

### Durable audit/evidence coverage

The target model must be able to explain every material paid-access transition without relying on application logs or overwritten current rows alone. `ANY-509 Step 2` must include an explicit evidence-source matrix covering at least:

- accepted commercial/mapping/legal provenance -> immutable `commercial_mapping_revisions`, `purchase_intents.accepted_snapshot`, and the append-only acceptance evidence finalized by `ANY-504` Step 3;
- ambiguous create/recovery decisions -> `external_create_operations`;
- webhook receipt/correlation -> `external_billing_webhook_deliveries`;
- successful authoritative reads/reconciliation facts, complete target-product discovery, first-primary decisions, and deterministic access-reducing boundaries -> append-only minimized `billing_state_observations`, linked to the relevant local subscription/purchase/scope and to `resulting_access_revision` when they caused a semantic access commit;
- conflicts/operator decisions -> `manual_review_cases`;
- current effective semantic state/revision -> `paid_access_states` plus the atomic invalidation outbox contract.

The concrete durable representation for successful authoritative reads/reconciliation, complete first-primary observations/decisions, and deterministic access-reducing boundaries is `billing_state_observations`. A mutable `external_subscriptions` row containing only the latest projection is not sufficient evidence for a previous access transition. The Step-2 physical-schema matrix must therefore define the observation references/keys, typed normalized payload schemas, indexes needed for audit/recovery lookup, and the optional `resulting_access_revision` linkage without storing unbounded raw provider payloads. This closes the audit requirement inside the reviewed target model rather than deferring a table-design decision to `ANY-504` Step 4.

### Provider-dependent gates

The durable artifact must contain a gate register with at least these `PHASE_0_GATED` items:

- exact Widget `ident_type`; `ident_type=6` is only a documented candidate and is not accepted production truth;
- exact `billing_customer_key <-> LBX users.outer_id` behavior, drift/recovery, and provider-side restoration behavior;
- Widget/server authorization independently of presentation flags;
- maximum acceptable Widget credential lifetime and old-token overlap/remint behavior;
- canonical LBX subscription identity and whether `subscriptions.subscription_id` is the authoritative binding while `outer_id` is only a recovery hint;
- agreement isolation, stable subscription-to-agreement binding, and no agreement reuse across historical subscriptions;
- authoritative material-term read set and complete match/mismatch/incomplete semantics;
- prepaid blocking semantics;
- fixed quantity authoritative source;
- provider cycle identity/bounds and same-cycle/new-cycle behavior;
- actual deployed customer subscription-list completeness/visibility/concurrency semantics;
- provider-specific safe absence predicate, if one exists, for automatic scope release.

These gates are informed by GitHub issue #112 and the accepted design. `ANY-504` Step 4 may create provider-neutral storage slots for these facts, but it must not enforce an unproven provider-specific uniqueness/identity rule as canonical production truth.

### Later runtime ownership

The artifact must keep implementation ownership explicit:

- `ANY-504` Step 3: final physical identity/session/legal baseline and provider-independent legal acceptance primitives;
- `ANY-504` Step 4: clean physical baseline, removal of legacy commerce/CloudPayments, `STEP_4_SAFE` constraints owned by `ANY-504` Step 4 only;
- `ANY-504` Step 5: LBX Phase 0 evidence and final provider-dependent identity/agreement/subscription/cycle constraints;
- `ANY-504` Step 6: capability manifest import, external catalog import, mapping publication/freshness;
- `ANY-504` Step 7: `PurchaseIntent`, customer/preparation/outbound-create runtime and Widget flow;
- `ANY-504` Step 8: webhook, discovery, reconciliation, recovery, durable worker execution;
- `ANY-504` Step 9: external subscription access projection, allowances, effective access revision, invalidation;
- `ANY-504` Step 10: Portal <-> Kernel HTTP contract and Kernel quota runtime;
- `ANY-504` Step 11: final as-built consolidation, architecture guards, transitional-debt cleanup, E2E proof.

No runtime owned by `ANY-504` Steps 5-10 is implemented by `ANY-509`.

### Clean-reset contract

The `ANY-504` Step 4 handoff must require all of the following:

1. Re-verify the no-production premise immediately before destructive work; stop if it changed.
2. Treat merged `ANY-504` Step 3 as the final physical baseline for retained identity/session/legal tables; update only the affected rows of the retention matrix if `ANY-504` Step 3 refined them.
3. Remove old API/frontend consumers of obsolete billing models so the application no longer imports or calls deleted commercial/provider paths.
4. Remove old Portal-owned commerce/direct-provider ORM models, enums that have no target owner, queries/persistence helpers, CloudPayments/payment-provider runtime source, settings/config, and obsolete tests.
5. The current researched chain is `20260707_0001` through `20260826_0005`, but `ANY-504` Step 3 may add retained identity/session/legal revisions before cleanup. `ANY-504` Step 4 therefore replaces the **entire pre-reset Alembic history that exists at the start of Step 4**, including any Step-3 revisions, with one clean first-install baseline / one Alembic head that represents the final retained identity/session/legal schema plus the reviewed target persistence model. Do not write a data-preserving forward business migration from the superseded commerce schema under the current no-production premise. After that reset, later Steps 5-10 use ordinary reviewed forward migrations for newly proven requirements; another squash/reset would require a separate explicit pre-production decision.
6. Recreate dev/test/pre-production databases from the fresh baseline. Old local billing data is disposable; no dual-write/backfill/coexistence path is required.
7. Bootstrap only contour-local configuration consistent with the final `ANY-504` Step 3 contour contract. Under the current `ru` baseline, do not keep the old `eu`/DE/ES rows in a `ru` data plane merely because the old initial migration seeded them.
8. Preserve the legal source/manifest as the canonical legal bootstrap input and keep deterministic legal bootstrap behavior consistent with the `ANY-504` Step 3 result.
9. Do not seed Portal-owned products/plans/bundles/provider accounts. Capability/catalog projections, mappings, purchases, subscriptions, allowances, access state, work items, outbox, and manual-review rows begin empty and are populated by their owning later steps.
10. Regenerate generated schema/OpenAPI artifacts in `ANY-504` Step 4; never hand-edit generated files.
11. End `ANY-504` Step 4 with no live imports, public APIs, frontend calls, configuration requirements, tests, or architecture docs that accidentally require removed `Product` / `Plan` / `Order` / `PaymentProvider` / CloudPayments semantics.

The reset contract protects identity/legal semantics, not old developer billing rows. There is no requirement to preserve historical direct-payment readability because the authoritative product baseline confirms there are no production billing customers/data obligations. If that baseline changes, the reset contract is invalid and must be redesigned.

### Verification matrix required in the durable artifact

The artifact must define future proof obligations, without implementing them in `ANY-509`:

- fresh database bootstrap reaches the new Alembic head and contains only retained + target tables;
- retained identity/session/legal behavior from `ANY-504` Step 3 survives the clean baseline, including preservation of core `/api/auth/session` while removing its old billing-derived `product_state`;
- legacy Portal trial persistence/lifecycle is removed without accidentally emitting free/trial grants through paid `AccessSnapshot`;
- the one-contour identity baseline approved by `ANY-504` Step 3 no longer depends on the old `eu`/DE/ES seed rows in the `ru` data plane;
- no old Portal-owned catalog/provider/commerce/subscription-entitlement tables remain;
- no CloudPayments/provider-registry runtime/config/frontend dependency remains, and direct-CloudPayments implementation work such as `ANY-168` is no longer executable into `ANY-504` Step 4;
- one customer slot is race-safe per `(external_billing_account_id, user_id)` and a `billing_customer_key` cannot be reused;
- one product scope row serializes `(user_id, product_id)` purchase/primary decisions;
- duplicate client retries do not create a second business flow once the `ANY-504` Step 7 idempotency contract is implemented;
- ambiguous external create persists UNKNOWN, survives restart, holds scope, and does not blind-retry;
- mapping revisions and accepted purchase snapshots remain immutable;
- `billing_state_observations` survive restart and later projection replacement, preserve normalized authoritative-read/discovery/primary/deterministic-boundary evidence, and link any evidence-driven semantic change to the resulting access revision without retaining raw provider/payment history;
- purchased allowance quantity and effective tuple remain immutable and runtime `remaining` is absent from Portal;
- same-cycle block/unblock preserves `allowance_id` and Kernel usage identity after `ANY-504` Step 9/10;
- known user with no `paid_access_states` row returns implicit revision zero without writes after `ANY-504` Step 10;
- every semantic paid-access change creates a monotonic revision and durable outbox update atomically;
- duplicate/out-of-order webhooks do not directly grant access and converge through the same transition as reconciliation;
- billing work claims/retries and reconciliation fencing prevent stale workers from committing;
- deterministic due-time work can remove only the due paid fact without provider HTTP;
- invalidation coalescing and in-flight acknowledgement races cannot lose a newer revision;
- manual review cannot directly create entitlement/allowance authority;
- stale/conflicting provider facts fail closed at the affected fact/metric scope rather than globally where independent facts remain valid;
- generated schema/OpenAPI, current-state docs, and architecture guards reflect the clean baseline.

### No new guard in ANY-509

Do not add a brittle content-specific architecture guard for the new design document in this ticket. `ANY-505` already protects the canonical authority chain and current-document classifications. `ANY-509` should add the new artifact to `docs/README.md` as an implementation handoff subordinate to the three canonical target sources. `ANY-504` Step 4 and later runtime steps own executable schema/concurrency/contract tests and any architecture guards justified by real code.

---

# ANY-509 Step 1 - Establish the current-state persistence and legacy-removal inventory

**Status:** `complete`

**Goal**

Create the durable target-persistence/reset artifact with an explicit, evidence-backed current-state inventory and legacy-removal matrix. Correct the stale deployment diagram so all authoritative current-state documentation agrees that CloudPayments is deactivated in normal runtime.

**Scope / affected code**

- create `docs/architecture/external-billing-persistence-reset.md`;
- update only the stale current-runtime portion of `docs/architecture/deployment.md`;
- no application, model, migration, test, frontend, configuration, or generated-file changes in this step.

**Implementation decisions**

1. Give the new artifact a clear status such as `implementation handoff under ADR 0005 and the accepted billing designs`. It must explicitly state that it is subordinate to, and cannot override, ADR 0005 or either accepted design specification.
2. Record the no-production reset premise with evidence from current authoritative repository docs and `ANY-504` / `ANY-509`. State the explicit STOP condition if production billing/customer-data obligations appear before `ANY-504` Step 4.
3. Record the merged predecessor (`ANY-505`, PR #113) and the completed runtime deactivation baseline (`ANY-457`).
4. Add the complete 26-table disposition matrix from this plan, preserving the exact classification and rationale.
5. Add a runtime/code-surface matrix covering at least:
   - current model modules and Alembic revisions;
   - `app.domains.identity.services.checkout`;
   - `app.domains.identity.services.account`, especially the billing-derived `/api/auth/session?product` `product_state` projection and `load_payment_status()` consumer of old catalog/order/payment/entitlement persistence;
   - old billing catalog/account/lifecycle services and routers, including the exported legacy `start_trial()` path, trial/entitlement semantics, and `apps/api/app/commands/expire_subscriptions.py`;
   - `app.payment_providers`;
   - `app.integrations.cloudpayments`, `app.cloudpayments.py`, retained sandbox script/support code;
   - old query/persistence helpers;
   - settings/configuration;
   - `/api/catalog/products`, `/api/auth/checkout-intent`, `/api/account/subscriptions*`, `/api/auth/payment-status`, and the billing-derived optional `product_state` extension on `/api/auth/session`;
   - frontend catalog/checkout/account-subscription clients, CloudPayments adapter/types, payment-result polling, and all current routes that consume those APIs (`/ru`, `/ru/products`, `/ru/auth-checkout`, `/ru/account`, `/ru/payment-result`);
   - old migration/schema tests, CloudPayments tests, old billing lifecycle/commercial tests, and retained identity/legal/architecture tests;
   - current-state/generated documentation.
6. Classify each material surface as retain/adapt, replace with target, remove in `ANY-504` Step 4, or defer to a named later step. Do not leave an unowned "keep for now" bucket.
7. Record that no durable target worker/job/outbox/reconciliation substrate exists today; only retained/legacy scheduled behavior such as the expiry CLI exists.
8. Add the `ANY-504` Step 3 handoff boundary: this ticket locks retention intent and provider-independent invariants, but `ANY-504` Step 3 owns the final physical identity/session/legal shape. `ANY-504` Step 3 must leave append-only acceptance evidence that directly binds the exact accepted commercial fingerprint/offer to the required versioned legal-document set. `entrypoint_sessions` may survive only if `ANY-504` Step 3 confirms a provider-independent identity/legal/origin role; old product/bundle foreign-key semantics are not target authority. `ANY-504` Step 3 must also resolve the current transitional multi-contour identity behavior before `ANY-504` Step 4 removes foreign-contour seed data: current registration accepts a client-supplied `region` and current tests include independent `ru`/`eu` accounts for the same email, while the target deployment is one contour per instance. `ANY-504` Step 4 must not delete the `eu`/DE/ES bootstrap rows while identity regression tests approved by `ANY-504` Step 3 still require that old behavior.
9. In `docs/architecture/deployment.md`, remove the active Browser -> CloudPayments widget and CloudPayments -> API webhook edges from the current-runtime diagram/description. Replace them with the factual deactivated state: checkout unavailable, no normal CloudPayments runtime/callback path. Also replace the stale statement that future Platform Kernel access is described by the old ANY-71-era contract with the current ADR 0005 / accepted Portal-Kernel authority. Do not redesign the future deployment topology in this step.
10. Record the discovered stale deployment doc as resolved by this focused change; do not opportunistically rewrite unrelated product/deployment documentation.

**Invariants**

- Current-state classification must agree with `main` after merged ANY-505 and ANY-457.
- The artifact cannot make the current Portal `Product`, `Plan`, `Order`, `Payment`, `Subscription`, or `Entitlement` model target authority.
- CloudPayments is transitional retained source only until `ANY-504` Step 4 cleanup; external billing is never a `PaymentProviderAdapter`.
- The `ANY-504` Step 3 identity/session/legal handoff remains open for physical refinement.
- No provider-dependent LBX assumption is promoted to an accepted persistence constraint.

**Out of scope**

- defining all target entity fields/constraints - `ANY-509 Step 2`;
- changing SQLAlchemy models or enums;
- editing Alembic revisions;
- deleting CloudPayments or old billing code;
- changing public API behavior;
- changing frontend runtime behavior;
- adding architecture guards or tests;
- running LBX probes.

**AI prompt**

Implement only `ANY-509 Step 1` of `ANY-509-implementation-plan`: establish the current-state persistence and legacy-removal inventory.

The implementation plan is already researched and approved for execution. Follow the decisions defined in this prompt and in `ANY-509 Step 1` exactly. Do not perform broad repository research and do not redesign the architecture. Inspect only the directly relevant current documentation/files if needed to verify that a referenced path or factual statement still matches the repository after predecessor work.

Create `docs/architecture/external-billing-persistence-reset.md` as the single durable ANY-509 persistence/reset handoff. In `ANY-509 Step 1`, populate only the authority/baseline section, the no-production reset premise, the current 26-table disposition matrix, the runtime/code/API/frontend/test/documentation removal matrix, the absence of a current durable target job/outbox/reconciliation subsystem, the old-roadmap/executable-plan disposition, and the `ANY-504` Step 3 handoff boundary.

Use the exact current-table dispositions and runtime classifications specified in `ANY-509 Step 1` and in the plan's locked research decisions. Explicitly include the hidden cross-domain consumers already identified by research: `app.domains.identity.services.account`, `/api/auth/session?product` + `product_state`, `/api/auth/payment-status`, payment-result polling, and the legacy trial lifecycle. Also record the one-contour `ANY-504` Step 3 handoff and the fact that `ANY-168` is still In Progress but conflicts with the ANY-504 cleanup direction. Every material legacy surface must have an explicit owner/disposition; do not leave vague "temporary" ownership. Make clear that the document is subordinate to ADR 0005 and the two accepted design specifications and is not a competing ADR.

Also update only the stale current-runtime/authority statements in `docs/architecture/deployment.md`: normal runtime no longer loads/invokes CloudPayments, checkout is unavailable, and no CloudPayments callback path is mounted. Remove the active CloudPayments widget/webhook arrows from the current diagram. Replace the stale ANY-71-era future-access authority reference with ADR 0005 / the accepted Portal-Kernel design. Do not redesign future deployment architecture.

Implement only this step. Do not work on the target table definitions, reset sequence, Phase 0 gate register, verification matrix, or documentation index yet; those belong to later `ANY-509` steps in this plan.

Do not perform broad repository research. Inspect only directly relevant files when needed to verify a plan assumption. Do not redesign the architecture. Do not perform unrelated refactoring. Do not work on future steps.

Do not run tests, linters, formatters, documentation checks, generators, or any other automated verification commands. Do not stage files. Do not create commits.

After implementation, report:
1. every changed file;
2. the current-state table/runtime classification added;
3. the stale deployment statement that was corrected;
4. any material contradiction with the plan assumptions.

Report the exact manual verification commands I should run. If current code or authoritative documentation materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

**Manual verification**

```bash
git diff --check
npm run docs:check
npm run architecture:check
```

**Expected completion**

- The repository contains one clear ANY-509 persistence/reset handoff document.
- All 26 current tables and material retained CloudPayments/commerce surfaces have an explicit disposition.
- The no-production reset premise and STOP condition are explicit.
- `ANY-504` Step 3 ownership of physical identity/session/legal details is explicit.
- `docs/architecture/deployment.md` no longer describes CloudPayments as active normal runtime and no longer points future access authority at the obsolete ANY-71-era contract.
- No target schema or destructive implementation has been performed yet.

**Proposed commit**

`docs(architecture): inventory persistence reset scope`

---

# ANY-509 Step 2 - Define the target persistence contract and provider-evidence gates

**Status:** `complete`

**Goal**

Complete the target persistence portion of the durable artifact so `ANY-504` Step 4 can build the clean schema without re-deciding ownership, table boundaries, stable keys, concurrency semantics, or which provider-dependent constraints must remain gated.

**Scope / affected code**

- extend `docs/architecture/external-billing-persistence-reset.md` only;
- no code/model/migration/test/frontend/config/generated-file changes.

**Implementation decisions**

1. Add the exact 15-table target physical model from the locked research section:
   - `capability_manifest_projections`;
   - `external_billing_catalog_projections`;
   - `commercial_mapping_revisions`;
   - `external_billing_customers`;
   - `billing_product_access_scopes`;
   - `purchase_intents`;
   - `external_create_operations`;
   - `external_subscriptions`;
   - `billing_state_observations`;
   - `purchased_allowances`;
   - `paid_access_states`;
   - `external_billing_webhook_deliveries`;
   - `billing_work_items`;
   - `access_invalidation_outbox`;
   - `manual_review_cases`.
2. For every target table document:
   - owner and source of truth;
   - stable internal/external identifiers and scope;
   - a physical-schema contract consumable by `ANY-504` Step 4, listing every planned persisted field by semantic/physical name, storage type family, nullability/default, PK role, FK target and deletion behavior where applicable, unique/check/index requirement, and mutability;
   - required foreign-key relationships;
   - confirmed uniqueness/check/immutability rules;
   - lifecycle/state vocabulary when closed and application-owned;
   - concurrency/idempotency role;
   - which fields are audit/evidence versus authority;
   - retention expectations;
   - evidence level using exactly `ACCEPTED_ARCHITECTURE_REQUIREMENT`, `DOCUMENTED_PROVIDER_FACT`, `VENDOR_CONFIRMED`, `CONFIRMED_ON_TEST`, or `GATED / UNVERIFIED`;
   - implementation gate using exactly `STEP_4_SAFE`, `PHASE_0_GATED`, or `LATER_STEP_RUNTIME`, with the owning later `ANY-504` step named for `LATER_STEP_RUNTIME`;
   - both classifications independently for every field/constraint whose semantics are not purely structural.
   The artifact must be concrete enough that `ANY-504` Step 4 does not invent columns, nullability, FKs, or provider-independent uniqueness rules. Exact SQLAlchemy syntax and incidental index names may still follow repository conventions during implementation. For later-owned/open vocabularies, explicitly record that the physical value remains text/open and that no premature persisted `StrEnum`/DB check is added until the owning later step closes the vocabulary. For `PHASE_0_GATED` semantics, distinguish a provider-neutral nullable opaque storage slot that is safe to create in `ANY-504` Step 4 from a provider-specific uniqueness/check/identity rule that must remain absent until Phase 0 evidence.
3. Use the exact stable storage contracts in the locked research section. Do not split complete capability/catalog projections or immutable mapping/purchase/access snapshots into table-per-item trees unless a real current requirement makes that necessary. Prefer validated, schema-versioned Pydantic snapshot documents persisted atomically where the design requires all-or-nothing LKG or immutable snapshot behavior.
4. Record `external_billing_account_id` as stable non-secret runtime/configuration scope, not as a provider-account catalog table. Explicitly prohibit secrets/payment credentials in persistence.
5. Lock `external_billing_customers` local uniqueness on `(external_billing_account_id, user_id)` and `(external_billing_account_id, billing_customer_key)` and permanent key non-reuse. Do not treat email/phone/name as identity.
6. Lock `(user_id, product_id)` serialization through `billing_product_access_scopes` and the complete observe-before-lock first-primary algorithm from the locked storage contract, including durable normalized observation before the short product-scope transaction, union re-read under lock, deterministic zero/one/many decision rules, and no implicit promotion/replacement heuristics. Do not introduce a separate primary-decision generation subsystem.
7. Lock one unified `external_create_operations` model for customer/agreement/subscription create uncertainty. Preserve durable UNKNOWN, fixed two-hour escalation, no blind create retry, and no zero-match absence inference.
8. Lock the proven-subscription-only rule for `external_subscriptions`, projection freshness fields, reconciliation fencing storage, historical-row retention needed for identity/recovery/audit, and the accepted normalized vocabularies: lifecycle `active|inactive|ended`, financial access `allowed|blocked`, commercial access `eligible|ineligible`. Do not enforce the unproven LBX canonical subscription/agreement uniqueness constraints before Phase 0.
9. Lock `billing_state_observations` as the append-only minimized evidence boundary for authoritative subscription reads, target-product discovery, first-primary selection, and deterministic access-reducing boundaries. Require typed normalized payloads, immutable evidence meaning, safe references to the affected local state, and optional `resulting_access_revision`; forbid raw provider payload archives, payment ledgers, and a second business state machine.
10. Lock purchased allowance integer quantity, `quantity >= 0`, valid effective half-open interval with `period_start < period_end`, immutable effective tuple, and absence of runtime `remaining`. Mark provider cycle identity/uniqueness as Phase 0 gated.
11. Lock `paid_access_states` as the current committed provider-neutral semantic snapshot with implicit revision zero when absent. Lock semantic scope as `(tenant_id, region, canonical Portal user_id)`, but explicitly delegate only the physical representation of tenant/region in the table/FK key to the `ANY-504` Step 3 -> Step 4 handoff. Any semantic change must increment revision and update the invalidation outbox atomically; GET/read paths never create or mutate access state.
12. Lock one shared `billing_work_items` substrate. Do not create separate urgent/recovery/deadline schedulers, and do not make in-memory/FastAPI background work correctness authority.
13. Lock minimal/redacted webhook evidence and manual-review semantics. Neither webhook payload nor manual review directly grants access. Add the durable audit/evidence-source matrix from the locked research section and map successful authoritative-read/reconciliation, first-primary, and deterministic-boundary proof to `billing_state_observations`; current mutable projections or logs alone are insufficient.
14. Lock projection/mapping identity semantics needed by future steps: `product_id`/`metric_key` remain Kernel identifiers without Portal catalog FKs; external offer/component IDs remain opaque rather than Portal catalog FKs; manifest/catalog admission freshness is 24h for new mapping/purchase only; `commercial_mapping_revisions` have explicit `(external_billing_account_id, billing_offer_id)` scope, immutable monotonic revision-number current selection, and pin manifest version + catalog version/digest.
15. Add the complete Phase 0 gate register from the locked research section, including all GitHub issue #112 identity/Widget/JWT/subscription-list concerns.
16. For every gate, name the later owner. Provider-dependent unknowns are expected and are not blockers to completing ANY-509 as long as they are explicitly gated.
17. State that provider-specific identifiers may be stored only at the Integration/persistence edge as opaque evidence/bindings and must not appear in Portal-Kernel contracts or canonical Application/Domain provider-neutral contracts.
18. State the schema-evolution rule: Step 4 freezes the provider-independent clean baseline, while Phase 0 and Steps 6-10 may add reviewed provider-facing fields/indexes/constraints through ordinary forward migrations when evidence requires them. Such changes may not alter the authority boundaries or silently recreate Portal-owned catalog/order/payment/provider-account semantics.
19. Keep canonical ORM ownership in `app.models` and canonical persisted closed vocabularies in `app.models.enums`; do not propose a parallel pure-domain entity model, generic repository layer, generic UoW, or speculative billing framework.

**Invariants**

- External Billing remains commercial authority; Portal stores projections/orchestration/evidence, not a shadow payment ledger.
- Kernel remains technical product/metric and actual-usage/quota authority.
- Portal owns identity/legal acceptance, mapping/purchase snapshots, recovery/projection, and provider-neutral paid access.
- All target storage can be implemented before LBX stand only where provider-independent.
- Phase-0-dependent identifiers/constraints remain visibly gated.
- No provider network call may require an open business transaction.
- Webhook/reconciliation paths must later feed the same Application transition.
- One access revision corresponds to one immutable provider-neutral effective semantic state.
- Portal never stores authoritative runtime remaining quota.

**Out of scope**

- `ANY-504` Step 3 physical identity/session/legal changes;
- creating SQLAlchemy classes or enums;
- creating migrations;
- writing workers, HTTP clients, Widget/JWT code, webhook routes, reconciliation, or AccessSnapshot endpoints;
- choosing/implementing exact LBX identity/agreement/subscription/cycle rules before Phase 0;
- creating a generic provider framework;
- adding repository classes per table;
- changing frontend behavior.

**AI prompt**

Implement only `ANY-509 Step 2` of `ANY-509-implementation-plan`: define the target persistence contract and provider-evidence gates inside the existing `docs/architecture/external-billing-persistence-reset.md` artifact created by `ANY-509 Step 1`.

The implementation plan is already researched and approved for execution. Follow the decisions defined in this prompt and `ANY-509 Step 2` exactly. Do not perform broad repository research and do not redesign the target model. Inspect only directly relevant current files if needed to verify that a referenced name or assumption still matches the repository after `ANY-509 Step 1`.

Add the exact 15-table target physical model and document each table's ownership, source of truth, keys/scope, confirmed constraints, immutability, lifecycle, concurrency/idempotency role, audit-vs-authority role, retention, evidence level, and implementation gate. For each table, include a physical-schema matrix for `ANY-504` Step 4 covering every planned persisted field: semantic/physical name, storage type family, nullability/default, PK/FK role and deletion behavior where applicable, unique/check/index requirement, mutability, evidence level, implementation gate, and later owner when deferred. `ANY-504` Step 4 must not need to invent provider-independent columns, nullability, FKs, or uniqueness rules. For open later-owned vocabularies, keep storage open/text and do not prematurely define persisted enums/checks. For Phase-0-gated semantics, distinguish safe nullable opaque storage slots from constraints that must not be installed before evidence. Use the target table list and stable storage contracts from the plan verbatim as the design baseline.

Use typed, schema-versioned structured snapshots for the complete LKG capability manifest, complete normalized billing catalog, immutable mapping document, immutable accepted purchase snapshot, and current committed provider-neutral effective access state. These snapshots must be validated by explicit Pydantic contracts when later implemented; do not describe them as arbitrary dictionaries.

Use the exact evidence taxonomy from this plan and keep it independent from the implementation-gate taxonomy. Also encode the complete observe-before-lock first-primary algorithm, the mandatory durable customer identity-conflict state, the explicit paid-access scope decision, and the durable audit/evidence-source matrix. Persist normalized authoritative-read/reconciliation, target-product discovery, first-primary-decision, and deterministic-boundary evidence in the reviewed `billing_state_observations` table so it survives projection replacement/restart; do not rely on logs or the latest mutable subscription row alone. Keep that table bounded, normalized and non-authoritative rather than turning it into a raw provider event store or payment ledger.

Preserve the existing architecture mechanics: canonical ORM in `app.models`, closed persisted `StrEnum` vocabularies in `app.models.enums`, Application-owned business transactions/idempotency/transitions, focused persistence mechanics, no repository-per-table layer, and no provider network I/O inside business transactions.

Add a Phase 0 gate register. Explicitly keep Widget `ident_type`, exact `outer_id` behavior, Widget credential/security behavior, canonical LBX subscription identity, agreement lifetime uniqueness, authoritative commercial read set, prepaid semantics, quantity source, provider cycle identity, customer subscription-list completeness, and any safe absence predicate as `PHASE_0_GATED`. `ident_type=6` must be recorded only as a documented candidate, never as an accepted production fact.

Implement only this step. Do not define the clean Alembic reset sequence, bootstrap order, final verification matrix, or docs index yet. Do not modify application code, models, migrations, tests, frontend, configuration, or generated files.

Do not perform broad repository research. Inspect only directly relevant current files when needed to verify a plan assumption. Do not redesign the architecture. Do not perform unrelated refactoring. Do not work on future steps.

Do not run tests, linters, formatters, documentation checks, generators, or any other automated verification commands. Do not stage files. Do not create commits.

After implementation, report:
1. every changed file;
2. the target table set and key stable constraints documented;
3. the Phase 0 gated constraints and their later owners;
4. any material contradiction with the plan assumptions.

Report the exact manual verification commands I should run. If current code or authoritative documentation materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

**Manual verification**

```bash
git diff --check
npm run docs:check
```

**Expected completion**

- The durable artifact defines a complete provider-independent target persistence model.
- `ANY-504` Step 4 no longer needs to decide table ownership, target logical boundaries, stable provider-independent keys, or core concurrency/idempotency storage roles.
- Every stand-dependent provider rule is explicitly gated instead of guessed.
- The model does not recreate Portal-owned commerce/payment ledgers or introduce a generic provider framework.
- No executable schema/runtime implementation has been performed.

**Proposed commit**

`docs(architecture): define target persistence contract`

---

# ANY-509 Step 3 - Lock the clean-reset handoff, verification matrix, and documentation index

**Status:** `complete`

**Goal**

Finish the ANY-509 artifact as an implementation-ready handoff to `ANY-504` Step 4: exact clean-reset/bootstrap strategy, dependency/removal order, the `ANY-504` Step 3 -> Step 4 handoff rule, verification obligations, later-step deferrals, and repository documentation indexing.

**Scope / affected code**

- complete `docs/architecture/external-billing-persistence-reset.md`;
- update `docs/README.md` to index the artifact as a subordinate implementation handoff;
- no application/model/migration/test/frontend/config/generated-file changes.

**Implementation decisions**

1. Add the clean-reset contract exactly as locked in the research section:
   - immediate no-production recheck and STOP condition;
   - `ANY-504` Step 3 final physical identity/session/legal baseline first;
   - remove old API/frontend/runtime consumers before allowing deleted persistence symbols to remain required;
   - remove old Portal-owned commerce/direct-provider models/code/config/tests;
   - treat current `0001`-`0005` only as the researched baseline and replace the **entire pre-reset Alembic history present when `ANY-504` Step 4 begins**, including any Step-3 identity/session/legal revisions, with one fresh first-install baseline / one Alembic head;
   - no data-preserving forward business migration, dual write, backfill, or coexistence layer while the no-production premise holds;
   - recreate dev/test/pre-production databases;
   - no Portal catalog/provider seed in the target baseline;
   - target projections/work/outbox/manual-review tables start empty;
   - legal bootstrap remains driven by the canonical legal source/manifest and the final `ANY-504` Step 3 shape;
   - bootstrap only contour-local data consistent with the final one-contour `ANY-504` Step 3 contract; do not perpetuate `eu`/DE/ES seed rows inside the `ru` data plane merely because the old migration contained them;
   - generated schema/OpenAPI artifacts are regenerated only by `ANY-504` Step 4 tooling.
2. Define the `ANY-504` Step 4 dependency/removal order explicitly enough to avoid circular legacy dependencies:
   1. verify premise and consume `ANY-504` Step 3 handoff;
   2. remove/neutralize old backend public consumers and frontend calls;
   3. remove old billing/application/integration/provider/config consumers;
   4. install retained + target canonical model/enums;
   5. replace the Alembic baseline and bootstrap;
   6. rewrite/delete old persistence/migration/provider tests and add target schema/concurrency tests;
   7. regenerate schema/OpenAPI/docs;
   8. prove no removed imports/config/API/frontend dependencies remain.
3. State that the public legacy billing APIs are removed in `ANY-504` Step 4 rather than kept as accidental compatibility contracts. A neutral unavailable frontend shell may remain, but it cannot call removed endpoints. Target catalog/purchase/account surfaces are introduced only by their later owners.
4. Add an explicit `ANY-504` Step 3 handoff checklist. `ANY-504` Step 4 must re-read only the retained identity/session/legal rows affected by `ANY-504` Step 3 and update their physical details in the artifact before schema implementation; it must confirm that accepted commercial evidence directly binds the exact commercial fingerprint/offer and required versioned legal documents; it must confirm that the one-contour identity/session tests approved by `ANY-504` Step 3 no longer depend on the old cross-contour seed/registration behavior before removing `eu`/DE/ES bootstrap rows; and it must resolve only the physical representation of the already-locked `(tenant_id, region, user_id)` paid-access scope (stored tenant/region columns versus derivation through the final canonical user/contour model) so `paid_access_states` and `access_invalidation_outbox` serialize the exact same scope. It must not reopen external-billing ownership, target table boundaries, or Phase 0 gates without a concrete contradiction.
5. Add the full verification matrix from the locked research section and map each proof to its owning future step. Mark which proofs are migration/schema tests, PostgreSQL concurrency tests, application/idempotency tests, architecture/static checks, contract tests, or E2E evidence.
6. Add the explicit later-step ownership/deferral table for `ANY-504` Steps 3-11. No runtime implementation from later steps may be hidden inside `ANY-504` Step 4 merely because its storage exists. Include the old-roadmap disposition: `ANY-168` / direct-CloudPayments roadmap must not remain executable before `ANY-504` Step 4; `ANY-79` / `ANY-286` / `ANY-287` must not execute as written and remain `ANY-504` Step 10 rewrite/supersede work; canceled `ANY-497` is historical only.
7. Add the documentation-removal/update handoff for `payment-portal-data-model.md`, `payment-providers.md`, `docs/product/ru-mvp.md`, `ARCHITECTURE.md`, `docs/PRODUCT.md`, `docs/RELIABILITY.md`, `README.md`, generated schema/OpenAPI, and any current architecture guard whose required classification becomes false after direct-provider source is physically removed.
8. Add security/audit retention rules:
   - no billing secrets/card credentials in DB;
   - opaque immutable non-PII billing customer key;
   - minimized/redacted webhook/recovery/manual-review evidence;
   - enough durable evidence to explain why access was granted, omitted, blocked, or put into review;
   - no legal/regulatory retention period is invented without Legal/Finance authority.
9. Document the `STEP_4_SAFE`, `PHASE_0_GATED`, and `LATER_STEP_RUNTIME` meanings in one concise implementation-gate table.
10. State explicitly that no new ANY-509-specific architecture guard is required. Existing ANY-505 precedence checks remain authoritative; executable schema/runtime guards belong to `ANY-504` Step 4 and later implementation tickets.
11. Update `docs/README.md` under a new or existing implementation-handoff/reference subsection. Do not insert the new artifact into the three-item canonical authority chain as an equal or higher authority. Describe it as the reviewed `ANY-504` Step 2 persistence/reset handoff under ADR 0005 and the two accepted design baselines.
12. End the artifact with an `ANY-504` Step 4 readiness checklist containing no unresolved provider-independent design question. The only remaining unknowns should be explicitly named `ANY-504` Step 3 physical refinements or Phase 0/later-runtime gates.

**Invariants**

- Destructive reset remains conditional on the verified no-production premise.
- `ANY-504` Step 3 is allowed to refine retained identity/session/legal physical details without invalidating the target billing design.
- No old commerce compatibility path is preserved without a real production obligation.
- Provider-dependent production semantics remain Phase 0 gated.
- Empty target projections after `ANY-504` Step 4 are valid; later steps populate them.
- Documentation hierarchy remains ADR 0005 -> external-billing design -> Portal-Kernel design -> subordinate implementation handoff.

**Out of scope**

- executing the reset;
- deleting migrations/source/tests;
- writing target ORM classes;
- generating schema/OpenAPI;
- creating API/runtime behavior;
- adding `ANY-504` Step 4 migration tests now;
- changing legal source content;
- running LBX Phase 0;
- updating Platform Kernel repository.

**AI prompt**

Implement only `ANY-509 Step 3` of `ANY-509-implementation-plan`: finalize the clean-reset handoff, verification matrix, later-step ownership, and documentation index.

The implementation plan is already researched and approved for execution. Follow the decisions defined in this prompt and `ANY-509 Step 3` exactly. Do not perform broad repository research and do not redesign the target persistence model created in `ANY-509 Step 2`. Inspect only directly relevant current files if needed to verify that a referenced path or documentation heading still matches the repository.

Complete `docs/architecture/external-billing-persistence-reset.md` with the exact clean-reset strategy, `ANY-504` Step 4 dependency/removal order, the `ANY-504` Step 3 -> Step 4 handoff rule, implementation-gate definitions, security/audit rules, future verification matrix, explicit `ANY-504` Steps 3-11 ownership/deferrals, and final `ANY-504` Step 4 readiness checklist from the plan.

The reset contract must replace the entire pre-reset Alembic history that exists when `ANY-504` Step 4 begins (the current researched chain is `0001`-`0005`, but Step 3 may add revisions) with one fresh first-install baseline / one Alembic head only after the no-production premise is revalidated and `ANY-504` Step 3 has finalized retained identity/session/legal persistence. Do not design a data-preserving business migration, dual write, old/new compatibility layer, or legacy billing backfill under the current baseline. Target projections start empty; legal/bootstrap data follows the canonical legal source and final `ANY-504` Step 3 contract; a `ru` instance must not perpetuate foreign-contour bootstrap rows merely because old migrations did.

Make the `ANY-504` Step 4 removal order explicit: remove/neutralize old API/frontend consumers, remove old billing/provider/integration/config consumers, install retained + target canonical models, replace the Alembic baseline, rewrite schema/concurrency tests, regenerate generated artifacts, then prove no removed dependency remains. Explicitly preserve core `/api/auth/session` identity/session behavior while removing its old catalog/entitlement-derived `product_state` extension; remove old `/api/auth/payment-status`; classify the legacy trial lifecycle as removed Portal-owned access state; and require affected frontend routes to stop polling/calling deleted billing APIs rather than shipping a broken intermediate UI.

Record the one-contour `ANY-504` Step 3 handoff condition and the related-roadmap precondition: `ANY-504` Step 4 must not begin while identity tests approved by `ANY-504` Step 3 still require the old `ru`+`eu` seed behavior, and direct CloudPayments implementation work such as `ANY-168` must no longer be executable. Record `ANY-79`/`ANY-286`/`ANY-287` as `ANY-504` Step 10 rewrite/supersede work, not executable current contracts.

Add the future verification matrix from the plan and assign each proof to its owning later step. Do not implement those tests or runtime behaviors in ANY-509. Include explicit documentation-update ownership for the current data-model/provider/product-journey documents and guards that become stale after physical removal.

Update `docs/README.md` so the new document is discoverable as a subordinate `ANY-504` Step 2 implementation handoff. Do not modify the canonical three-document target authority chain or add a new content-specific architecture guard.

Implement only this step. Do not modify application code, SQLAlchemy models, Alembic revisions, tests, frontend code, configuration, generated files, or Platform Kernel.

Do not perform broad repository research. Inspect only directly relevant current files when needed to verify a plan assumption. Do not redesign the architecture. Do not perform unrelated refactoring. Do not work on future steps.

Do not run tests, linters, formatters, documentation checks, generators, or any other automated verification commands. Do not stage files. Do not create commits.

After implementation, report:
1. every changed file;
2. the clean-reset and `ANY-504` Step 3 handoff contract finalized;
3. the verification/deferral matrix added;
4. how `docs/README.md` indexes the artifact without changing the canonical authority hierarchy;
5. any material contradiction with the plan assumptions.

Report the exact manual verification commands I should run. If current code or authoritative documentation materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

**Manual verification**

```bash
git diff --check
npm run docs:check
npm run architecture:check
npm run check:fast
```

**Expected completion**

- `docs/architecture/external-billing-persistence-reset.md` is complete and reviewable as the direct implementation handoff for `ANY-504` Step 4.
- The target model, current-to-target removal matrix, reset/bootstrap contract, `ANY-504` Step 3 handoff, evidence gates, security/audit rules, verification matrix, and later-step ownership are all explicit.
- There is no unresolved provider-independent design decision that `ANY-504` Step 4 would need to invent.
- Remaining unknowns are intentionally limited to `ANY-504` Step 3 physical refinements or explicitly named Phase 0/later-runtime gates.
- The artifact is discoverable in `docs/README.md` without being promoted above ADR 0005 or the accepted design specifications.
- No destructive persistence/runtime implementation has occurred in ANY-509.

**Proposed commit**

`docs(architecture): finalize clean reset contract`

---

## Definition of Done for ANY-509

- `ANY-509 Step 1`, `ANY-509 Step 2`, and `ANY-509 Step 3` are completed sequentially, each reviewed and manually verified before the next starts.
- The durable artifact is present at `docs/architecture/external-billing-persistence-reset.md`.
- The artifact is explicitly subordinate to ADR 0005 and the two accepted design baselines.
- All 26 current tables and material backend/frontend/config/test/docs surfaces have an explicit retain/adapt/replace/remove/defer disposition.
- The target persistence model uses the defined 15 target tables plus the retained identity/session/legal baseline finalized by `ANY-504` Step 3; the additional `billing_state_observations` table is the bounded append-only evidence boundary required by the accepted audit semantics, not a commerce/event-sourcing subsystem.
- The clean-reset strategy is based on a revalidated no-production premise and contains an explicit STOP condition if that premise changes.
- `ANY-504` Step 4 can replace the entire pre-reset Alembic history present at execution time with one fresh first-install baseline / one head, without designing a business-data migration, dual-write layer, or generic provider framework.
- Every non-structural field/constraint has both an exact evidence level and an independent implementation gate; exact LBX identity, Widget security, subscription/agreement identity, cycle semantics, list completeness, and provider absence rules remain explicit `PHASE_0_GATED` items.
- Provider-independent concurrency/idempotency invariants are defined: customer-slot uniqueness and durable conflict state, product-scope serialization with the observe-before-lock first-primary algorithm, durable UNKNOWN, reconciliation fencing, immutable purchase/mapping/allowance state, revision + outbox atomicity, and one shared durable work substrate.
- No provider/vendor values leak into Portal-Kernel contracts or canonical provider-neutral Application/Domain contracts.
- Portal does not recreate a payment/refund ledger and does not store authoritative remaining quota.
- Manual review and webhook evidence are durable but never access authority; successful authoritative-read/reconciliation, complete discovery/primary-decision, and deterministic-boundary evidence is durably retained in `billing_state_observations` without relying on logs or overwritten current projections.
- `ANY-504` Step 3 physical identity/session/legal ownership is respected and has an explicit handoff checkpoint before `ANY-504` Step 4, including resolution of the old cross-contour registration/seed behavior and only the physical representation of the already-locked `(tenant_id, region, user_id)` paid-access scope.
- Core `/api/auth/session` identity/session semantics are explicitly retained while its old Product/Plan/Entitlement-derived `product_state` extension and `/api/auth/payment-status` are classified for `ANY-504` Step 4 removal.
- Legacy Portal trial state is explicitly classified and cannot accidentally survive as target paid-access authority.
- `ANY-168` / the old direct-CloudPayments roadmap cannot remain executable into `ANY-504` Step 4; old ANY-79/286/287 contracts are explicitly non-executable pending their `ANY-504` Step 10 rewrite/supersede.
- `commercial_mapping_revisions` has an explicit account/offer publication scope with immutable monotonic revision-number current selection and pins capability manifest version plus billing-catalog version/digest; historical pins never rebind.
- Kernel `product_id` / `metric_key` and external offer/component identifiers remain direct canonical/opaque identifiers rather than recreating Portal-owned product/metric/catalog FK tables.
- Manifest/catalog LKG admission semantics preserve the accepted 24h new-sale/new-mapping freshness gate without retroactively revoking historical pins.
- Ended external-subscription projections are retained as required for identity/recovery/audit and future Phase-0-proven non-reuse constraints; no automatic hard-delete defeats those invariants.
- The artifact explicitly permits later evidence-backed forward migrations for provider-facing fields/indexes/constraints while forbidding later steps from changing authority boundaries or recreating Portal-owned commerce.
- `docs/architecture/deployment.md` reflects the deactivated CloudPayments current runtime.
- `docs/README.md` indexes the artifact as a subordinate implementation handoff.
- Relevant documentation/architecture checks and `check:fast` pass when run manually after the final step.
- No SQLAlchemy model, Alembic migration, destructive reset, CloudPayments deletion, LBX probe, production integration, worker, paid-access runtime, or Portal-Kernel endpoint is implemented by ANY-509 itself.
