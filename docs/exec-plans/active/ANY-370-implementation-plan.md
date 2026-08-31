# ANY-370 — Load catalog products from backend API

## Plan Overview

| Field | Value |
| --- | --- |
| Project | `Payment portal` |
| Ticket | `ANY-370` |
| Linear status | `In Progress` |
| Overall implementation status | `todo` |
| Execution order | Sequential only: Step 1 → manual verification → commit → Step 2 → manual verification → commit → Step 3 → manual verification → commit → Step 4 |
| Steps / commits | 4 |
| Database migration | Not required |
| Implemented contour | `ru` only |

## How to Use This File

1. Put this file at:

```text
docs/exec-plans/active/ANY-370-implementation-plan.md
```

2. Start from the up-to-date `ANY-370` branch.

3. For Step 1 instruct the implementation AI only:

```text
Read docs/exec-plans/active/ANY-370-implementation-plan.md and implement only Step 1.
Follow the Step 1 prompt exactly.
Do not work on later steps.
Do not run automated checks.
```

4. Review the diff yourself and run the manual checks listed at the end of Step 1.

5. If they pass, create the specified Step 1 commit and mark Step 1 `done`.

6. Repeat the same process for each following step.

7. Do not ask the AI to implement multiple steps in one pass.

8. The implementation AI must not redo the ticket/repository/documentation research already captured in this file. It may inspect the explicitly listed files and direct dependencies required to edit them, but it must not perform broad repository searches, inspect unrelated Linear tickets, investigate alternative architectures, or redesign the solution.

9. If the current branch materially contradicts a locked assumption in this plan—for example a listed endpoint or model no longer exists—the AI must report the exact conflict instead of inventing a replacement architecture.

---

# Context and Locked Decisions

ANY-370 requires the frontend catalog to stop using hardcoded product definitions as its source of truth, load products from the backend, handle loading/error/empty states, and stop offering another purchase when existing access/subscription data says the user already owns the product.

The persistent catalog already exists. `Product` owns product identity and descriptive domain data. `Plan` owns region, price in minor units, currency, billing period, renewal mode, trial days, status and validity interval. No new product or plan persistence is required.

The current RU seed already contains:

```text
document-summary
  -> document-summary-pro
  -> 99000 RUB
  -> month
  -> 7 trial days

prompt-optimizer
  -> prompt-optimizer-pro
  -> 99000 RUB
  -> month
  -> 7 trial days
```

The catalog endpoint introduced by this ticket therefore reads existing `Product + Plan` state. It does **not** recreate the catalog in configuration, code, migrations, or frontend constants.

The implemented product surface remains the `ru` contour. Existing repository rules explicitly prohibit enabling another product contour as part of unrelated work.

The existing application already uses:

```python
DEFAULT_TENANT_ID = "anytoolai"
DEFAULT_REGION = "ru"
```

for the current implemented contour. ANY-370 must reuse the existing current-surface convention rather than inventing another contour configuration mechanism.

The authenticated subscription API already exists:

```text
GET /api/account/subscriptions
```

and returns the subscription plan, scope, status, renewal mode, current period, cancellation data and entitlement validity. ANY-370 must reuse this API rather than create a second ownership/subscription projection.

Current access is determined from entitlement validity, not from subscription lifecycle status alone:

```text
entitlement.status == active
AND valid_from <= now
AND valid_until > now
```

This rule comes from the Payment Portal data model and must remain consistent on frontend presentation.

The existing frontend hardcodes catalog commercial data in `catalog.ts`, and that data is consumed by `ProductCards`, `CheckoutClient`, `AccountClient`, and the RU home page.

`CheckoutClient` is particularly important: it currently uses the hardcoded product definition to validate the `product` query parameter and provide `plan_code` to `/api/auth/checkout-intent`. Therefore changing only the visible product cards would **not** satisfy ANY-370.

`AccountClient` currently also uses per-product:

```text
GET /api/auth/session?product=<code>
```

which exposes `inactive | pending | active | failed` product state. This behavior must not be deleted because doing so would regress existing pending-payment presentation.

The frontend catalog contains customer-facing RU marketing data which does not have an equivalent localized backend source:

- icon;
- `"Chrome extension"` presentation label;
- RU tagline;
- RU marketing description;
- RU feature/value-point list;
- free-tier copy such as `3 summaries per month` and `50 optimizations per month`.

These values may remain frontend presentation data.

They must **not** determine:

- whether a product exists;
- which plan is sellable;
- plan code;
- price;
- billing period;
- renewal mode;
- trial days;
- checkout payload.

The backend `Product.description` remains part of the API and is used as a fallback for products without known localized presentation metadata. For the existing two RU products, the current localized RU description remains presentation-only so ANY-370 does not regress the RU customer-facing locale.

`plan_limits` must not be used as a replacement for the existing free-tier marketing copy. The current paid plans contain limits of `1000`, which are purchased plan limits, not the hardcoded free-tier `3 / 50` copy currently shown by the portal.

### API contract locked for ANY-370

Introduce:

```text
GET /api/catalog/products
```

Public, read-only, no authentication required.

Response:

```json
{
  "products": [
    {
      "product_id": "uuid",
      "code": "document-summary",
      "name": "Document Summary",
      "description": "Chrome extension for document and web page summaries.",
      "plan": {
        "plan_id": "uuid",
        "code": "document-summary-pro",
        "name": "Document Summary Pro",
        "price_amount_minor": 99000,
        "currency": "RUB",
        "billing_period": "month",
        "renewal_mode": "manual",
        "trial_days": 7
      }
    }
  ]
}
```

The endpoint exposes only currently sellable direct-product offers:

```text
Product.status == active
Plan.status == active
Plan.scope_type == product
Plan.valid_from <= now
Plan.valid_to IS NULL OR Plan.valid_to > now
Plan.product_id == Product.id
tenant == current Payment Portal tenant
region == current RU contour
```

Bundles and `all_access` exist in the backend model but are **not** part of the current frontend product-card surface and must not be added by this ticket.

The current RU dataset contains one current direct product plan for each displayed product. ANY-370 does not introduce multi-plan selection UX.

If implementation encounters more than one current direct-product offer for the same product code, do **not** invent a first/latest/default-plan policy. Report the conflict instead of silently choosing a plan.

### Frontend contract validation

Repository conventions require `response.json()` to remain `unknown` until explicitly decoded. Components must not cast raw API JSON with `as CatalogProductsResponse` or duplicate API response types locally. Every new decoder requires rejection coverage for invalid input.

---

## Out of Scope for ANY-370

Do not implement any of the following:

- new database tables or columns;
- catalog migrations;
- bundle or all-access frontend cards;
- EU or US product surfaces;
- Region Resolver;
- future `/v1/me` or `/v1/me/entitlements` Account API from ANY-302;
- Platform Kernel entitlement API;
- duplicate active-order prevention from ANY-369;
- continuation of pending provider checkout from ANY-369;
- a new subscription-management page;
- the ANY-369 fix for the current manage-subscription CTA navigation;
- CloudPayments changes;
- payment-provider changes;
- subscription lifecycle/state-machine changes;
- catalog administration;
- product editing APIs;
- OpenAPI client generation;
- a frontend schema-validation dependency;
- a generic HTTP-layer refactor;
- moving all session-storage constants as unrelated cleanup;
- unrelated replacement of existing frontend type assertions.

ANY-302 separately owns the future public regional Account API.

ANY-369 separately owns duplicate active purchase orders and the incorrect manage-subscription CTA navigation behavior.

---

# Step 1 — Expose the current sellable product catalog from the backend

**Status:** `done`  
**Commit:** `feat(catalog): expose sellable product offers`

## Prompt

Implement Step 1 of ANY-370: expose the existing Payment Portal product catalog through a public read-only backend API.

The necessary research and architecture decisions are already recorded in this plan.

Do not inspect Linear, Git history, unrelated documentation, unrelated domains, or alternative designs.

Inspect only the files listed below and direct imports/types required to edit them.

## Goal

Create:

```text
GET /api/catalog/products
```

which returns the current sellable direct-product offers from the existing `Product` and `Plan` tables.

The frontend must be able to obtain product identity and all checkout-relevant commercial fields from this API.

No database schema change is required.

## Relevant existing code

Work primarily in:

```text
apps/api/app/models/catalog.py
apps/api/app/infrastructure/queries/products.py
apps/api/app/infrastructure/queries/plans.py
apps/api/app/domains/billing/
apps/api/app/domains/billing/enums.py
apps/api/app/domains/identity/session.py
apps/api/app/main.py
apps/api/tests/test_api.py
```

Use:

```python
app.core.time.utc_now
```

for current-time comparison.

Reuse the existing current-surface values:

```python
DEFAULT_TENANT_ID
DEFAULT_REGION
```

from the current identity/session implementation.

Do not create another copy of `"anytoolai"` / `"ru"` inside the new query or router and do not introduce new environment settings in this ticket.

## Implementation

### 1. Add a focused catalog read query

Add a query function in the existing infrastructure query area.

Preferred location:

```text
apps/api/app/infrastructure/queries/products.py
```

If keeping the Product/Plan join there would make the existing module materially unclear, a narrowly named:

```text
apps/api/app/infrastructure/queries/catalog.py
```

is acceptable.

Do not create a repository class, interface, unit-of-work abstraction, or service layer solely for this read.

The query must join `Product` to `Plan` through:

```text
Plan.product_id == Product.id
```

and require:

```text
Product.tenant_id == tenant_id
Product.status == "active"

Plan.tenant_id == tenant_id
Plan.region == region
Plan.status == "active"
Plan.scope_type == "product"
Plan.valid_from <= now
Plan.valid_to IS NULL OR Plan.valid_to > now
```

Return all current direct-product offers satisfying those conditions.

Use deterministic ordering. Prefer stable product-code then plan-code ordering.

Do not load bundles, `BundleProduct`, all-access plans, plan price components, plan limits, orders, payments, subscriptions, entitlements, or provider accounts.

Do not invent a default plan if multiple valid plans exist for one product.

### 2. Add named Pydantic response contracts

Keep the response models next to the HTTP catalog slice unless an existing billing contract module clearly owns them.

Define equivalent models to:

```python
class CatalogPlanResponse(BaseModel):
    plan_id: uuid.UUID
    code: str
    name: str
    price_amount_minor: int
    currency: str
    billing_period: BillingPeriod
    renewal_mode: SubscriptionRenewalMode
    trial_days: int


class CatalogProductResponse(BaseModel):
    product_id: uuid.UUID
    code: str
    name: str
    description: str | None
    plan: CatalogPlanResponse


class CatalogProductsResponse(BaseModel):
    products: list[CatalogProductResponse]
```

Reuse the existing provider-neutral:

```python
BillingPeriod
SubscriptionRenewalMode
```

from `apps/api/app/domains/billing/enums.py`.

Do not introduce another enum with the same values.

Do not expose:

```text
platform_product_id
Product.status
Plan.status
valid_from
valid_to
metadata
provider data
created_at
updated_at
plan limits
payment information
```

### 3. Add the catalog router

Add a billing-owned HTTP module such as:

```text
apps/api/app/domains/billing/catalog.py
```

with:

```text
GET /api/catalog/products
```

The route must:

- require no user session;
- use `DEFAULT_TENANT_ID`;
- use `DEFAULT_REGION`;
- use `utc_now()`;
- delegate persistence to the query function;
- return `CatalogProductsResponse`;
- expose the named schema in generated OpenAPI.

Do not place SQL directly in the router.

Do not add catalog behavior to the identity router.

### 4. Register the router

Register the new router in:

```text
apps/api/app/main.py
```

without changing unrelated router order or application startup behavior.

### 5. Add focused backend tests

Add focused coverage in:

```text
apps/api/tests/test_api.py
```

Reuse the existing test database setup and catalog fixtures.

Do not create a second catalog seeding system for these tests.

Cover:

1. `GET /api/catalog/products` works without `Authorization`;
2. `document-summary` is returned from persisted `Product` + `Plan` data;
3. `prompt-optimizer` is returned;
4. `price_amount_minor == 99000`;
5. currency is `RUB`;
6. plan code/name/billing period/renewal mode/trial days come from `Plan`;
7. inactive product is excluded;
8. inactive plan is excluded;
9. future plan is excluded;
10. expired plan is excluded;
11. bundle plans are excluded;
12. all-access plans are excluded;
13. product with no current sellable direct-product plan is excluded;
14. no sellable products returns:

```json
{"products": []}
```

15. generated FastAPI/OpenAPI metadata exposes a named catalog response schema.

When proving DB authority, change a persisted test product/plan field and assert that the response reflects the changed DB value. Do not merely assert the migration seed constants.

## Scope constraints

Do not:

- modify migrations;
- modify ORM schema;
- add Product fields;
- add Plan fields;
- use `Plan.metadata` for frontend marketing copy;
- expose `plan_limits`;
- modify subscription APIs;
- modify checkout;
- modify frontend code;
- modify CloudPayments;
- add another contour;
- add a configuration framework;
- refactor existing billing lifecycle code.

If existing code materially conflicts with the locked contract above, stop and report the exact conflict instead of redesigning the endpoint.

## Automated checks

Do NOT run:

```text
pytest
npm test
npm run test:api
npm run check
npm run check:fast
npm run architecture:check
npm run generate
npm run generate:check
linters
formatters
type checkers
migrations
builds
```

Do not automatically reformat unrelated files.

Do not hand-edit generated files.

## After implementation

Report:

1. files changed;
2. exact endpoint path;
3. final response-model structure;
4. exact DB predicates used to determine a sellable product;
5. confirmation that no migration was added;
6. confirmation that bundles/all-access were not exposed;
7. any discrepancy from this plan;
8. exact commands I should run manually.

Tell me to run:

```bash
pytest apps/api/tests/test_api.py -k "catalog"
npm run architecture:check
npm run generate
npm run generate:check
npm run check:fast
```

`npm run generate` is expected to update generated artifacts if the OpenAPI surface is tracked. Do not edit those artifacts manually; I will review and include legitimate generated changes in this step's commit.

## Commit

Final commit name:

```text
feat(catalog): expose sellable product offers
```

Status after successful manual verification:

```text
done
```

---

# Step 2 — Replace the hardcoded catalog cards with validated backend data

**Status:** `done`  
**Commit:** `feat(web): load product catalog from backend`  
**Depends on:** Step 1 completed, manually verified, generated artifacts updated if required, and committed.

## Prompt

Implement Step 2 of ANY-370: make the RU catalog pages render backend catalog data instead of the hardcoded frontend product list.

Step 1 is complete and the backend contract is fixed:

```text
GET /api/catalog/products
```

Do not research the repository architecture again.

Do not inspect Linear or unrelated tickets.

Work only in the catalog frontend slice, the RU routes that render it, the minimum authenticated subscription API consumer required by these cards, and their focused tests.

## Goal

The following surfaces must obtain product availability and commercial plan data from the backend:

```text
/ru
/ru/products
```

The frontend may still keep localized presentation metadata, but it must no longer determine which products/plans exist or what they cost.

For a logged-in user with current product entitlement, the catalog card must show current access/subscription information instead of a purchase CTA.

## Relevant existing code

Work primarily in:

```text
apps/web/src/features/catalog/catalog.ts
apps/web/src/features/catalog/ProductCards.tsx
apps/web/src/features/catalog/index.ts
apps/web/src/app/ru/page.tsx
apps/web/src/app/ru/products/page.tsx
apps/web/src/shared/api/auth.ts
apps/web/tests/
```

The backend subscription contract already exists at:

```text
GET /api/account/subscriptions
```

Do not modify that backend endpoint in this step.

## Implementation

### 1. Create the frontend catalog API contract

Create:

```text
apps/web/src/features/catalog/api.ts
```

Define shared feature-level types matching Step 1:

```text
CatalogPlan
CatalogProduct
CatalogProductsResponse
```

Implement:

```text
decodeCatalogProductsResponse(payload: unknown)
```

The decoder must explicitly validate every consumed field.

At minimum validate:

```text
products is an array

product_id: string
code: string
name: string
description: string | null

plan.plan_id: string
plan.code: string
plan.name: string
plan.price_amount_minor: finite non-negative integer
plan.currency: string
plan.billing_period: string
plan.renewal_mode: "manual" | "automatic"
plan.trial_days: finite non-negative integer
```

Do not use:

```typescript
response.json() as CatalogProductsResponse
```

Do not add Zod or another schema library.

### 2. Add a narrow public catalog fetch function

In the same feature API module, add a function such as:

```text
getCatalogProducts()
```

Use:

```text
resolveApiBase()
requestTimeoutMs
```

from the existing shared API implementation.

Use the existing timeout convention with `AbortController`.

The catalog request requires **no Authorization header**.

Treat `response.json()` as `unknown` and pass it through `decodeCatalogProductsResponse`.

Do not generalize this into a new application-wide HTTP client.

Do not refactor `postJson`, `getJson`, `ApiError`, auth flows, or unrelated API consumers.

A failed HTTP request, timeout, or decoder failure must surface to the catalog UI as a catalog load failure.

### 3. Add the authenticated subscriptions decoder

Create:

```text
apps/web/src/shared/api/subscriptions.ts
```

Model the already-existing response from:

```text
GET /api/account/subscriptions
```

Include exactly the fields needed by catalog/account presentation:

```text
subscription_id

plan:
  plan_id
  code
  name
  billing_period

scope:
  scope_type
  product_id
  bundle_id

status
renewal_mode

current_period:
  starts_at
  ends_at

cancellation:
  cancel_requested_at
  canceled_at

entitlement_validity:
  status
  valid_from
  valid_until
```

Validate the finite vocabularies that already exist in the backend.

Do not invent additional subscription states.

Implement an explicit decoder and an authenticated fetch wrapper using the existing `getJson(..., decoder)` behavior.

### 4. Add one reusable current-entitlement predicate

Add one small shared frontend predicate used later by both catalog and account presentation.

It must return current access only when:

```text
scope_type == "product"
product_id matches the catalog product
entitlement_validity.status == "active"
valid_from <= now
valid_until > now
```

Invalid/missing dates must not grant access.

Do not infer access from:

```text
subscription.status == "active"
```

alone.

Do not duplicate this predicate separately in `ProductCards` and `AccountClient`.

### 5. Separate product authority from RU presentation metadata

Refactor:

```text
apps/web/src/features/catalog/catalog.ts
```

Remove the existing hardcoded `products` array as the authoritative catalog.

Replace it with a presentation map keyed by backend product code.

For the two existing products, presentation metadata may contain:

```text
Icon
type label
RU tagline
RU marketing description
RU valuePoints
freeLimit copy
```

Keep the current Russian customer-facing copy for the known products.

Do not store there:

```text
plan code
plan name as commercial authority
price
billing period
renewal mode
trial days
whether the product exists
```

The presentation map must not be iterated to determine the catalog.

A backend product for which no presentation mapping exists must still render.

For an unknown backend product:

- use a generic existing icon;
- use backend `name`;
- use backend `description` when available;
- omit optional marketing-only fields that do not exist;
- do not invent a fake free limit or fake feature list.

Do not reject an unknown product code just because it is absent from the presentation map.

### 6. Change `ProductCards` into a pure decoded-data renderer

`ProductCards` must no longer import or iterate the old static `products` array.

Make it receive decoded backend products through props.

Preserve support for `selectedCode` because checkout uses that visual state later.

It may receive subscription/access presentation state through props, but it must not fetch APIs itself.

Commercial card fields must come from `CatalogProduct`:

```text
product code
product name
plan name
price_amount_minor
currency
billing_period
trial_days
```

Use presentation metadata only for the explicitly allowed localized visual/marketing fields.

### 7. Add a client-side catalog loader for `/ru` and `/ru/products`

Create a client component such as:

```text
apps/web/src/features/catalog/CatalogProductsClient.tsx
```

Responsibilities:

1. fetch `/api/catalog/products`;
2. handle catalog loading/error/empty/success states;
3. check whether an existing session token is present;
4. if no session token exists, render normal guest purchase actions;
5. if a session token exists, fetch `/api/account/subscriptions`;
6. map current direct-product entitlement state to catalog products;
7. pass decoded data to `ProductCards`.

Do not move checkout behavior into this component.

### 8. Define catalog UI states explicitly

Catalog loading:

```text
show a RU loading state
do not render stale hardcoded products
```

Catalog request/decoder error:

```text
show a RU error state
do not fall back to hardcoded products
```

Empty:

```text
show a RU empty-catalog state
do not render stale products
```

Guest:

```text
show normal purchase CTA
```

Stored authenticated session + subscriptions loading:

```text
show products
show subscription-status loading indication
do not expose an active purchase CTA until ownership state is known
```

Subscriptions successfully loaded + no current entitlement:

```text
show normal purchase CTA
```

Current direct-product entitlement:

```text
show access/subscription state
show plan name
show validity/current-period information where available
show localized renewal-mode information
do not show the purchase CTA
provide link to /ru/account
```

Subscription API/decoder failure:

```text
keep catalog visible
show a non-destructive RU subscription-status error
do not expose an active purchase CTA while authenticated ownership state is unknown
```

Do not attempt to handle pending payment orders in these catalog cards. That belongs to ANY-369.

### 9. Format backend money, do not restore `priceRub`

Replace the old whole-ruble commercial contract.

The API source is:

```text
price_amount_minor
currency
```

Create/update the catalog display helper accordingly.

This is presentation formatting only. Do not use floating-point money for business calculations.

The current ANY-370 surface is RU/RUB. Do not pretend to implement a complete arbitrary ISO-4217 minor-unit engine.

Do not hardcode the product price itself.

### 10. Remove duplicated commercial copy from the RU catalog section

Update:

```text
apps/web/src/app/ru/page.tsx
```

Remove the sentence that independently claims:

```text
990 ₽
7 days
```

Use neutral RU copy directing the customer to the actual product cards for current price/trial terms.

Do not redesign the page.

Do not introduce a new commercial claim.

If `platformFacts` contains catalog-derived product-count/trial numbers which would remain another stale commercial source, remove the numeric dependency or make the copy neutral. Preserve the Bundle 3 layout; do not build another API request only for decorative statistics.

### 11. Add focused frontend tests

Create focused catalog component/API tests using the existing Vitest + MSW setup.

Cover:

1. products are rendered from `/api/catalog/products`;
2. backend `name` change changes rendered name;
3. backend `price_amount_minor` change changes rendered price;
4. hardcoded product array is not required;
5. loading state;
6. HTTP error state;
7. empty state;
8. invalid catalog JSON is rejected;
9. unknown backend product code still renders with generic presentation;
10. guest receives the purchase CTA;
11. authenticated user with current entitlement does not receive the purchase CTA;
12. active product shows subscription/validity data;
13. expired entitlement does not count as current access;
14. revoked entitlement does not count as current access;
15. future entitlement does not count as current access before `valid_from`;
16. subscriptions loading does not briefly expose the purchase CTA;
17. subscriptions request failure does not expose the purchase CTA;
18. invalid subscriptions payload is rejected.

Add a focused unit test for money formatting because money display logic is changing.

## Scope constraints

Do not:

- modify backend code;
- modify checkout yet;
- modify AccountClient yet;
- implement pending-order behavior;
- add a frontend API-generation tool;
- add a validation library;
- turn marketing metadata into backend persistence;
- use `plan_limits` as the free-tier `3 / 50` values;
- redesign Bundle 3;
- add new contour support;
- refactor all HTTP helpers;
- refactor all localStorage/session event constants;
- change auth semantics.

## Automated checks

Do NOT run:

```text
Vitest
Playwright
ESLint
Prettier
typecheck
Next build
npm run check
npm run check:fast
formatters
generators
```

Do not automatically modify unrelated files.

## After implementation

Report:

1. files changed;
2. fields now sourced from the backend;
3. fields intentionally retained as presentation-only frontend metadata;
4. exact handling of unknown backend product codes;
5. exact loading/error/empty behavior;
6. exact authenticated ownership behavior;
7. confirmation that `plan_limits` were not confused with free-tier copy;
8. exact manual commands I should run.

Tell me to run:

```bash
npm --workspace @anytoolai/web run test:components -- tests/components/CatalogProductsClient.test.tsx
npm run typecheck:web
npm run lint:web
```

Then manually inspect:

```text
/ru
/ru/products
```

Verify:

```text
guest -> purchase CTA is available
active entitlement -> purchase CTA is absent
catalog API unavailable -> error state, no static fallback
unknown API product -> still renders
```

## Commit

Final commit name:

```text
feat(web): load product catalog from backend
```

Status after successful manual verification:

```text
done
```

---

# Step 3 — Make checkout use the backend catalog offer

**Status:** `todo`  
**Commit:** `fix(checkout): use backend catalog offer`  
**Depends on:** Step 2 completed, manually verified, and committed.

## Prompt

Implement Step 3 of ANY-370: remove CheckoutClient's dependency on the old hardcoded product/plan catalog.

The backend catalog API and frontend validated catalog client from Steps 1–2 already exist.

Do not redo repository or ticket research.

Do not change payment-provider behavior.

Work primarily in CheckoutClient and its focused tests.

## Goal

`CheckoutClient` must obtain the selected product and plan from:

```text
GET /api/catalog/products
```

instead of:

```text
products[]
findProduct()
hardcoded plan.code
hardcoded priceRub
```

The existing route remains:

```text
/ru/auth-checkout?product=<product-code>
```

No new product-selection URL contract is introduced in ANY-370.

If current entitlement already grants access to the selected product, checkout must not offer or initiate another payment.

## Relevant existing code

Work primarily in:

```text
apps/web/src/features/checkout/CheckoutClient.tsx
apps/web/src/features/catalog/api.ts
apps/web/src/features/catalog/ProductCards.tsx
apps/web/src/features/catalog/catalog.ts
apps/web/tests/components/CheckoutClient.test.tsx
```

Do not modify backend checkout.

The existing backend endpoint remains:

```text
POST /api/auth/checkout-intent
```

with the current request contract:

```text
product
plan_code
auto_renew
recurring_consent_acceptance_id when applicable
```

## Implementation

### 1. Load catalog before resolving the selected product

`CheckoutClient` must load the validated catalog using the Step 2 catalog API client.

Do not validate:

```text
?product=
```

against a frontend literal union or hardcoded presentation map.

The selected catalog offer is the backend item whose:

```text
product.code == query product
```

For the current RU surface this is one direct-product plan per product.

If no backend catalog item matches:

```text
show existing invalid-product UX
do not allow checkout
```

If more than one current catalog item unexpectedly has the same product code:

```text
treat the catalog selection as ambiguous
do not silently select first/latest
block checkout
```

Do not implement multi-plan selection UX in this ticket.

### 2. Handle catalog loading before auth/checkout decisions

While catalog is loading:

- do not classify the query product as invalid;
- do not open the product-driven authentication modal yet;
- do not expose payment controls;
- show a clear RU loading state.

If catalog loading fails or decoder validation fails:

- show a RU checkout/catalog-unavailable error;
- do not fall back to hardcoded product data;
- do not allow checkout.

### 3. Use backend offer data throughout checkout presentation

Replace commercial uses of the former static `Product` definition.

Use backend:

```text
product.code
product.name
plan.code
plan.name
plan.price_amount_minor
plan.currency
plan.billing_period
plan.trial_days
```

Use presentation metadata only for:

```text
Icon
type
tagline
localized marketing description
valuePoints
freeLimit
```

`SelectedProductCard` and `SubscriptionState` must not read commercial plan data from the old static catalog.

### 4. Use backend `plan.code` in checkout intent

The request to:

```text
POST /api/auth/checkout-intent
```

must use exactly:

```text
product = selectedCatalogProduct.code
plan_code = selectedCatalogProduct.plan.code
```

Do not keep a product-to-plan mapping anywhere else on the frontend.

Do not modify the backend checkout request model.

### 5. Preserve existing auth/legal/provider behavior

Do not redesign:

- login;
- registration;
- session loading;
- legal-document acceptance;
- recurring-consent flow;
- provider adapter selection;
- CloudPayments widget launch;
- payment-result session storage.

Only make mechanical changes required to replace the selected hardcoded catalog product with the decoded backend catalog offer.

### 6. Block repeat purchase UI for current active access

The existing:

```text
GET /api/auth/session?product=<code>
```

already computes product state from backend entitlement data.

When:

```text
productState.status == "active"
```

the checkout page must:

- display active access/subscription information;
- show backend plan name;
- show expiry when available;
- not show the main payment button;
- not show a purchase action on the selected product card;
- not show purchase-only controls such as auto-renew selection for starting a new purchase;
- provide navigation to `/ru/account`.

Add a defensive check at the beginning of the payment-start handler.

If:

```text
productState.status == "active"
```

the handler must return without calling:

```text
POST /api/auth/checkout-intent
```

This is a UI safety guard.

Do not change backend duplicate-order behavior.

### 7. Preserve pending behavior for ANY-369

Do **not** reinterpret:

```text
productState.status == "pending"
```

as part of ANY-370.

Do not implement continuation/reuse/blocking of existing pending orders.

Do not change the existing backend order invariant.

ANY-369 owns that behavior.

### 8. Update CheckoutClient tests

Every selected-product checkout test must provide a mocked valid response for:

```text
GET /api/catalog/products
```

Update expectations so tests no longer rely on static `catalog.ts` plan data.

Cover:

1. selected product comes from backend catalog;
2. backend plan code is sent to `/api/auth/checkout-intent`;
3. backend product name is rendered;
4. backend price is rendered;
5. backend trial days are rendered;
6. catalog loading blocks checkout;
7. catalog HTTP error blocks checkout;
8. invalid catalog payload blocks checkout;
9. unknown query product is rejected only after catalog resolution;
10. active product state does not render the payment button;
11. active product state does not render the selected-card purchase CTA;
12. active access shows expiry/plan data;
13. active access provides `/ru/account` navigation;
14. defensive payment handler does not call checkout-intent for active access;
15. guest auth behavior remains unchanged;
16. legal acceptance behavior remains unchanged;
17. provider-adapter behavior remains unchanged;
18. pending characterization remains unchanged unless an existing test must be mechanically adapted to the new catalog mock.

## Scope constraints

Do not:

- modify backend code;
- change `/api/auth/checkout-intent`;
- add order deduplication;
- add pending-order continuation;
- change CloudPayments;
- change legal rules;
- change recurring-consent rules;
- add subscription management;
- change payment result behavior;
- introduce `?plan=`;
- introduce multi-plan UX;
- refactor CheckoutClient beyond what catalog replacement requires.

## Automated checks

Do NOT run:

```text
Vitest
Playwright
ESLint
Prettier
typecheck
Next build
npm run check
npm run check:fast
```

Do not automatically reformat unrelated checkout code.

## After implementation

Report:

1. files changed;
2. all former hardcoded catalog dependencies removed from CheckoutClient;
3. exact selected-product resolution behavior;
4. exact checkout-intent product/plan source;
5. exact active-access guard behavior;
6. confirmation that pending-order behavior was not changed;
7. exact commands I should run manually.

Tell me to run:

```bash
npm --workspace @anytoolai/web run test:components -- tests/components/CheckoutClient.test.tsx
npm run typecheck:web
npm run lint:web
```

Then manually inspect:

```text
/ru/auth-checkout?product=document-summary
/ru/auth-checkout?product=prompt-optimizer
/ru/auth-checkout?product=does-not-exist
```

For an account with current entitlement verify:

```text
plan/subscription data is visible
payment button is absent
purchase CTA is absent for the selected product
/account navigation is available
no checkout-intent request occurs
```

## Commit

Final commit name:

```text
fix(checkout): use backend catalog offer
```

Status after successful manual verification:

```text
done
```

---

# Step 4 — Remove remaining hardcoded catalog authority from account and production UI

**Status:** `todo`  
**Commit:** `refactor(account): remove hardcoded catalog authority`  
**Depends on:** Step 3 completed, manually verified, and committed.

## Prompt

Implement the final Step 4 of ANY-370: migrate AccountClient from the hardcoded catalog list and remove obsolete frontend catalog authority without changing unrelated account/payment behavior.

The backend catalog API, frontend catalog decoder, subscription decoder, current-entitlement helper, and checkout integration from Steps 1–3 already exist.

Do not perform additional architecture research.

## Goal

After this step, production frontend code must not contain a hardcoded product list or product-to-plan commercial mapping that determines:

```text
available products
plan code
plan price
trial days
checkout plan
```

`AccountClient` must iterate backend catalog products.

At the same time, preserve its existing pending/payment-state behavior.

## Relevant existing code

Work primarily in:

```text
apps/web/src/features/account/AccountClient.tsx
apps/web/src/features/catalog/api.ts
apps/web/src/features/catalog/catalog.ts
apps/web/src/shared/api/subscriptions.ts
apps/web/tests/components/AccountClient.test.tsx
```

Inspect other production `apps/web/src` files only when removing a direct import of the old catalog authority.

Do not perform a general frontend cleanup.

## Implementation

### 1. Load backend catalog in AccountClient

Replace iteration over:

```text
products
```

from `catalog.ts`.

Load:

```text
GET /api/catalog/products
```

through the Step 2 validated catalog API client.

The list of account product cards must now be driven by the backend catalog response.

Do not derive the product list from the presentation map.

### 2. Preserve the existing authenticated account/session request

Keep the existing initial session request used to establish the logged-in account and email.

Do not redesign authentication.

### 3. Preserve existing per-product `product_state` behavior

The current account page requests:

```text
GET /api/auth/session?product=<code>
```

for each known product and uses it to represent:

```text
inactive
pending
active
failed
```

Do not delete this behavior simply because `/api/account/subscriptions` now exists.

Instead, drive those product-state requests from backend catalog product codes.

This preserves existing pending-payment presentation and avoids taking ANY-369 scope.

Do not optimize these requests into a new backend endpoint in ANY-370.

### 4. Add account subscription details without replacing product state

Also load the existing:

```text
GET /api/account/subscriptions
```

once for the authenticated account.

Use it to enrich product cards with subscription-specific data.

Match direct product subscriptions by:

```text
scope.scope_type == "product"
scope.product_id == catalogProduct.product_id
```

Use the shared current-entitlement predicate from Step 2.

Do not implement another copy.

When current entitlement exists, show available subscription details such as:

```text
plan name
current period end
entitlement validity end
renewal mode
```

Current access truth comes from entitlement validity.

Use `product_state` to preserve the existing pending/failed presentation.

### 5. Preserve ANY-369 navigation scope

The current active-account button labeled:

```text
manage-subscription CTA
```

has separate navigation behavior covered by ANY-369.

Do not implement a new management page.

Do not introduce a new subscription-management route.

Do not change backend duplicate-order logic.

If the existing manage-subscription CTA destination remains unchanged, keep it unchanged in this step. Step 3 already guarantees that entering checkout with current active access cannot start another payment.

### 6. Remove obsolete commercial hardcoding

Once no production consumer requires it, remove obsolete definitions from the catalog module:

```text
ProductCode literal union used as catalog authority
Product commercial type containing hardcoded plan
products array
findProduct
plan.code mapping
plan.name mapping used as authority
priceRub
hardcoded trialDays used as authority
```

Retain the presentation map from Step 2.

Product-specific code strings are allowed to remain **only** as keys for presentation metadata.

They must not determine whether a product exists.

### 7. Remove remaining direct commercial catalog duplication

Inspect the production `apps/web/src` files directly affected by old catalog imports.

Remove stale direct assumptions such as:

```text
hardcoded 990 catalog price
hardcoded product-to-plan mapping
hardcoded trial used instead of API data
iteration of a fixed product list
```

Do not mechanically delete unrelated mentions of:

```text
document-summary
prompt-optimizer
```

Those codes can legitimately remain in:

- presentation metadata;
- marketing copy;
- provider/test context;
- query examples;
- unrelated feature-specific logic.

The requirement is removal of **catalog authority**, not removal of every product-code string.

### 8. Preserve localized marketing presentation

Do not delete the current RU icon/tagline/value-points/free-limit presentation simply because the product catalog became backend-driven.

Do not move these fields into Plan metadata.

For known products, retain current localized presentation.

For unknown backend products, keep the fallback behavior from Step 2.

### 9. Update AccountClient tests

Mock:

```text
GET /api/catalog/products
GET /api/auth/session
GET /api/auth/session?product=...
GET /api/account/subscriptions
```

as required by each scenario.

Cover:

1. account product list is driven by catalog API;
2. backend-added product appears without editing a hardcoded product list;
3. backend price is rendered;
4. active entitlement is shown as current access;
5. subscription plan/current-period/renewal data is shown;
6. expired entitlement does not grant current access;
7. revoked entitlement does not grant current access;
8. pending product state remains visible;
9. failed product-state behavior remains visible;
10. one failed per-product state request still behaves according to the existing partial-load semantics;
11. catalog decoder failure is handled;
12. subscription decoder failure is handled safely;
13. presentation fallback works for an unknown backend product;
14. no test relies on the removed static `products` array.

Do not rewrite unrelated component tests.

## Scope constraints

Do not:

- modify backend APIs;
- remove pending product-state behavior;
- implement ANY-369;
- change the active management destination as a separate feature;
- add a management page;
- add migrations;
- add Product/Plan fields;
- move marketing content to backend metadata;
- refactor account authentication;
- refactor global session-storage handling;
- clean up unrelated frontend debt.

## Automated checks

Do NOT run:

```text
Vitest
Playwright
ESLint
Prettier
typecheck
Next build
npm run check
npm run check:fast
rg
grep
formatters
generators
```

Do not automatically reformat unrelated files.

## After implementation

Report:

1. files changed;
2. exact remaining role of `catalog.ts`;
3. hardcoded commercial authority removed;
4. presentation-only metadata intentionally retained;
5. confirmation that pending product-state behavior remains;
6. confirmation that ANY-369 behavior was not implemented;
7. exact manual commands/searches I should run.

Tell me to run:

```bash
npm --workspace @anytoolai/web run test:components -- tests/components/AccountClient.test.tsx
npm --workspace @anytoolai/web run test:components
npm run typecheck:web
npm run lint:web
npm run build:web
npm run check:fast
```

Then tell me to inspect production frontend references manually with:

```bash
rg 'export const products|findProduct|priceRub' apps/web/src
rg 'document-summary-pro|prompt-optimizer-pro|990' apps/web/src
```

The second search is **not required to be empty**.

Review every remaining match and verify that no remaining production frontend code uses it to determine:

```text
product availability
plan selection
catalog price
trial duration
checkout plan
```

Product codes may remain as presentation metadata keys or legitimate unrelated identifiers.

Finally manually verify:

```text
/ru
/ru/products
/ru/account
/ru/auth-checkout?product=document-summary
```

with:

```text
guest account
authenticated account without subscription
authenticated account with active entitlement
authenticated account with pending payment if available
```

## Commit

Final commit name:

```text
refactor(account): remove hardcoded catalog authority
```

Status after successful manual verification:

```text
done
```

---

# Completion Criteria

ANY-370 is complete only when the data flow is:

```text
Product + Plan in PostgreSQL
        ↓
GET /api/catalog/products
        ↓
validated CatalogProductsResponse
        ↓
/ru
/ru/products
/ru/auth-checkout
/ru/account
```

and authenticated subscription/access presentation is:

```text
GET /api/account/subscriptions
        ↓
scope.product_id
        +
current entitlement validity
        ↓
catalog/account subscription presentation
```

while existing checkout/account product-state behavior remains:

```text
GET /api/auth/session?product=<backend catalog code>
        ↓
inactive / pending / active / failed
```

The finished implementation must satisfy all of these conditions:

```text
Frontend hardcoded products[] is no longer the catalog source of truth.

Frontend hardcoded plan codes are no longer used for checkout selection.

Frontend hardcoded prices are no longer used as catalog commercial truth.

Frontend hardcoded trialDays are no longer used as catalog commercial truth.

Current RU catalog still preserves its localized presentation.

Unknown backend product codes are not silently discarded.

Catalog loading/error/empty states exist.

Current active entitlement suppresses another purchase CTA.

Checkout itself defensively refuses to start a new purchase while product_state is active.

Pending payment behavior is preserved for ANY-369.

No new database migration exists.

No new contour exists.

No CloudPayments changes exist.

No Account API from ANY-302 was implemented.

No duplicate-order behavior from ANY-369 was implemented.
```
