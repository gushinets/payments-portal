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

`REPLACE WITH TARGET` records replacement intent only. The target tables,
fields, constraints, provider-evidence gates, and reset sequence are deliberately
not defined in this step.

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

The target design will require a shared durable work substrate, but its tables,
fields, constraints, scheduling semantics, and verification obligations are
outside `ANY-509` Step 1 and are not specified here.

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
