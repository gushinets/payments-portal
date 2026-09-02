# ANY-327 — Make exact Plan ID the checkout purchase identity

## Plan Overview

| Field | Value |
| --- | --- |
| Project | `Payment portal` |
| Ticket | `ANY-327` |
| Current ticket type | `type:research`; the investigation has produced an implementation decision, so runtime work must be explicitly owned before Step 2 |
| Triggered by | `ANY-323` checkout refactor exposing the legacy `all-access` / `all_access` ambiguity |
| Related contract work | `ANY-324` |
| Current base | `ANY-370` / PR #74 is already merged into `main` |
| Important ANY-370 fact | the frontend catalog is backend-backed and every `CatalogProduct.plan` contains the exact `plan_id` |
| Important ANY-370 fact | selected-product checkout now uses scope-aware ownership checks and fails closed while ownership is loading or unavailable |
| Scope-alignment gate | before Step 2, either change `ANY-327` so it explicitly owns this runtime refactor, or execute Steps 2-3 under one dedicated implementation follow-up |
| Overall status | `todo` |
| Recommended base | new `ANY-327` branch from current up-to-date `main` |
| Execution order | Step 1 -> manual verification -> commit -> Linear scope-alignment gate -> Step 2 -> manual verification -> commit -> Step 3 -> manual verification -> commit |
| Steps / commits | 3 |
| Database migration | not required |
| Frontend change | required |
| Generated OpenAPI change | required after Step 2 |
| Follow-up constraint | `ANY-323` must be rebased after this work and preserve the new exact-Plan contract |

## How to Use This File

1. Create/rebase the implementation branch from the current `main` containing merged `ANY-370`.
2. Put this file at:

   ```text
   docs/exec-plans/active/ANY-327-implementation-plan.md
   ```

3. For each implementation step, give the implementation AI only that step.
4. Do not ask the implementation AI to re-research Linear, GitHub history, architecture, or `ANY-370`; the relevant decisions are locked below.
5. The implementation AI may inspect the files explicitly listed in the step and direct dependencies required to edit them.
6. The implementation AI must not run tests, linters, formatters, generators, or repository-wide checks. Run the listed verification manually after each step.
7. Commit each step separately using the commit message specified by the step.
8. Do not begin Step 2 until Linear ownership of the runtime work is explicit.
9. If current `main` materially differs from a stated implementation assumption, report the exact conflict rather than adding compatibility behavior.

---

# Context and Locked Decisions

`ANY-327` was opened because checkout code mixed these values:

```text
all-access
all_access
```

That mismatch is only a symptom.

The real architectural problem is that the existing checkout request uses:

```text
product + plan_code
```

and the `product` field is overloaded to mean different things depending on the selected plan. Legacy code may interpret it as a `Product.code`, a `Bundle.code`, or a synthetic `all-access` sentinel. For an all-access scoped plan, old code may even accept `Plan.code` as another alias.

The corrected design must stop using those strings to resolve a purchase.

## 1. Exact persisted `Plan.id` is the checkout purchase identity

The catalog already exposes the commercial Plan selected for a product:

```text
CatalogProduct
  product_id
  code
  name
  ...
  plan
    plan_id
    code
    name
    price_amount_minor
    currency
    billing_period
    renewal_mode
    trial_days
```

The current direct-product flow is therefore:

```text
DB Product + current sellable Plan
-> GET /api/catalog/products
-> frontend selects CatalogProduct
-> frontend submits selectedProduct.plan.plan_id
-> backend resolves that exact persisted Plan
```

The checkout request authority is:

```text
plan_id: UUID
```

The client must not repeat commercial identity using:

```text
Product.code
Bundle.code
Plan.code
scope_type
```

`Plan.code` remains readable domain data and may be persisted/returned as a snapshot, but it is not the exact checkout selector.

This is important because Plans are versioned. A new persisted Plan version may retain the same human-readable code but have a different `Plan.id`.

## 2. The frontend is product-oriented today, but the checkout authority is still Plan ID

`ANY-370` implements the current direct-product catalog and route:

```text
/ru/auth-checkout?product=<Product.code>
```

That query parameter may remain because it selects which product card/page the user is looking at.

It is navigation only.

The payment request must not send the URL product code as purchase authority. It must send:

```text
selectedProduct.plan.plan_id
```

Do not replace `plan_id` with `product_id`: `Product` identifies what capability is being sold, while `Plan` identifies the exact commercial offer/version presented to the customer.

## 3. Remove the synthetic `all-access` string from the checkout runtime contract

`all-access` is not a persisted Product identity and is not a persisted Bundle identity.

There is no reason for the current frontend product flow to send it, and there is no reason for the backend checkout resolver to expect it.

The target checkout runtime must not use `all-access` as:

```text
request product
sellable code
plan alias
scope alias
entrypoint synthesized from scope
invoice prefix
order/provider metadata identity
checkout response identity
```

Do not create:

```text
Product(code="all-access")
Bundle(code="all-access")
```

Do not preserve a compatibility branch equivalent to:

```python
entrypoint_code in {"all-access", plan.code}
```

After this migration, the literal legacy sentinel `all-access` should only appear where necessary to document/test removal of the old behavior. It is not part of the target checkout API.

This ticket does not define a future `all-access` route slug, public entrypoint name, or catalog card. If a future feature needs such UI vocabulary, it must define that contract independently and must not reuse a synthetic purchase identifier.

## 4. `all_access` remains a canonical access-scope value, not purchase identity

Do not confuse removal of the legacy string `all-access` with removal of the domain scope value `all_access`.

The canonical access scope remains:

```python
class SubscriptionScopeType(StrEnum):
    PRODUCT = "product"
    BUNDLE = "bundle"
    ALL_ACCESS = "all_access"
```

`all_access` answers:

```text
What access does this persisted Plan/Subscription/Entitlement grant?
```

It does not answer:

```text
What string should the client send to buy something?
```

The checkout client must never submit `all_access` or any other `scope_type` as purchase authority.

The backend derives scope from the persisted Plan:

```text
plan_id
-> Plan
-> Plan.scope_type
-> SubscriptionScopeType(plan.scope_type)
```

`all_access` may continue to appear in server-derived read models such as account subscription/access data and may be consumed by frontend ownership checks. That is access semantics, not checkout purchase selection.

## 5. Product/Bundle references are derived from the resolved Plan

For a current persisted Plan, validate the existing domain shape fail closed:

```text
scope_type == product
  -> product_id is required
  -> bundle_id is null
  -> referenced Product exists and is active

scope_type == bundle
  -> product_id is null
  -> bundle_id is required
  -> referenced Bundle exists and is active

scope_type == all_access
  -> product_id is null
  -> bundle_id is null
```

The client does not send any of these relationships.

The backend gets them from the Plan selected by exact ID.

For `all_access` scope specifically, the backend must not synthesize any Product/Bundle code or the legacy `all-access` string.

## 6. Entrypoint context is provenance, not purchase identity

`EntrypointSession.entrypoint_type` and `EntrypointSession.entrypoint_value` describe where checkout started.

They do not choose the Plan.

For the current direct-product UI the checkout request may explicitly carry:

```text
entrypoint_type = "product"
entrypoint_value = selectedProduct.code
```

because that is the actual UI provenance.

The resolver must not compare those values with Plan/Product/Bundle scope in order to resolve the purchase.

Target request shape:

```python
class CheckoutIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: uuid.UUID
    auto_renew: bool = False
    recurring_consent_acceptance_id: uuid.UUID | None = None
    entrypoint_type: str
    entrypoint_value: str
    frontend_id: str | None = None
    source_url: str | None = None
```

Remove legacy purchase fields:

```text
product
plan_code
```

Do not add aliases for them.

## 7. Preserve the final ANY-370 ownership semantics

The merged frontend now resolves whether the selected product is already owned using both direct session product state and `/api/account/subscriptions`.

That access check intentionally understands these entitlement scopes:

```text
product
bundle
all_access
```

For the currently selected Product, ownership can therefore come from:

```text
direct product entitlement
bundle containing that product
all_access entitlement
```

This is correct and must remain.

It does not mean checkout accepts `bundle`, `all_access`, or `all-access` as purchase identifiers.

Preserve these merged invariants:

```text
ownership checking/loading -> checkout unavailable
ownership fetch error -> checkout unavailable
current direct entitlement -> purchase unavailable
current bundle entitlement containing product -> purchase unavailable
current all_access entitlement -> purchase unavailable
otherwise -> selected product can be purchased
```

Do not regress to authenticated users being treated as guest ownership while subscription data is unresolved.

## 8. Recurring consent binds to exact Plan ID

The fail-closed recurring-consent boundary introduced by `ANY-379` must remain enforced in both:

```text
checkout intent validation
enable_automatic_renewal() lifecycle revalidation
```

Keep all existing matching dimensions:

```text
user
tenant/region
current required legal document/version/hash
acceptance kind/time
entrypoint_type
entrypoint_value
```

Change only the commercial identity from:

```text
metadata.plan_code
```

to exact:

```text
plan_id
```

The legal acceptance request must expose a typed optional:

```python
plan_id: uuid.UUID | None = None
```

For `recurring_consent`, require:

```text
plan_id
entrypoint_type
entrypoint_value
```

Validate the Plan against the current tenant/region and sellable window before persisting it.

Persist the canonical UUID string under backend-owned metadata:

```text
metadata.plan_id
```

A client-provided generic metadata key named `plan_id` must not override the validated typed field.

`metadata.plan_code` must stop participating in recurring-consent validity.

A consent for Plan A must not authorize Plan B when:

```text
PlanA.id != PlanB.id
```

including:

```text
PlanA.code == PlanB.code
```

The normal checkout UI must still allow a new append-only acceptance for Plan B.

## 9. Checkout response is purchase-oriented, not `product_state`-oriented

The checkout-intent endpoint creates a purchase/order, so its response should not model the result as a generic Product state.

Use named response models equivalent to:

```python
class CheckoutPurchaseResponse(BaseModel):
    order_id: uuid.UUID
    plan_id: uuid.UUID
    plan_code: str
    plan_name: str
    scope_type: SubscriptionScopeType
    product_id: uuid.UUID | None
    bundle_id: uuid.UUID | None
    invoice_id: str


class CheckoutPaymentResponse(BaseModel):
    amount_minor: int
    amount: float
    currency: str
    action: CheckoutAction


class CheckoutIntentResponse(BaseModel):
    status: Literal["pending"] = "pending"
    purchase: CheckoutPurchaseResponse
    checkout: CheckoutPaymentResponse
```

Reuse the existing provider-neutral `CheckoutAction`.

Preserve the frontend action envelope:

```text
checkout.amount
checkout.currency
checkout.action
```

Do not redesign `/api/auth/session` or `/api/auth/payment-status` in this ticket. Those legacy presentation endpoints may still contain old product-oriented projections; they must not be used as justification to restore `all-access` into checkout purchase resolution.

## 10. Provider identifiers are opaque

The current merchant/invoice ID must stop encoding product/entrypoint-like strings.

Use an opaque, implementation-defined identifier that carries no catalog, scope, or entrypoint semantics.

Current implementation:

```python
def make_invoice_id() -> str:
    return uuid.uuid4().hex
```

The UUID representation is technical infrastructure data, not a Product, Plan, scope, or entrypoint identity.

Do not encode:

```text
Product.code
Bundle.code
Plan.code
scope_type
entrypoint_type
entrypoint_value
```

into the invoice ID.

## 11. Provider/order metadata is backend-derived

Do not copy removed request fields such as `payload.product` or `payload.plan_code` into persisted/provider metadata.

Where useful, derive metadata from the resolved persisted Plan:

```text
plan_id
plan_code
scope_type
```

and already validated checkout context:

```text
auto_renew
recurring_consent_acceptance_id
```

For a product-scoped OrderItem, `product_code_snapshot` comes from the persisted referenced Product, never from the request.

## 12. ANY-323 must rebase onto this contract

`ANY-323` is a structural move/refactor. It must not restore the contract that caused `ANY-327`.

After `ANY-327`, the rebased ordering flow must preserve:

```text
plan_id as exact purchase authority
backend-derived SubscriptionScopeType
explicit entrypoint provenance
exact-plan recurring consent
opaque invoice IDs
no product + plan_code request identity
no synthetic all-access alias
no branch-local duplicate scope enum
```

## 13. Linear ownership must match the implementation

The current `ANY-327` ticket is research-oriented, but Steps 2-3 are runtime changes.

Before Step 2 choose exactly one:

1. update `ANY-327` so its description/DoD explicitly owns the runtime implementation and change its type appropriately; or
2. keep `ANY-327` as the research/ADR decision and execute Steps 2-3 under one dedicated implementation follow-up.

Do not duplicate the same runtime work across `ANY-327`, `ANY-324`, and `ANY-323`.

## Out of Scope

- adding bundle purchase cards to the current frontend catalog;
- adding an all-access purchase card/route to the current frontend catalog;
- defining a new public `all-access` slug or compatibility vocabulary;
- changing prices, seed contents, plan limits, or bundle membership;
- changing persisted subscription/entitlement scope value `all_access`;
- redesigning `/api/account/subscriptions`;
- changing the final ANY-370 entitlement/ownership semantics;
- PostgreSQL native enums;
- the future Platform Kernel `/v1/access/check` work from `ANY-79`;
- performing the `ANY-323` ordering-domain structural move inside this ticket;
- unrelated CloudPayments webhook/recurring-subscription orchestration;
- unrelated payment-status/account API redesign;
- backwards-compatible aliases for the old checkout request.

---

# Step 1 — Record the exact Plan-based checkout contract

**Status:** `todo`  
**Commit:** `docs(architecture): define plan-based checkout identity`

## Prompt

Implement Step 1 of ANY-327: document the exact Plan-ID checkout identity and removal of the legacy synthetic `all-access` checkout sentinel.

Do not modify application runtime behavior in this step.

Do not research Linear, GitHub history, ANY-370, or unrelated repository areas again. The architectural decisions in this plan are locked.

Do not run tests, linters, formatters, type checks, generators, or repository-wide automated checks.

## Goal

Create a durable architecture decision that makes these boundaries unambiguous:

```text
Plan.id = exact purchase identity
Product = catalog/access entity
SubscriptionScopeType = backend-derived access semantics
Entrypoint = provenance
all-access = removed legacy checkout sentinel
```

## Relevant existing documentation

Work primarily in:

```text
docs/architecture/decisions/README.md
docs/architecture/payment-portal-data-model.md
```

Create:

```text
docs/architecture/decisions/0002-plan-based-checkout-identity.md
```

Do not rewrite unrelated architecture documentation.

## Implementation

### 1. Create ADR 0002

Use the repository ADR structure:

```text
# 0002. Plan-based checkout identity

Status: accepted
Date: <current implementation date>

## Context
...

## Decision
...

## Consequences
...
```

Record explicitly:

1. The current frontend catalog receives persisted Product data and an exact sellable `Plan.id` from backend data.
2. `Plan.id` is the only commercial purchase identity submitted by checkout.
3. `Product.code`, `Bundle.code`, and `Plan.code` are not generic checkout purchase selectors.
4. `product` and `plan_code` are removed from `CheckoutIntentRequest` after migration; no compatibility aliases are retained.
5. `SubscriptionScopeType` is derived server-side from `Plan.scope_type`.
6. `all_access` remains a canonical scope value and may appear in backend-derived access/read models, but the checkout client never submits it to select a purchase.
7. The synthetic string `all-access` is removed from the checkout runtime contract and is not a valid purchase identifier or scope alias.
8. No fake Product/Bundle row is created for all-access scope.
9. Entrypoint fields are provenance only and never participate in Plan resolution.
10. Current product navigation may continue using `?product=<Product.code>` because that is UI selection, not purchase authority.
11. Recurring consent binds to exact `plan_id` plus the existing user/contour/legal/entrypoint dimensions.
12. Same-code/different-ID Plan versions require new recurring consent when automatic renewal is selected.
13. Provider merchant/invoice IDs are opaque and contain no catalog/scope strings.
14. Checkout response is purchase/Plan-oriented while preserving the existing provider-neutral `checkout.amount` / `checkout.currency` / `checkout.action` envelope.
15. Final ANY-370 ownership semantics remain independent from purchase selection: bundle/all_access entitlements may block buying a selected Product without becoming checkout identifiers.
16. `ANY-323` must preserve this contract after rebase.

### 2. Add ADR 0002 to the ADR index

Update only `## Records` in:

```text
docs/architecture/decisions/README.md
```

### 3. Update the normative data-model document

In the checkout/catalog/access sections of:

```text
docs/architecture/payment-portal-data-model.md
```

record:

```text
backend catalog returns Product + exact current Plan
-> frontend selects Product for UI
-> frontend submits Plan.id for checkout
-> backend resolves exact current Plan
-> backend validates Plan scope/reference shape
-> backend derives scope and commercial snapshots
-> order/order_item persist resolved facts
```

Also record:

```text
entrypoint_session != purchased object
```

and:

```text
all_access entitlement/scope semantics != synthetic all-access checkout identity
```

Document the recurring-consent invariant:

```text
same Plan.id + same user/contour/legal/entrypoint context -> consent may validate
new Plan.id -> previous recurring consent does not authorize the new Plan
-> checkout provides a fresh append-only consent path
```

Document that final ANY-370 ownership checks may detect access through direct Product, containing Bundle, or `all_access` entitlement, and this does not change the checkout request identity.

## Scope constraints

Do not:

- change Python or TypeScript runtime code;
- change migrations or seed data;
- add an all-access Product/Bundle;
- define `all-access` as a valid public checkout identifier;
- remove/rename persisted `all_access` scope semantics;
- add bundle/all-access purchase UI;
- redesign unrelated state-machine/provider/account APIs.

## After implementation — report

Report:

1. files changed;
2. exact ADR decision;
3. exact meaning of `Plan.id`, Product identity, `scope_type`, and entrypoint provenance;
4. confirmation that `all-access` is rejected as target checkout vocabulary;
5. confirmation that `all_access` remains only access/scope semantics and is never a checkout purchase selector;
6. confirmation that ANY-370 ownership semantics remain intact in the documented target;
7. exact manual checks I should run.

## Manual verification after Step 1

Run manually:

```bash
git diff --check
git diff -- docs/architecture/decisions/README.md docs/architecture/decisions/0002-plan-based-checkout-identity.md docs/architecture/payment-portal-data-model.md
```

Confirm:

```text
Plan.id is the checkout request authority
Product.code is UI/catalog identity, not purchase authority
scope_type is backend-derived
all-access is documented only as removed legacy checkout behavior
all_access remains scope/access semantics
entrypoint is provenance only
ANY-370 ownership semantics are not conflated with purchase identity
ANY-323 rebase rule is explicit
```

If any statement contradicts those invariants, fix the docs before Step 2.

## Commit

```text
docs(architecture): define plan-based checkout identity
```

---

# Step 2 — Replace backend checkout purchase resolution with exact Plan ID

**Status:** `todo`  
**Commit:** `refactor(checkout): resolve purchases by plan id`  
**Depends on:** Step 1 completed, manually verified, committed, and runtime work explicitly owned in Linear.

## Prompt

Implement Step 2 of ANY-327: migrate the current backend checkout and recurring-consent boundary to exact persisted `Plan.id` purchase identity.

Step 1 is complete and the architecture is fixed. Do not redesign it.

Do not implement the ANY-323 ordering-domain structural move in this step. Modify the current main checkout implementation and its direct legal/query/test dependencies only. ANY-323 will rebase later.

Do not inspect unrelated Linear tickets, PR history, or broad repository areas.

Do not run tests, linters, formatters, type checks, generators, or repository-wide automated checks. Do not manually edit generated OpenAPI. The user will run generation and verification after implementation.

## Goal

The backend checkout boundary must accept exactly one commercial purchase identity:

```text
plan_id
```

and derive Product/Bundle/scope/commercial facts from persistence.

The backend must not require, compare, synthesize, or return the legacy `all-access` string for checkout purchase resolution.

## Relevant existing code

Work primarily in:

```text
apps/api/app/domains/identity/router.py
apps/api/app/domains/legal/router.py
apps/api/app/domains/legal/service.py
apps/api/app/infrastructure/queries/plans.py
apps/api/app/infrastructure/queries/products.py
apps/api/app/domains/billing/enums.py
apps/api/app/domains/billing/service/lifecycle_operations.py
apps/api/app/payment_providers/contracts.py
apps/api/tests/test_api.py
apps/api/tests/test_billing_lifecycle.py
```

Inspect a Bundle query/model helper only if required to validate an existing bundle-scoped Plan by ID.

Generated OpenAPI will be updated manually after implementation using the existing repository generator.

Do not create a new ordering domain in this step.

## Implementation

### 1. Replace `CheckoutIntentRequest`

Change the current request contract to the exact equivalent of:

```python
class CheckoutIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: uuid.UUID
    auto_renew: bool = False
    recurring_consent_acceptance_id: uuid.UUID | None = None
    entrypoint_type: str
    entrypoint_value: str
    frontend_id: str | None = None
    source_url: str | None = None
```

Remove:

```text
product
plan_code
```

Do not add compatibility aliases/parsing for them.

`extra="forbid"` is required so old or invented selector fields fail explicitly rather than being silently ignored.

### 2. Resolve the exact current sellable Plan by ID

Add/reuse a narrow query helper with these constraints:

```text
Plan.id == payload.plan_id
Plan.tenant_id == current user tenant
Plan.region == current user region
Plan.status == active
Plan.valid_from <= now
Plan.valid_to is null OR Plan.valid_to > now
```

Return at most one Plan.

Do not:

```text
resolve by Plan.code
select latest by code
fallback ID -> code
compare entrypoint with plan code
```

### 3. Derive and validate scope/reference shape

Convert persisted scope through the canonical enum:

```python
SubscriptionScopeType(plan.scope_type)
```

Fail closed for unsupported persisted scope.

For `PRODUCT`:

- require `product_id`;
- require `bundle_id is None`;
- load referenced Product by ID;
- require Product exists and is active;
- capture persisted `Product.code` only for server-side snapshots/logging where required.

For `BUNDLE`:

- require `bundle_id`;
- require `product_id is None`;
- load referenced Bundle by ID;
- require Bundle exists and is active.

For `ALL_ACCESS`:

- require `product_id is None`;
- require `bundle_id is None`;
- do not load/synthesize Product/Bundle identity;
- do not compare or construct the legacy `all-access` string.

This branch exists because `all_access` is a persisted domain scope. It must not create a new frontend purchase path or request vocabulary.

### 4. Replace the untyped sellable dict with a typed resolved model

Use a small internal immutable model equivalent to:

```python
class ResolvedCheckoutPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: uuid.UUID
    code: str
    name: str
    scope_type: SubscriptionScopeType
    product_id: uuid.UUID | None
    bundle_id: uuid.UUID | None
    product_code: str | None
    price_amount_minor: int
    currency: str
    trial_days: int
    billing_period: str
    renewal_mode: str
    pricing_snapshot: dict
```

For non-product scope, `product_code` is null.

Do not put `entrypoint_value` in this model. Entrypoint provenance is not a Plan property.

### 5. Persist explicit entrypoint provenance without using it for purchase resolution

Persist:

```text
EntrypointSession.entrypoint_type = payload.entrypoint_type
EntrypointSession.entrypoint_value = payload.entrypoint_value
```

Do not derive either value from the resolved Plan.

Do not use them to decide which Plan is being purchased.

Do not synthesize `all-access` for any scope.

### 6. Move recurring-consent commercial binding to exact Plan ID

Add to `AcceptDocumentRequest`:

```python
plan_id: uuid.UUID | None = None
```

For `recurring_consent`, fail closed unless these are present:

```text
plan_id
entrypoint_type
entrypoint_value
```

Validate the supplied Plan ID using the same tenant/region/current-sellable semantics used by checkout.

Persist validated exact ID under backend-owned:

```text
metadata.plan_id = str(plan.id)
```

Rules:

- client `metadata.plan_id` must not override typed validated `payload.plan_id`;
- `metadata.plan_code` no longer participates in recurring-consent validity;
- unrelated generic acceptance metadata remains unchanged where already supported;
- non-recurring documents do not become generically Plan-scoped.

Update:

```text
is_current_recurring_consent_acceptance(...)
get_current_recurring_consent_acceptance(...)
```

so the commercial parameter is `plan_id`, with exact comparison against stored validated metadata.

Keep all existing fail-closed user/tenant/region/legal/hash/time/entrypoint checks.

### 6.1 Preserve ANY-379 lifecycle revalidation

`enable_automatic_renewal()` reuses the same security predicate after payment.

Change that call from:

```text
plan_code = plan.code
```

to:

```text
plan_id = plan.id
```

Do not alter renewal state transitions, provider-reference ordering, or orchestration beyond this commercial-identity migration.

### 6.2 Preserve a working re-consent path

When `auto_renew=true`:

```text
resolve exact Plan
-> evaluate ordinary required documents
-> validate supplied recurring consent against exact plan_id + entrypoint
-> if missing/invalid for this Plan, return current recurring_consent document as missing
-> frontend records a new append-only acceptance for this plan_id
-> checkout retries with the new acceptance_id
```

Required scenario:

```text
accept current recurring consent for Plan A
-> catalog later selects Plan B
-> Plan B may even have the same Plan.code
-> old acceptance does not authorize Plan B
-> checkout asks for recurring consent again
-> accept for Plan B
-> checkout succeeds
```

Do not mutate old `DocumentAcceptance` rows.

If no current required recurring-consent document exists while automatic renewal requires it, fail closed.

### 7. Make invoice IDs opaque

Change the generator to:

```python
def make_invoice_id() -> str:
    return uuid.uuid4().hex
```

The identifier must remain opaque. No product/bundle/plan/scope/entrypoint string may be embedded in it; the current UUID-hex representation is an implementation strategy, not a business identity.

### 8. Derive order/provider metadata from persistence

Remove metadata writes sourced from removed request fields.

Use backend-derived values where useful:

```text
plan_id
plan_code
scope_type
```

Keep already validated context such as:

```text
auto_renew
recurring_consent_acceptance_id
```

For `OrderItem.product_code_snapshot`:

```text
PRODUCT -> resolved persisted Product.code
BUNDLE -> null
ALL_ACCESS -> null
```

Do not add a new schema field solely for this ticket.

### 9. Replace checkout `product_state` response with a purchase model

Define/use named response models equivalent to the locked contract:

```python
class CheckoutPurchaseResponse(BaseModel):
    order_id: uuid.UUID
    plan_id: uuid.UUID
    plan_code: str
    plan_name: str
    scope_type: SubscriptionScopeType
    product_id: uuid.UUID | None
    bundle_id: uuid.UUID | None
    invoice_id: str


class CheckoutPaymentResponse(BaseModel):
    amount_minor: int
    amount: float
    currency: str
    action: CheckoutAction


class CheckoutIntentResponse(BaseModel):
    status: Literal["pending"] = "pending"
    purchase: CheckoutPurchaseResponse
    checkout: CheckoutPaymentResponse
```

Use `response_model=CheckoutIntentResponse`.

Reuse existing provider-neutral `CheckoutAction` and preserve:

```text
checkout.amount
checkout.currency
checkout.action
```

Remove checkout-intent response dependency on:

```text
product_state
present_product_state(...)
```

Do not redesign `/api/auth/session` or `/api/auth/payment-status` here.

### 10. Update provider checkout metadata

Provider action metadata must not depend on input Product/Plan codes.

Derive any commercial metadata from the resolved Plan.

Do not add provider-specific domain branching.

### 11. Add focused backend regression coverage

Reuse existing test setup/fixtures. Do not create a second seed system.

At minimum cover:

1. direct-product checkout succeeds using the catalog Plan ID plus required context;
2. request `product` is rejected;
3. request `plan_code` is rejected;
4. client-supplied `scope_type` is rejected;
5. an invented `all_access` checkout selector field is rejected as extra input;
6. no request path requires or accepts a synthetic `all-access` purchase sentinel;
7. unknown Plan ID is rejected;
8. Plan ID from another tenant or region is rejected;
9. inactive, future, and expired Plan IDs are rejected;
10. product-scoped Plan with invalid/missing/inactive referenced Product fails closed;
11. bundle-scoped Plan with invalid/missing/inactive referenced Bundle fails closed;
12. invalid persisted scope/reference shape fails closed;
13. persisted `all_access` scope is handled only as a server-derived scope and never causes synthesis/comparison of `all-access`;
14. invoice ID is opaque and contains no product/bundle/plan/scope/entrypoint strings; the current implementation uses `uuid.uuid4().hex`;
15. recurring consent for Plan A validates Plan A;
16. the same acceptance is rejected for another Plan ID, including same-code/different-ID version;
17. Plan B can reacquire the same current recurring-consent document through the normal missing-document flow;
18. recurring consent without typed Plan ID/entrypoint context fails closed;
19. generic client metadata cannot spoof backend-owned `metadata.plan_id`;
20. `enable_automatic_renewal()` accepts only exact Plan-matching consent;
21. checkout response exposes `purchase`, not checkout `product_state`;
22. checkout response preserves `checkout.amount`, `checkout.currency`, and `checkout.action`;
23. product order-item snapshot comes from persisted Product.code, not request data;
24. generated OpenAPI reflects the new request/response and legal acceptance contract.

## Scope constraints

Do not:

- add or modify catalog seed Products/Plans;
- add an all-access Product/Bundle;
- add a public all-access purchase flow;
- change DB columns/migrations;
- rename persisted `all_access` scope values;
- create a duplicate scope enum;
- implement the ANY-323 ordering package/refactor;
- add backward-compatible checkout request aliases;
- change subscription/entitlement state transitions beyond the exact Plan-ID consent revalidation migration;
- change webhooks/cancellation/account behavior;
- redesign `/api/auth/session` or `/api/auth/payment-status`;
- run automated checks.

## After implementation — report

Report:

1. files changed;
2. final `CheckoutIntentRequest`;
3. exact Plan lookup constraints;
4. scope/reference validation rules;
5. confirmation that no checkout resolution branch uses `all-access`;
6. confirmation that `all_access` is server-derived scope only;
7. recurring-consent Plan-ID binding and re-consent path;
8. confirmation that `enable_automatic_renewal()` uses exact Plan ID;
9. final checkout response;
10. invoice format;
11. provider/order metadata changes;
12. exact manual commands I should run.

## Manual verification after Step 2

Generate artifacts manually:

```bash
npm run generate
npm run generate:check
```

Run focused backend tests:

```bash
pytest apps/api/tests/test_api.py -k "checkout or recurring_consent"
pytest apps/api/tests/test_billing_lifecycle.py -k "automatic_renewal"
```

Then:

```bash
git diff --check
npm run check:fast
```

Inspect:

```bash
git diff -- docs/generated/openapi.json
```

Confirm in OpenAPI:

```text
CheckoutIntentRequest requires plan_id
CheckoutIntentRequest does not define product
CheckoutIntentRequest does not define plan_code
CheckoutIntentRequest does not define scope_type
CheckoutIntentResponse has purchase
purchase.scope_type is server-produced SubscriptionScopeType
checkout keeps amount/currency/action
AcceptDocumentRequest exposes typed optional plan_id
```

Also inspect the production diff and confirm:

```text
no checkout purchase-resolution comparison against "all-access"
no client-supplied all_access is used to select a purchase
no compatibility alias restores product + plan_code
```

If any check fails, fix Step 2 before Step 3.

## Commit

```text
refactor(checkout): resolve purchases by plan id
```

---

# Step 3 — Make the final ANY-370 frontend submit exact catalog Plan ID

**Status:** `todo`  
**Commit:** `refactor(web): submit checkout by plan id`  
**Depends on:** Step 2 completed, manually verified, generated artifacts updated, and committed.

## Prompt

Implement Step 3 of ANY-327: migrate the final ANY-370 frontend checkout flow to the exact Plan-ID request/response contract without regressing its scope-aware ownership protections.

The backend contract from Step 2 is complete. Do not modify backend behavior in this step unless a direct type/compile mismatch from the committed Step 2 contract requires a minimal correction.

ANY-370 is already merged. The frontend catalog is backend-backed, each `CatalogProduct.plan` contains `plan_id`, and selected-product availability is guarded by the final scope-aware ownership implementation.

Do not research repository architecture, Linear, or PR history again.

Do not run tests, linters, formatters, type checks, generators, or repository-wide automated checks.

## Goal

Keep product selection as UI behavior:

```text
?product=<Product.code>
-> find selected CatalogProduct from backend catalog
```

but submit only the exact commercial identity:

```text
selectedProduct.plan.plan_id
```

At the same time preserve the merged ANY-370 rule that a Product already covered by a direct, bundle, or `all_access` entitlement cannot be purchased again.

## Relevant existing code

Work primarily in:

```text
apps/web/src/features/checkout/CheckoutClient.tsx
apps/web/src/features/checkout/ownership.ts
apps/web/src/features/checkout/CheckoutProductPanels.tsx
apps/web/src/features/catalog/api.ts
apps/web/src/shared/api/subscriptions.ts
apps/web/tests/components/CheckoutClient.test.tsx
```

`ownership.ts`, `CheckoutProductPanels.tsx`, and `shared/api/subscriptions.ts` are listed because they are part of the final ANY-370 checkout behavior that must be preserved; do not rewrite them unless the new response typing requires a minimal direct adjustment.

Do not expand the catalog to bundle/all-access purchase UI.

## Implementation

### 1. Keep the backend catalog as the only source of Product/Plan commercial selection

Continue loading Products through the backend catalog introduced by ANY-370.

Do not restore hardcoded commercial data.

Resolve the current UI Product from the catalog, then use:

```text
selectedProduct.plan.plan_id
```

for checkout.

Do not use the URL `product` query parameter directly in the POST body as purchase authority.

### 2. Replace the checkout POST body

Remove:

```typescript
product: selectedProduct.code,
plan_code: selectedProduct.plan.code,
```

Send the equivalent of:

```typescript
{
  plan_id: selectedProduct.plan.plan_id,
  auto_renew: autoRenew,
  recurring_consent_acceptance_id: ... when applicable,
  entrypoint_type: "product",
  entrypoint_value: selectedProduct.code,
  source_url: window.location.pathname + window.location.search
}
```

The entrypoint pair is provenance for the current direct-product UI only.

Do not send:

```text
product
plan_code
scope_type
all_access
all-access
```

as purchase identity.

### 3. Bind recurring-consent acceptance to exact selected Plan ID

When accepting a `recurring_consent` document, send typed:

```text
plan_id: selectedProduct.plan.plan_id
```

and the same explicit entrypoint type/value that checkout will use.

Do not send typed Plan ID for unrelated non-recurring documents.

Stop sending `metadata.plan_code` as commercial authority.

Do not manufacture `all-access` or send `all_access` in legal acceptance payloads.

When backend checkout surfaces the current recurring-consent document again because the existing acceptance belongs to another Plan, reuse the existing missing-document acceptance UI, create a new acceptance for the current `plan_id`, and retry checkout using its returned acceptance ID.

### 4. Key cached recurring-consent evidence by exact Plan ID

The current key:

```typescript
`${selectedProduct.code}:${selectedProduct.plan.code}`
```

is not exact enough for versioned Plans.

Use the exact selected Plan ID as the commercial context key, preferably:

```typescript
selectedProduct.plan.plan_id
```

The selected Plan ID is globally unique, so Product.code is not needed to make the commercial key unique.

Invariant:

```text
same Product.code
same Plan.code
different Plan.plan_id
-> commercial checkout context changed
-> clear cached recurringConsentAcceptanceId
-> reacquire consent for new Plan when auto-renew is selected
```

Keep session-user invalidation as the separate existing key.

### 5. Consume `purchase` response instead of checkout `product_state`

Replace the frontend-local checkout response type with Step 2's contract:

```text
status
purchase
checkout
```

Consume as needed:

```text
purchase.invoice_id
purchase.plan_id
purchase.plan_code
purchase.plan_name
purchase.scope_type
checkout.amount
checkout.currency
checkout.action
```

Do not expect checkout-intent `product_state`.

The selected Product is already known from the backend catalog and remains the source of customer-facing Product presentation.

Do not create a fake `AuthProductState` from the generic `purchase` response merely to preserve the old shape.

If the UI needs to prevent another click while payment is being prepared/launched, use the existing request/loading state rather than synthesizing entitlement state from checkout response.

Session/payment-status ownership projections remain separate APIs.

### 6. Preserve ANY-370 scope-aware ownership behavior unchanged

Continue using:

```text
resolveSelectedProductAccess(...)
useCheckoutOwnership(...)
hasCurrentProductEntitlement(...)
SelectedProductCard
SubscriptionState
```

Do not simplify ownership to only direct `product_state`.

The following must still block purchase for the selected Product:

```text
active direct Product access
active Bundle entitlement containing selected product_id
active all_access entitlement
```

The following must remain fail closed:

```text
ownership checking/loading
ownership API error
```

This is the only legitimate reason `all_access` is relevant in this frontend area: it describes an existing entitlement that covers the selected Product. It is never sent to checkout to identify what is being purchased.

### 7. Keep payment-result presentation separate from purchase identity

Stored result/presentation may continue using values already known from the selected backend catalog Product:

```text
productCode
productName
planName
```

for UI copy.

Set invoice ID from:

```text
checkoutIntent.purchase.invoice_id
```

Do not derive invoice IDs from Product/Plan codes.

### 8. Add/update focused frontend regression coverage

Update the existing CheckoutClient tests to prove both the new contract and the final ANY-370 protections.

At minimum cover:

1. selected Product/commercial display still comes from backend catalog;
2. checkout POST contains exact `plan_id` from `CatalogProduct.plan.plan_id`;
3. checkout POST does not contain `product`;
4. checkout POST does not contain `plan_code`;
5. checkout POST does not contain `scope_type`;
6. checkout POST does not contain `all_access` or `all-access`;
7. entrypoint provenance is explicit and separate from purchase identity;
8. recurring-consent acceptance sends typed exact Plan ID only for the recurring document;
9. recurring-consent acceptance and checkout use identical entrypoint type/value;
10. same-code/different-ID Plan change clears cached recurring acceptance;
11. backend missing-document Plan-B re-consent is handled by the existing acceptance UI and retry;
12. checkout response is consumed through `purchase`, not checkout `product_state`;
13. `checkout.amount`, `checkout.currency`, and `checkout.action` remain unchanged provider-neutral envelope;
14. payment-result storage uses `purchase.invoice_id`;
15. direct active selected-product access still blocks checkout;
16. containing Bundle entitlement still blocks selected-product checkout;
17. active `all_access` entitlement still blocks selected-product checkout;
18. ownership loading/checking still blocks checkout controls;
19. ownership error still blocks checkout controls;
20. authenticated product-picker/selected-product flow does not fall back to guest ownership semantics;
21. CheckoutClient contains no special-case purchase behavior for `all-access` / `all_access`;
22. changing catalog `plan_id` changes submitted purchase identity without changing frontend constants.

When fixtures for checkout response are updated, use the Step 2 `purchase` shape rather than rebuilding the removed checkout `product_state` response.

## Scope constraints

Do not:

- change the current catalog API shape beyond consuming its existing `plan_id`;
- add bundle/all-access purchase cards/routes;
- remove `all_access` from account subscription/access decoding;
- weaken scope-aware entitlement ownership checks;
- change prices or marketing copy;
- redesign payment-result polling;
- introduce hardcoded Plan IDs;
- create frontend enums for dynamic Product/Plan codes;
- send scope type from frontend;
- add compatibility with old checkout request;
- run automated checks.

## After implementation — report

Report:

1. files changed;
2. exact checkout POST body;
3. exact recurring-consent acceptance payload;
4. exact Plan-ID checkout context key;
5. checkout response fields consumed;
6. confirmation that catalog Plan ID is the only purchase authority;
7. confirmation that `?product=` is navigation only;
8. confirmation that no `all-access` purchase special case remains;
9. confirmation that `all_access` remains only entitlement/access semantics in this frontend path;
10. confirmation that direct/bundle/all_access ownership protections from ANY-370 are preserved;
11. confirmation that no fake checkout `AuthProductState` is created from `purchase`;
12. exact manual commands I should run.

## Manual verification after Step 3

Run focused component tests:

```bash
npm --workspace @anytoolai/web run test:components -- tests/components/CheckoutClient.test.tsx
```

Then:

```bash
npm run typecheck:web
npm run lint:web
git diff --check
npm run check
```

Manually inspect a direct-product checkout request.

It must contain:

```text
plan_id
entrypoint_type = product
entrypoint_value = selected Product.code
auto_renew
recurring_consent_acceptance_id when required
```

It must not contain:

```text
product
plan_code
scope_type
all-access
all_access
```

Inspect the checkout response and confirm:

```text
purchase.plan_id
purchase.plan_code
purchase.scope_type
purchase.invoice_id
checkout.amount
checkout.currency
checkout.action
```

and no checkout-intent `product_state` object.

Then manually verify the existing selected-product access behavior:

```text
direct entitlement -> no purchase action
containing bundle entitlement -> no purchase action
all_access entitlement -> no purchase action
ownership loading/error -> no purchase action
no covering entitlement -> purchase action available
```

If any check fails, fix Step 3 before committing.

## Commit

```text
refactor(web): submit checkout by plan id
```

---

# Post-ANY-327 Requirement for ANY-323

`ANY-323` must be rebased onto the completed ANY-327 state before its PR is resumed.

The following old concepts must not survive the rebase:

```text
CheckoutIntentRequest.product
request plan_code as purchase authority
ResolveSellablePlanInput.entrypoint_code as purchase selector
{"all-access", plan.code} alias matching
SellablePlan.entrypoint_value as purchase identity
branch-local duplicate PlanScopeType
invoice IDs built from sellable/entrypoint strings
```

The ordering resolver after rebase must conceptually remain:

```text
current user + exact plan_id
-> exact current persisted Plan
-> validate persisted scope/reference shape
-> load referenced Product/Bundle when required
-> derive SubscriptionScopeType
-> persist order/order-item snapshots
```

Entrypoint remains explicit provenance.

The rebased ordering flow must call the same exact-Plan recurring-consent predicate and preserve the Plan-A -> Plan-B re-consent path.

The existing lifecycle `enable_automatic_renewal()` revalidation must continue using exact Plan ID.

If ANY-323 cannot preserve this contract without a material design change, stop and review the conflict rather than restoring compatibility behavior.

---

# Final Definition of Done

ANY-327 implementation is complete only when all are true:

```text
[ ] ADR records exact persisted Plan.id as checkout purchase identity
[ ] normative docs separate Product identity, Plan purchase identity, access scope, and entrypoint provenance
[ ] docs explicitly classify "all-access" as removed legacy checkout sentinel, not target API vocabulary
[ ] persisted/read-model all_access remains canonical scope/access semantics
[ ] backend CheckoutIntentRequest accepts plan_id and no product/plan_code purchase fields
[ ] request schema forbids unknown legacy selector fields
[ ] backend resolves exact current Plan by ID + tenant + region + sellable window
[ ] Product/Bundle references are server-resolved and validated from the Plan
[ ] no checkout purchase-resolution branch compares or synthesizes "all-access"
[ ] scope_type is always derived from SubscriptionScopeType(plan.scope_type)
[ ] client never sends all_access/scope_type to select the purchase
[ ] recurring consent is bound to exact plan_id and exact entrypoint context
[ ] reserved acceptance metadata.plan_id is backend-owned and cannot be spoofed
[ ] same-code/different-ID Plan versions require and can acquire fresh recurring consent
[ ] ANY-379 enable_automatic_renewal revalidates recurring consent by exact plan_id
[ ] invoice IDs are opaque and contain no catalog/scope semantics
[ ] checkout-intent response uses purchase, not product_state, while preserving checkout.amount/currency/action
[ ] frontend submits selectedProduct.plan.plan_id from backend catalog
[ ] frontend ?product= value is navigation/provenance, not purchase authority
[ ] frontend recurring-consent cache is keyed by exact Plan ID
[ ] final ANY-370 scope-aware ownership behavior is preserved
[ ] direct Product entitlement blocks duplicate selected-product checkout
[ ] containing Bundle entitlement blocks duplicate selected-product checkout
[ ] all_access entitlement blocks duplicate selected-product checkout without becoming purchase identity
[ ] ownership checking/loading/error remains fail closed
[ ] frontend does not manufacture all-access/all_access purchase identifiers
[ ] frontend does not recreate checkout product_state from purchase response
[ ] OpenAPI reflects exact Plan-ID checkout and typed legal acceptance plan_id
[ ] targeted backend/billing lifecycle tests pass
[ ] targeted frontend tests pass
[ ] repository checks pass
[ ] Linear ownership/type explicitly covers runtime implementation, or Steps 2-3 run under one dedicated implementation follow-up
[ ] ANY-323 rebase requirement is captured and cannot silently restore the old ambiguity
```
