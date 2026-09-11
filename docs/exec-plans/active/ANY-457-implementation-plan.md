# ANY-457 — Deactivate CloudPayments Runtime and Frontend Checkout — Implementation Plan

## Plan Overview

| Field | Value |
| --- | --- |
| Project | `Payment portal` |
| Parent | `ANY-407` — target Payment Portal architecture |
| Ticket | `ANY-457` — Deactivate CloudPayments Runtime and Frontend Checkout |
| Overall status | `todo` |
| Architectural position | Transitional deactivation gate after ANY-407 Step 4 and before Step 5 |
| Required predecessor | `ANY-454` completed and present in `main` |
| Blocks | `ANY-455` — Establish Persistence Boundary |
| Recommended base | Up-to-date `main` containing completed ANY-454; do **not** base implementation on unmerged ANY-455 work |
| Execution order | Sequential only: Step 1 → manual verification → commit → Step 2 → ... → Step 6 |
| Steps / commits | 6 |
| Database migration | Not required |
| Database/data cleanup | Not required; no production CloudPayments data exists, and schema/code cleanup is explicitly deferred |
| Physical CloudPayments deletion | Explicitly deferred |
| New billing provider | Out of scope |
| Frontend change | Required |
| Generated OpenAPI change | Required after source changes; never hand-edit generated output |
| Post-merge handoff | Revalidate the ANY-455 implementation plan against the deactivated runtime before executing ANY-455 |

---

## How to Use This File

1. Create or rebase the `ANY-457` branch from current `main` after the completed `ANY-454` work.
2. Do **not** include ANY-455 branch changes in the implementation baseline. ANY-457 is now the gate that must complete before ANY-455.
3. Put this file at:

   ```text
   docs/exec-plans/active/ANY-457-implementation-plan.md
   ```

4. Execute one step at a time. Do not ask the implementation AI to implement several steps together.
5. For each step:
   - give the AI only that step;
   - let the AI inspect the directly relevant code and run the smallest useful focused checks while implementing;
   - review the diff;
   - manually run the listed step-level verification;
   - commit with the specified message only after verification passes;
   - mark the step `done` before starting the next one.
6. The implementation AI must not rerun broad Linear/GitHub research. The architectural decisions in this plan are locked. It may inspect only directly relevant current files and direct dependencies needed to implement the current step.
7. The implementation AI should format/lint changed code and may run small focused tests/checks needed to validate the current edit. It must not run broad test suites, repository-wide checks, generators, full browser suites, or other expensive verification unless the current step explicitly requires it. The human operator runs the complete step-level and final verification commands listed below.
   - Run Python verification from the repository root using the repository-owned root `.venv` (for example `./.venv/bin/python -m pytest ...`). Do not create or rely on `apps/api/.venv`.
8. If current code materially contradicts a locked assumption, stop the step and report the contradiction instead of inventing a compatibility layer, feature flag, replacement provider architecture, or broader refactor.
9. Do not start ANY-455 implementation until ANY-457 is merged and the ANY-455 plan has been revalidated against the new baseline.

---

# 1. Research Outcome and Current Baseline

## 1.1. Architectural position in ANY-407

ANY-407 now explicitly places ANY-457 between:

```text
ANY-454 — Sync / Async Architecture
              ↓
ANY-457 — Deactivate CloudPayments Runtime
              ↓
ANY-455 — Persistence Boundary
```

ANY-457 is **not** a new numbered architecture step. It is a transitional gate that removes direct CloudPayments from active normal runtime before persistence, transaction, DI/composition, and business-transition architecture are refined further.

Future external billing is a distinct integration model. It must not be implemented as another `PaymentProviderAdapter`, and ANY-457 must not invent the future billing webhook, checkout, REST contract, customer model, or vendor abstraction.

## 1.2. Current backend runtime is still CloudPayments-active

Current `apps/api/app/main.py` still:

- imports `CloudPaymentsAdapter`;
- imports and builds the CloudPayments API client;
- creates the adapter in `create_app()`;
- registers it in `PaymentProviderRegistry`;
- stores it on `app.state.cloudpayments_adapter`;
- attaches the API client during lifespan;
- closes the adapter during shutdown;
- mounts the active CloudPayments webhook router.

Therefore runtime deactivation is real work and cannot be achieved only by setting `CLOUDPAYMENTS_ENABLED=false`.

## 1.3. Existing generic provider boundary already fails closed

`PaymentProviderRegistry` supports an empty registry.

`get_or_create_checkout_provider_account(...)` returns the existing `503 payment_provider_unavailable` when the configured/default provider has no registered adapter. In the current checkout flow, provider/account resolution occurs before `EntrypointSession`, `CheckoutSession`, and `Order` are created.

This existing behavior is sufficient for the deactivated normal runtime. Do not add:

- `DisabledPaymentProvider`;
- a fake adapter;
- a replacement provider;
- a special testing provider in production composition;
- a new generic feature-flag framework.

## 1.4. Current CloudPayments webhook is an active processing surface

The current `/api/cloudpayments/{endpoint}` POST route:

- reads the request body;
- resolves a DB session;
- resolves the active CloudPayments adapter;
- verifies/normalizes the request;
- persists a webhook event;
- executes application transitions;
- records provider-specific processing results.

That behavior must stop being mounted in normal runtime after ANY-457.

## 1.5. Current frontend still activates CloudPayments

The frontend checkout adapter registry currently registers only `cloudPaymentsCheckoutAdapter`.

`/ru/auth-checkout` loads scripts for required adapters, so the CloudPayments widget script is currently loaded in normal checkout runtime.

`CheckoutClient` already has a `disabled` adapter status, but currently treats only `loading` and `failed` as blocking states. As a result, `disabled` can still reach `/api/auth/checkout-intent` before adapter resolution fails later in the client.

ANY-457 must make `disabled` an explicit terminal checkout-unavailable state.

## 1.6. Current runtime configuration still exposes CloudPayments

Current Settings, shared test environment, repository harness, and CI still expose CloudPayments as normal runtime/test configuration:

- `cloudpayments_enabled` is a required Settings field;
- startup validation conditionally requires CloudPayments credentials;
- Compose files forward CloudPayments public ID, secret, and enable flag;
- repository harness resolves CloudPayments credentials and writes them into `.harness/runtime.env`;
- `apps/api/tests/support/settings.py` injects CloudPayments enable/credential values into the shared default API test environment;
- the production CI gate still forwards `CLOUDPAYMENTS_ENABLED`;
- the browser CI job still enables the provider UI stub and supplies a CloudPayments public ID.

This creates a misleading supported-runtime/test contract even when the runtime flag is false and can keep CloudPayments assumptions alive only for tests.

## 1.7. No production cutover or data-migration obligation

Payment Portal is still under development and CloudPayments has never been launched as a production billing runtime. There are no production CloudPayments payments, subscriptions, webhook obligations, or persisted production billing data to migrate or drain.

This is a locked implementation premise for ANY-457. Therefore the repository does **not** need a compatibility callback, retry-absorption endpoint, migration bridge, or staged production cutover path merely to deactivate CloudPayments.

CloudPayments source code, models, migrations, and provider-specific persistence structures may remain temporarily because physical cleanup is intentionally deferred, not because live production traffic or historical production data must be preserved.

If this premise becomes false before merge/deployment, stop and re-evaluate the plan rather than silently adding compatibility behavior.

## 1.8. Agent documentation currently describes CloudPayments as active

Both root `AGENTS.md` and `apps/api/AGENTS.md` currently describe CloudPayments as the current direct-provider runtime and describe its verified webhooks as the current authoritative payment-fact path.

After ANY-457 that wording would be false and would mislead future AI work, so these files are part of the final documentation update.

---

# 2. Locked Decisions

## 2.1. Deactivate, do not physically delete

ANY-457 changes CloudPayments from:

```text
active runtime integration
```

to:

```text
deactivated retained integration
```

Retain unless a tiny deletion is strictly required for correctness:

- `integrations/cloudpayments` implementation;
- adapter/client code;
- provider-specific normalization/processing code;
- existing CloudPayments migrations;
- provider/payment/subscription/webhook persistence structures and any local development/test records;
- provider-specific low-level tests that remain meaningful for the retained implementation.

Physical dead-code/persistence cleanup is a later evidence-based decommission task.

## 2.2. Future billing does not reuse CloudPayments contracts

Do not preserve active CloudPayments runtime because a future billing system will need “an API”, “a webhook”, or “checkout”.

Future external billing may have a different:

- REST command model;
- webhook/event model;
- customer/invoice/payment/subscription authority;
- checkout model, including redirect/hosted checkout;
- reconciliation behavior.

CloudPayments source paths are retained only as temporary legacy implementation for later cleanup, not as an active compatibility surface or a template for future external billing.

## 2.3. Do not turn `CLOUDPAYMENTS_ENABLED` into the architecture

`CLOUDPAYMENTS_ENABLED` is not a reliable runtime composition boundary today because normal app composition creates CloudPayments regardless of that setting.

ANY-457 must not “fix” this by introducing a new reversible provider feature-flag architecture.

Normal supported runtime after ANY-457 simply does not compose CloudPayments.

Remove the misleading required `cloudpayments_enabled` Settings contract and normal harness/Compose forwarding. Retained CloudPayments code may keep optional credentials/API tuning settings needed for direct retained tests/manual sandbox verification, but those values are no longer normal application runtime requirements.

## 2.4. Keep the generic `PaymentProviderRegistry`, but empty in normal composition

Do not remove or redesign `PaymentProviderRegistry` in ANY-457.

Normal `create_app()` should create the registry and expose it through the existing app-state dependency, but register no CloudPayments adapter.

This preserves current generic checkout failure semantics while avoiding Step 7 DI/composition work and avoiding premature removal of the transitional provider abstraction.

## 2.5. Generic checkout remains, but fails closed

Do not deprecate `/api/auth/checkout-intent` merely because CloudPayments is disabled. It is a generic Payment Portal surface, not a CloudPayments-specific URL.

With no registered direct provider, a valid checkout attempt must fail with the existing:

```text
503 payment_provider_unavailable
```

before creation of provider-backed commercial checkout state.

At minimum, the failed request must not create a new:

- `PaymentProviderAccount`;
- `EntrypointSession`;
- `CheckoutSession`;
- `Order`.

Do not move provider resolution earlier/later merely for style if current behavior already satisfies this invariant.

## 2.6. Do not mount any CloudPayments API/webhook route in normal runtime

The existing CloudPayments router implementation may remain in source code, but normal `create_app()` must not mount it.

After ANY-457, the normal application has no active CloudPayments-specific HTTP surface:

```text
POST /api/cloudpayments/{endpoint}
→ normal application route is absent
→ HTTP 404 from normal FastAPI routing
```

Do **not** create a replacement `deactivated_router.py`, compatibility callback, retry-absorption endpoint, or deprecated placeholder API. There is no production CloudPayments traffic or consumer contract to preserve.

Do not modify the retained active `integrations/cloudpayments/router.py` merely to add `deprecated=True` or disabled branches. It is retained legacy source code and simply stops being part of normal application composition.

This means:

- no CloudPayments webhook body is read by normal runtime;
- no CloudPayments signature validation runs;
- no CloudPayments DB/webhook processing path is reachable through normal app routing;
- no provider-specific callback acknowledgement semantics need to be preserved;
- OpenAPI must no longer expose `/api/cloudpayments/{endpoint}` after generated artifacts are refreshed.

## 2.7. Frontend checkout is deliberately unavailable

The active frontend adapter registry becomes empty.

Retain the CloudPayments adapter implementation/type declarations temporarily, but do not register or load them in normal checkout runtime.

`CheckoutAdapterStatus = "disabled"` becomes an explicit blocked terminal state.

Required user behavior:

- show a neutral Russian temporary-unavailable message;
- payment action is disabled or short-circuits before any checkout preparation request;
- do not request `/api/auth/checkout-intent`;
- do not start or load the CloudPayments widget;
- do not manufacture a replacement billing flow;
- do not add a fake success path.

Suggested copy:

```text
Оплата временно недоступна. Попробуйте позже.
```

Button copy may be:

```text
Оплата недоступна
```

Preserve current catalog, auth, session, account, ownership, and legal-document behavior unrelated to initiating payment.

If a stale in-memory missing-document state could reach `acceptRequiredDocumentsAndContinue()`, that continuation must also short-circuit while checkout is disabled so deactivated checkout does not create new payment-specific legal acceptance activity as part of a payment continuation.

## 2.8. Do not create a hidden active-CloudPayments application mode for tests

Do not add:

- `create_app(enable_cloudpayments=True)`;
- environment-only hidden activation;
- test-only production composition root;
- a second active runtime path solely to keep old default-app tests unchanged.

Provider-specific retained tests may construct/test CloudPayments components directly where useful. Default application tests must represent the new normal deactivated runtime.

## 2.9. Retained persistence/schema stays intact

Do not delete or migrate away provider-specific fields, tables, enums, indexes, migrations, or persistence structures in ANY-457. There is no production CloudPayments data to migrate, so database cleanup is unnecessary for runtime deactivation.

ANY-455 will later classify persistence after CloudPayments runtime is inactive:

1. generic persistence still used by active Portal runtime;
2. retained legacy/audit-shaped persistence structures or local test/development data;
3. CloudPayments-only persistence with no active runtime consumers.

Only the first category is a candidate for normal ANY-455 architecture work. CloudPayments-only dead persistence is a later cleanup concern.

---

# 3. Operational Premise

ANY-457 is implemented under the confirmed project state that Payment Portal has not been launched with CloudPayments in production and contains no production CloudPayments billing data or operational obligations.

Therefore there is no production drain/cutover sequence in this ticket. Runtime deactivation is a repository/application-composition change only:

- stop composing CloudPayments backend runtime;
- stop exposing its router through the normal FastAPI app;
- stop exposing CloudPayments as supported runtime configuration;
- stop activating it in the frontend/browser runtime;
- retain the implementation source and persistence schema temporarily for later evidence-based cleanup.

No compatibility API should be invented for hypothetical traffic that does not exist.

---

# Step 1 — Remove CloudPayments from backend composition and routing

**Status:** `todo`  
**Commit:** `feat(api): deactivate CloudPayments runtime`

## Goal

Make the normal FastAPI application start without constructing, registering, attaching, shutting down, or routing to CloudPayments runtime objects. Retain the existing CloudPayments implementation source untouched where possible, but make it unreachable from normal application composition.

## Scope / affected code

Primary:

- `apps/api/app/main.py`
- `apps/api/tests/compatibility/test_app_factory.py`
- new `apps/api/tests/test_cloudpayments_deactivation.py`

Read only as needed:

- `apps/api/app/integrations/cloudpayments/router.py`
- `apps/api/app/integrations/cloudpayments/adapter.py`
- `apps/api/app/integrations/cloudpayments/api_client.py`
- `apps/api/app/payment_providers/registry.py`

Do not refactor or delete the retained implementation under:

```text
apps/api/app/integrations/cloudpayments/
```

The existing active router source may remain exactly where it is; it must simply stop being mounted by normal `create_app()`.

## Implementation decisions

### Backend composition

In `main.py`:

- remove `CloudPaymentsAdapter` construction from `create_app()`;
- remove `build_cloudpayments_api_client(...)` from normal lifespan;
- remove `app.state.cloudpayments_adapter`;
- remove adapter close/shutdown work;
- keep the existing `PaymentProviderRegistry` app-state boundary;
- create it empty and register no CloudPayments adapter;
- stop importing/mounting the active CloudPayments router;
- do **not** replace it with another CloudPayments router;
- preserve legal seed, observability, middleware, CORS, health, metrics, auth, catalog, account/billing, legal, and password-reset behavior.

### HTTP surface

Normal runtime must expose no CloudPayments-specific callback route.

Expected behavior:

```text
POST /api/cloudpayments/check
POST /api/cloudpayments/pay
POST /api/cloudpayments/anything
→ 404 in the normal application
```

The 404 is ordinary absence of the route, not a custom CloudPayments compatibility response.

Do not:

- create `deactivated_router.py`;
- add a compatibility callback;
- add `deprecated=True` to the retained active router solely for ANY-457;
- add disabled branches to the retained active router;
- add a CloudPayments feature flag or hidden activation seam.

## Tests

Add focused coverage proving:

1. `create_app()` has a configured `PaymentProviderRegistry` with no active adapters;
2. `app.state.cloudpayments_adapter` is absent;
3. app lifespan does not build, attach, or close a CloudPayments client/adapter;
4. normal application routing does not expose `/api/cloudpayments/{endpoint}`;
5. representative CloudPayments callback requests return ordinary `404`;
6. no replacement/deactivated CloudPayments runtime surface exists in normal composition;
7. non-CloudPayments startup/lifespan behavior from ANY-454 remains intact.

Do not require the retained active CloudPayments router itself to change for these tests.

## AI Prompt

```text
Implement only Step 1 of ANY-457: remove CloudPayments completely from normal FastAPI composition and routing, while retaining its source code for later cleanup.

The architectural decisions in the plan are locked. Do not redesign them.

Confirmed project premise:
- Payment Portal has never run CloudPayments in production.
- There are no production CloudPayments payments, subscriptions, webhook obligations, or persisted production billing data to migrate or drain.
- Therefore no compatibility/deprecated callback is required.

Relevant code:
- apps/api/app/main.py
- apps/api/app/integrations/cloudpayments/router.py (read only as retained legacy implementation that must stop being mounted)
- apps/api/app/integrations/cloudpayments/adapter.py only if needed to verify current wiring
- apps/api/app/integrations/cloudpayments/api_client.py only if needed to verify current lifespan wiring
- apps/api/app/payment_providers/registry.py
- apps/api/tests/compatibility/test_app_factory.py
- add apps/api/tests/test_cloudpayments_deactivation.py

Required outcome:
1. Normal create_app() must not construct or register CloudPaymentsAdapter.
2. Normal lifespan must not build, attach, or close a CloudPayments API client/adapter.
3. app.state.cloudpayments_adapter must no longer be part of normal composition.
4. Keep app.state.payment_provider_registry using the existing PaymentProviderRegistry, but leave it empty.
5. Stop importing and mounting the active CloudPayments router in normal create_app().
6. Do not replace it with a deactivated/compatibility router. Normal POST /api/cloudpayments/{endpoint} must simply be absent and return the normal application 404.
7. Do not modify the retained active CloudPayments router merely to mark it deprecated or add disabled branches.
8. Preserve every non-CloudPayments app route, middleware, observability, legal-seed, health and metrics behavior.
9. Do not delete or broadly refactor the retained CloudPayments adapter/client/router/processing implementation.
10. Do not add a feature flag, disabled provider class, replacement provider, test-only activation mode, compatibility layer, or future billing abstraction.
11. Add only focused app-factory/deactivation tests required by this step, including proof that the CloudPayments route is absent from normal runtime.

Implement only this step.
Do not perform broad repository research.
Inspect only directly relevant current files and direct dependencies needed to edit them.
Do not redesign architecture or perform unrelated refactoring.
Do not work on ANY-455 or later ANY-407 steps.
Format/lint changed Python code and run only the smallest focused tests/checks needed while implementing this step. Do not run broad API suites, repository-wide checks, generators, documentation checks, architecture checks, or browser suites; the human operator runs the complete verification block below.
Do not stage files and do not create commits.

After implementation:
- report every changed file;
- summarize the resulting backend composition;
- confirm whether any CloudPayments runtime object or route can still be initialized/exposed by normal app startup;
- report the exact manual verification commands below.

If current code materially contradicts a locked assumption, stop and report the exact contradiction instead of inventing another architecture.
```

## Manual verification

From repository root:

```bash
./.venv/bin/python -m pytest \
  apps/api/tests/compatibility/test_app_factory.py \
  apps/api/tests/test_cloudpayments_deactivation.py
```

## Expected completion

Normal FastAPI composition has no active CloudPayments adapter/client and no CloudPayments-specific HTTP route. Retained CloudPayments source code remains in the repository but is unreachable from normal application runtime.

---

# Step 2 — Align backend checkout/tests with the deactivated default runtime

**Status:** `todo`  
**Commit:** `test(api): align checkout with deactivated provider runtime`

## Goal

Make the new normal backend behavior explicit: generic checkout remains available as an API contract, but fails closed with no provider and creates no new checkout/payment state.

## Scope / affected code

Primary:

- `apps/api/tests/test_api.py`
- `apps/api/tests/test_cloudpayments_deactivation.py`
- `apps/api/tests/test_cloudpayments_adapter_api.py`
- existing provider-specific tests as directly required

Production code such as:

- `apps/api/app/payment_providers/accounts.py`
- `apps/api/app/domains/identity/router.py`

should not require change if the current fail-closed ordering remains intact.

## Implementation decisions

The existing provider resolution happens before creation of `EntrypointSession`, `CheckoutSession`, and `Order`. Preserve that ordering.

For a fully valid checkout request under normal deactivated app composition:

```text
POST /api/auth/checkout-intent
→ 503 payment_provider_unavailable
```

and the request must not create new provider/checkout/order state.

Update default-app tests that currently assume CloudPayments is automatically registered.

Retain useful provider-specific unit/integration coverage by testing retained CloudPayments components directly where appropriate.

Do not create a hidden application activation seam to make old tests pass.

## Tests

At minimum prove:

- normal app checkout returns the existing `503 payment_provider_unavailable` once all earlier request/business prerequisites are valid;
- no new `PaymentProviderAccount` is created;
- no new `EntrypointSession` is created;
- no new `CheckoutSession` is created;
- no new `Order` is created;
- existing non-provider auth/catalog/account/legal behavior remains unchanged;
- retained CloudPayments adapter API tests continue to cover the retained implementation without changing normal app composition.

Do not rewrite webhook processing tests to run through normal `app.main.app`, because the CloudPayments route is intentionally absent there. Retained low-level processing tests may call the retained processing boundary directly if they are still intentionally useful.

If `apps/api/tests/test_cloudpayments_webhook_postgres.py` is retained, it must no longer exercise the active CloudPayments processing router through `app.main.app`, because Step 1 intentionally removes that route from normal composition. Preserve useful retained processing tests by either:

- testing the retained processing boundary directly; or
- mounting the retained active CloudPayments router in a **test-local FastAPI fixture** with explicit test-only dependencies.

Do **not** reactivate CloudPayments in `create_app()`, add `create_app(enable_cloudpayments=True)`, introduce an environment activation switch, or create a second production composition root merely to preserve the old tests.

## AI Prompt

```text
Implement only Step 2 of ANY-457: align backend checkout and provider-specific tests with the new deactivated default runtime.

Step 1 is complete and normal create_app() now contains an empty PaymentProviderRegistry and no CloudPayments runtime adapter/client.

Relevant files:
- apps/api/tests/test_api.py
- apps/api/tests/test_cloudpayments_deactivation.py
- apps/api/tests/test_cloudpayments_adapter_api.py
- apps/api/tests/test_cloudpayments_webhook_postgres.py if retained processing coverage must be decoupled from app.main.app
- directly related provider-specific tests only when required
- apps/api/app/payment_providers/accounts.py and apps/api/app/domains/identity/router.py only to verify the existing fail-closed ordering

Required outcome:
1. A fully valid normal-app POST /api/auth/checkout-intent fails with the existing 503 payment_provider_unavailable when no direct provider is registered.
2. Prove that this failure creates no new PaymentProviderAccount, EntrypointSession, CheckoutSession, or Order.
3. Preserve the current ordering where provider/account resolution occurs before provider-backed checkout state is created. Do not reorder the checkout flow if the current implementation already satisfies the invariant.
4. Update old default-app test assumptions that expected CloudPayments to be active automatically.
5. Keep retained CloudPayments adapter/client/processing tests provider-specific and direct where useful. If the retained PostgreSQL webhook-processing suite currently imports `app.main.app` and posts to `/api/cloudpayments/...`, decouple it from normal composition: either call the retained processing boundary directly or mount the retained active router in a test-local FastAPI fixture with explicit test-only dependencies. This fixture must not change production composition.
6. Do not reactivate CloudPayments in normal `create_app()`. Do not create `create_app(enable_cloudpayments=True)`, an environment-only hidden activation switch, a second production composition root, or another runtime activation architecture solely for tests.
7. Do not change public non-CloudPayments API behavior.
8. Do not redesign PaymentProviderRegistry, checkout orchestration, transactions, persistence, or billing architecture.
9. Prefer test-only changes in this step unless the current branch materially violates the locked fail-closed state-creation invariant.

Implement only this step.
Do not perform broad repository research.
Inspect only directly relevant files and direct dependencies required to verify or edit the behavior.
Do not work on configuration, frontend, documentation, ANY-455, or later steps.
Format/lint changed Python code and run only the smallest focused tests/checks needed while implementing this step. Do not run broad API suites, repository-wide checks, generators, or browser suites; the human operator runs the complete verification block below.
Do not stage files and do not create commits.

After implementation:
- report every changed file;
- state the exact checkout failure behavior;
- state which persisted objects are proven not to be created;
- report the manual verification commands below.

If current code materially contradicts the expected ordering, stop and report the contradiction before changing architecture.
```

## Manual verification

From repository root:

```bash
./.venv/bin/python -m pytest \
  apps/api/tests/test_api.py \
  apps/api/tests/test_cloudpayments_deactivation.py \
  apps/api/tests/test_cloudpayments_adapter_api.py
```

Then, if the retained PostgreSQL webhook-processing test is still present and intentionally retained, run it using the repository's existing PostgreSQL test environment/configuration:

```bash
./.venv/bin/python -m pytest apps/api/tests/test_cloudpayments_webhook_postgres.py
```

If that suite requires PostgreSQL setup in the current worktree, use the repository-owned test DB setup described in `apps/api/AGENTS.md` before running it; do not create a separate `apps/api/.venv`.

## Expected completion

Default application tests now describe the deactivated runtime, while retained CloudPayments implementation tests no longer require CloudPayments to exist in normal production composition.

---

# Step 3 — Remove CloudPayments from supported runtime configuration and repository harness

**Status:** `todo`  
**Commit:** `chore(runtime): remove CloudPayments from supported configuration`

## Goal

Normal development, agent, and production runtime must no longer require, resolve, forward, or advertise CloudPayments configuration.

Retained provider code may still accept explicit optional credentials/configuration when directly exercised by retained provider-specific tests or explicit manual sandbox verification.

## Scope / affected code

Primary:

- `apps/api/app/core/settings.py`
- `docker-compose.yml`
- `docker-compose.agent.yml`
- `docker-compose.prod.yml`
- `.env.example`
- `.env.production.example`
- `scripts/repo.py`
- `scripts/cloudpayments_sandbox_verify.py`
- `.github/workflows/ci.yml`
- `apps/api/tests/support/settings.py`
- `apps/api/tests/conftest.py` only if directly required by the default test-environment cleanup
- `apps/api/tests/test_deployment_contract.py`
- `apps/api/tests/test_repository_docs.py`
- runtime/config sections of `README.md`

## Implementation decisions

### Settings

Remove:

```text
cloudpayments_enabled
```

from the required Settings contract.

Remove the validator that conditionally requires CloudPayments public ID/secret when enabled.

If the shared boolean parser remains needed only for SMTP, rename/adjust it cleanly rather than keeping CloudPayments terminology.

Retain optional CloudPayments fields required by retained direct adapter/client tests/manual sandbox work, including credentials/API tuning, unless current direct usage proves a specific field is dead and its removal is tiny and safe. Do not turn their presence into normal runtime activation.

### Compose

Remove CloudPayments public ID, secret, and enable flag from normal API environment blocks in development, agent, and production Compose.

### Repository harness and retained sandbox verifier

`write_runtime()` must no longer:

- resolve CloudPayments public ID;
- synthesize a CloudPayments secret;
- emit `CLOUDPAYMENTS_PUBLIC_ID`;
- emit `CLOUDPAYMENTS_API_SECRET`;
- emit `CLOUDPAYMENTS_ENABLED`.

Remove now-unused resolver helpers if they have no retained harness consumer.

The retained explicit `scripts/cloudpayments_sandbox_verify.py` may continue to require `CLOUDPAYMENTS_PUBLIC_ID` and `CLOUDPAYMENTS_API_SECRET` when the operator opts into manual sandbox verification, but it must not depend on the removed runtime activation flag. Remove its legacy:

```python
os.environ.setdefault("CLOUDPAYMENTS_ENABLED", "false")
```

Do not remove the sandbox verifier itself in ANY-457.

### Default API test environment

The shared default API test environment must represent the new normal deactivated runtime.

Remove CloudPayments activation/credential defaults from `apps/api/tests/support/settings.py`, including `CLOUDPAYMENTS_ENABLED`, `CLOUDPAYMENTS_PUBLIC_ID`, and `CLOUDPAYMENTS_API_SECRET`, when they are present only to make default application tests compose CloudPayments. Provider-specific retained tests must supply any CloudPayments credentials/configuration explicitly and locally.

Do not keep CloudPayments variables in the shared default test environment merely to preserve historical test assumptions. Default application tests must exercise the same deactivated composition used by normal runtime.

### CI runtime contract

Update `.github/workflows/ci.yml` so production/runtime jobs no longer publish `CLOUDPAYMENTS_ENABLED` or other CloudPayments activation values into the normal application environment or generated CI env file.

Do not remove browser-only CloudPayments stub variables in this step if the current browser suite still requires them before Step 5. Their removal belongs to Step 5 together with the E2E contract change.

### Env examples / README

Normal supported `.env` examples must not present CloudPayments credentials or an enable flag as required/supported runtime setup.

If retained sandbox verification still requires credentials, document that only as a clearly labelled **legacy/manual CloudPayments sandbox verification** concern, not as normal Portal startup configuration.

Do not automatically modify or delete secrets in an external deployment environment from repository code.

## AI Prompt

```text
Implement only Step 3 of ANY-457: remove CloudPayments from the supported normal runtime configuration and repository harness.

Steps 1-2 are complete. Normal FastAPI composition no longer initializes CloudPayments.

Relevant files:
- apps/api/app/core/settings.py
- docker-compose.yml
- docker-compose.agent.yml
- docker-compose.prod.yml
- .env.example
- .env.production.example
- scripts/repo.py
- scripts/cloudpayments_sandbox_verify.py
- .github/workflows/ci.yml
- apps/api/tests/support/settings.py
- apps/api/tests/conftest.py only if directly required by the default test-environment cleanup
- apps/api/tests/test_deployment_contract.py
- apps/api/tests/test_repository_docs.py
- README.md only for directly related runtime/configuration instructions

Required outcome:
1. Remove the required cloudpayments_enabled Settings field and the credential requirement tied to it.
2. Do not replace it with a new CloudPayments feature flag or generic provider feature framework.
3. Keep optional retained CloudPayments credential/API tuning settings only where retained direct adapter/client tests or explicit manual sandbox verification still need them; they must not activate normal runtime.
4. Remove CLOUDPAYMENTS_PUBLIC_ID, CLOUDPAYMENTS_API_SECRET and CLOUDPAYMENTS_ENABLED from the normal API environment in dev, agent and production Compose files.
5. Stop scripts/repo.py from resolving, synthesizing, or writing CloudPayments runtime values into .harness/runtime.env. Remove resolver helpers if they have no remaining harness consumer.
6. Remove the legacy `os.environ.setdefault("CLOUDPAYMENTS_ENABLED", "false")` from `scripts/cloudpayments_sandbox_verify.py`. Keep the explicit opt-in sandbox verifier and its direct public-id/secret inputs; they are not normal runtime configuration.
7. Remove CloudPayments variables from normal supported env examples. If sandbox verification still needs explicit variables, describe them only as legacy/manual sandbox input, not application startup requirements.
8. Remove CloudPayments activation/credential defaults from the shared API test environment so default app tests no longer receive CLOUDPAYMENTS_ENABLED, CLOUDPAYMENTS_PUBLIC_ID, or CLOUDPAYMENTS_API_SECRET implicitly. Provider-specific retained tests must configure any required values explicitly.
9. Update .github/workflows/ci.yml so production/runtime CI no longer forwards CLOUDPAYMENTS_ENABLED or other CloudPayments activation values as part of the normal runtime contract. Leave browser-only provider-stub variables for Step 5 if they are still needed by the pre-Step-5 browser suite.
10. Update focused deployment/repository-doc tests so they prove supported normal startup/config no longer depends on CloudPayments.
11. Preserve retained CloudPayments source code and provider-specific manual test ability.
12. Do not change database schema, payment-provider architecture, frontend behavior, or future billing contracts.

Implement only this step.
Do not perform broad repository research.
Inspect only directly relevant current files and direct dependencies needed to edit them.
Do not work on frontend, documentation architecture, ANY-455, or later steps.
Format/lint changed code where applicable and run only the smallest focused tests/checks needed while editing. Do not run broad API suites, repository-wide checks, generators, or browser suites; the human operator runs the complete verification block below.
Do not stage files and do not create commits.

After implementation:
- report every changed file;
- list every CloudPayments variable removed from normal runtime/harness configuration;
- state which optional retained settings remain and why;
- report the manual verification commands below.

If retained direct provider tests materially require a normal-runtime setting that this step would remove, stop and report the exact dependency instead of inventing a feature flag.
```

## Manual verification

From repository root:

```bash
./.venv/bin/python -m pytest \
  apps/api/tests/test_deployment_contract.py \
  apps/api/tests/test_repository_docs.py
npm run repo:doctor
```

## Expected completion

Supported Portal startup/harness/Compose configuration no longer contains a CloudPayments activation contract or requires CloudPayments credentials.

---

# Step 4 — Make frontend checkout explicitly unavailable and stop all payment preparation

**Status:** `todo`  
**Commit:** `feat(web): show checkout unavailable without CloudPayments`

## Goal

Remove CloudPayments from active browser checkout runtime while retaining its implementation source temporarily. The checkout page must deliberately show an unavailable state and must not start any payment preparation flow.

## Scope / affected code

Primary:

- `apps/web/src/features/checkout/provider-adapters.ts`
- `apps/web/src/features/checkout/CheckoutClient.tsx`
- `apps/web/src/app/ru/auth-checkout/page.tsx` only if a tiny composition adjustment is required
- `apps/web/tests/components/CheckoutClient.test.tsx`

Retain unless later cleanup proves otherwise:

- `cloudPaymentsCheckoutAdapter` implementation;
- `cloudpayments.d.ts`;
- provider-neutral checkout types.

## Implementation decisions

### Adapter registration

Normal registered checkout adapters become empty.

Do not delete the CloudPayments adapter implementation solely because it is no longer registered.

With zero required adapters, the existing page-level adapter status should resolve to:

```text
disabled
```

and no CloudPayments `<Script>` should be rendered.

### Checkout client

Treat `disabled` as a first-class terminal blocked state, distinct from temporary `loading`/`failed` widget states.

Required behavior:

- visible neutral temporary-unavailable message;
- payment CTA disabled or guaranteed to short-circuit;
- `goToPaymentResult()` must return before POST `/api/auth/checkout-intent`;
- no checkout result is written to session storage;
- no checkout adapter is resolved or started;
- no CloudPayments widget/runtime is referenced during the payment action;
- stale missing-document continuation must not POST new payment-continuation acceptances while checkout is disabled.

Preserve unrelated auth/login/register/catalog/account/ownership rendering. Do not remove the checkout page or replace it with a future billing UX.

Do not add provider selection, redirect checkout, fake success, waitlist, billing vendor branding, or another product-flow redesign.

## Tests

Add focused component coverage proving:

- disabled state renders the unavailable message;
- payment action cannot initiate `/api/auth/checkout-intent`;
- CloudPayments adapter `start()` is not called;
- disabled state does not transition into widget loading/error messaging;
- stale payment-document continuation cannot proceed as a payment continuation while disabled;
- existing non-payment auth/catalog rendering remains usable where current tests cover it.

## AI Prompt

```text
Implement only Step 4 of ANY-457: deactivate CloudPayments in the normal frontend checkout runtime and make checkout deliberately unavailable.

Backend/runtime deactivation and configuration cleanup are already complete.

Relevant files:
- apps/web/src/features/checkout/provider-adapters.ts
- apps/web/src/features/checkout/CheckoutClient.tsx
- apps/web/src/app/ru/auth-checkout/page.tsx only if required by the minimal composition change
- apps/web/tests/components/CheckoutClient.test.tsx

Required outcome:
1. The normal checkout adapter registry must contain no active CloudPayments adapter.
2. Retain the CloudPayments adapter implementation and type declarations unless a tiny removal is strictly required; this ticket does not physically delete broad provider code.
3. With no registered required adapter, the checkout page must not render the CloudPayments script.
4. Treat checkoutAdapterStatus === "disabled" as an explicit terminal unavailable state.
5. Show neutral Russian copy such as "Оплата временно недоступна. Попробуйте позже." and use a disabled/unavailable payment action.
6. goToPaymentResult() must short-circuit before POST /api/auth/checkout-intent when checkout is disabled.
7. Do not write payment-result session storage, resolve/start an adapter, or attempt any provider action while disabled.
8. Ensure a stale missing-document payment-continuation state cannot call /api/legal/acceptances and continue payment while checkout is disabled.
9. Preserve auth, registration, session, catalog, ownership and account behavior unrelated to starting payment.
10. Do not add a replacement provider, fake checkout, redirect flow, feature flag, provider chooser, or speculative future billing UX.
11. Do not broadly remove CloudPayments-specific helper code that has merely become unreachable; physical cleanup is later work.
12. Add focused component tests for the disabled state and absence of checkout/payment-preparation requests.

Implement only this step.
Do not perform broad repository research.
Inspect only directly relevant current files and direct dependencies needed to edit them.
Do not work on browser E2E, docs, ANY-455, or later steps.
Format/lint changed frontend code and run only the smallest focused component tests/checks needed while implementing this step. Do not run broad frontend suites, full type/build gates, Playwright/browser suites, or repository-wide checks; the human operator runs the complete verification block below.
Do not stage files and do not create commits.

After implementation:
- report every changed file;
- summarize the exact disabled UX;
- confirm that /api/auth/checkout-intent and payment-continuation legal acceptance are not initiated from the disabled checkout path;
- report the manual verification commands below.

If the existing component structure makes the locked disabled behavior impossible without a broader frontend redesign, stop and report the exact contradiction instead of redesigning the feature.
```

## Manual verification

From repository root:

```bash
npm --workspace @anytoolai/web run test:components -- \
  tests/components/CheckoutClient.test.tsx
npm run typecheck:web
```

## Expected completion

Browser checkout contains no active CloudPayments adapter/script and does not create new checkout intent/state while payments are deliberately unavailable.

---

# Step 5 — Replace active CloudPayments browser E2E with the deactivated checkout contract

**Status:** `todo`  
**Commit:** `test(e2e): cover unavailable checkout without CloudPayments`

## Goal

Make browser-level acceptance coverage represent the supported runtime after ANY-457 instead of keeping an E2E-only active CloudPayments path alive.

## Scope / affected code

Primary:

- existing `apps/web/e2e/checkout-webhook.spec.ts`
- new/replacement `apps/web/e2e/checkout-unavailable.spec.ts`
- `apps/web/e2e/react-runtime.spec.ts`
- `apps/web/e2e/provider-ui-stub.ts` only if it becomes unused
- `.github/workflows/ci.yml`
- direct E2E helpers required by the selected scenarios

## Implementation decisions

Remove active browser E2E assumptions that require:

- CloudPayments widget script stubbing;
- CloudPayments HMAC secret setup;
- active CloudPayments checkout;
- browser-driven CloudPayments webhook completion.

Do not create an E2E-only flag or runtime seam to reactivate CloudPayments.

The replacement E2E should prove the supported product contract:

- checkout page renders;
- selected product/catalog/auth flow needed to reach the checkout surface still works;
- explicit unavailable payment state is shown;
- payment action cannot initiate checkout;
- no request is made to `widget.cloudpayments.ru`;
- no request is made to `/api/auth/checkout-intent` from the disabled payment path.

If the old E2E contains valuable provider-neutral scenarios, move only those scenarios to an appropriate provider-neutral test without retaining CloudPayments setup.

`apps/web/e2e/react-runtime.spec.ts` is part of this step because it currently installs the provider UI stub and expects the checkout payment button to be enabled. Update that test to represent the deactivated runtime: keep its provider-neutral React/runtime, auth, catalog, account, accessibility, and visual-evidence assertions, but remove CloudPayments stub activation and assert the deliberate checkout-unavailable state instead of an enabled payment action.

After no browser test requires the CloudPayments provider UI stub, remove `PLAYWRIGHT_PROVIDER_UI_STUB` and `CLOUDPAYMENTS_PUBLIC_ID` from the browser job in `.github/workflows/ci.yml`. Delete `provider-ui-stub.ts` only if it has no remaining consumer after both the checkout E2E and `react-runtime.spec.ts` are updated.

CloudPayments callback routing is absent from normal backend runtime and does not need browser E2E coverage.

## AI Prompt

```text
Implement only Step 5 of ANY-457: replace the active CloudPayments browser E2E contract with the supported checkout-unavailable contract.

Frontend Step 4 is complete. Normal checkout has no registered CloudPayments adapter and is deliberately disabled.

Relevant files:
- apps/web/e2e/checkout-webhook.spec.ts
- create/rename to apps/web/e2e/checkout-unavailable.spec.ts
- apps/web/e2e/react-runtime.spec.ts
- apps/web/e2e/provider-ui-stub.ts only if it becomes unused
- .github/workflows/ci.yml
- directly required E2E helpers only

Required outcome:
1. Remove browser E2E setup whose purpose is to activate/stub the CloudPayments widget, CloudPayments HMAC flow, or active CloudPayments payment completion.
2. Do not add a test-only runtime flag, hidden adapter registration, or alternate production composition to keep the old flow alive.
3. Add browser coverage proving the checkout page shows the deliberate unavailable state.
4. Prove the disabled payment path does not request /api/auth/checkout-intent.
5. Prove the page does not request https://widget.cloudpayments.ru/... in normal runtime.
6. Preserve provider-neutral auth/catalog/ownership behavior from the old spec only when it remains valuable and does not require CloudPayments setup.
7. Update apps/web/e2e/react-runtime.spec.ts: remove provider UI stub activation, stop expecting an enabled "Pay" action, preserve provider-neutral runtime/auth/catalog/account/accessibility/visual assertions, and assert the new checkout-unavailable state.
8. Once no browser test needs CloudPayments activation, remove PLAYWRIGHT_PROVIDER_UI_STUB and CLOUDPAYMENTS_PUBLIC_ID from the browser job in .github/workflows/ci.yml.
9. Delete provider-ui-stub.ts only if it has no remaining consumer after all affected E2E files are updated.
10. Do not recreate or test a CloudPayments callback compatibility surface through the browser; normal backend runtime does not expose one.
11. Do not introduce replacement billing behavior or future provider assumptions.

Implement only this step.
Do not perform broad repository research.
Inspect only directly relevant E2E files and helpers.
Do not work on docs, generated files, ANY-455, or future billing work.
Format/lint changed frontend code and run only lightweight focused checks needed while editing. Do not run the full Playwright/browser suite or broad build/repository checks; the human operator runs the complete E2E verification below.
Do not stage files and do not create commits.

After implementation:
- report every changed/deleted file;
- list the browser scenarios retained/replaced;
- confirm no E2E-only CloudPayments activation seam was introduced;
- report the manual verification command below.

If an old scenario is actually provider-neutral but coupled to the CloudPayments stub, preserve its business assertion without preserving the provider activation mechanism.
```

## Manual verification

From repository root:

```bash
npm run test:e2e -- apps/web/e2e/checkout-unavailable.spec.ts
npm run test:e2e:react-runtime
```

Confirm the browser CI job no longer exports `PLAYWRIGHT_PROVIDER_UI_STUB` or `CLOUDPAYMENTS_PUBLIC_ID` after no remaining E2E consumer needs them.

## Expected completion

Browser E2E now proves the supported deactivated checkout contract, the React-runtime journey reflects the same unavailable checkout state, and CI no longer keeps an artificial active CloudPayments runtime alive for tests.

---

# Step 6 — Update sources of truth, generated API contract, and run final verification

**Status:** `todo`  
**Commit:** `docs: document CloudPayments runtime deactivation`

## Goal

Make CURRENT/TARGET/TRANSITIONAL documentation and agent guidance match the runtime implemented by Steps 1-5, then regenerate/check derived API artifacts and perform final ticket verification.

## Scope / affected code

Authoritative/current docs:

- `AGENTS.md`
- `apps/api/AGENTS.md`
- `README.md`
- `ARCHITECTURE.md`
- `docs/PRODUCT.md`
- `docs/product/ru-mvp.md`
- `docs/architecture/payment-providers.md`
- `docs/architecture/billing-authority.md`
- `docs/SECURITY.md`
- `docs/RELIABILITY.md` only if its current wording explicitly claims active CloudPayments runtime/webhook behavior

Generated artifact after manual generation:

- `docs/generated/openapi.json`

Do not edit accepted ADR history merely to describe the new current state.

## Documentation decisions

Record unambiguously:

### CURRENT

- normal backend runtime does not initialize/register/use CloudPayments;
- normal frontend checkout does not load/invoke CloudPayments;
- checkout is temporarily unavailable until a separately selected/implemented billing integration exists;
- generic checkout API fails closed when no direct provider is registered;
- normal FastAPI runtime does not expose the CloudPayments callback path at all; the retained active router exists only as unreachable legacy source code;
- CloudPayments credentials are not normal startup/runtime configuration.

### TRANSITIONAL / RETAINED

- CloudPayments source code, persistence schema/migrations, and any local development/test records remain temporarily;
- retained code must not be treated as active product architecture;
- retained CloudPayments persistence must not be generalized during ANY-455 solely for cleanup;
- a later evidence-based cleanup/decommission may physically remove provider-only code/data dependencies when safe.

### TARGET

- future external billing remains a separate integration boundary;
- it is not another `PaymentProviderAdapter`;
- its webhook, REST, checkout, reconciliation and authoritative-state contracts are defined only by the future selected integration ticket;
- ANY-457 does not select LBX, Dodo, or another vendor.

### Agent guidance

Update root `AGENTS.md` and `apps/api/AGENTS.md` so future AI agents do not read stale statements such as:

```text
CloudPayments is the current active direct-provider integration
Current CloudPayments supplies authoritative facts through verified webhooks
```

Replace them with the deactivated retained state and the future external-billing distinction.

Do not modify `apps/web/AGENTS.md` unless current post-Step-5 content contains a concrete stale CloudPayments runtime statement.

### Security source of truth

Update `docs/SECURITY.md` so it no longer describes CloudPayments signature verification as part of the current active `ru` runtime. Preserve the general security invariant that any future active external billing/payment integration must authenticate and validate authoritative external facts before trusting them. The retained CloudPayments router is not mounted in normal runtime and therefore is not a current billing-fact processing path.

## Generated API contract

Do not hand-edit `docs/generated/openapi.json`.

After source/docs changes are complete, the human operator runs generation. The resulting OpenAPI must no longer expose `/api/cloudpayments/{endpoint}` because the route is not part of normal application composition.

## AI Prompt

```text
Implement only Step 6 of ANY-457: update authoritative documentation and agent guidance to match the completed CloudPayments runtime deactivation.

Steps 1-5 are complete. Do not change runtime behavior in this step.

Relevant files:
- AGENTS.md
- apps/api/AGENTS.md
- README.md
- ARCHITECTURE.md
- docs/PRODUCT.md
- docs/product/ru-mvp.md
- docs/architecture/payment-providers.md
- docs/architecture/billing-authority.md
- docs/SECURITY.md
- docs/RELIABILITY.md only if its current text explicitly presents CloudPayments runtime/webhooks as active

Required documentation state:
1. CURRENT: normal backend/frontend runtime does not initialize, register, load or invoke CloudPayments.
2. CURRENT: checkout is deliberately temporarily unavailable until a separately selected/implemented billing integration exists.
3. CURRENT: generic checkout fails closed when no direct payment provider is registered.
4. CURRENT: normal application routing does not expose /api/cloudpayments/{endpoint}; do not create a deprecated compatibility callback.
5. TRANSITIONAL: CloudPayments implementation, persistence schema/migrations, and local development/test records may remain for later persistence/dead-code analysis and physical cleanup.
6. TARGET: future external billing is a distinct architecture boundary and is not another PaymentProviderAdapter. Do not select or design LBX, Dodo, or another vendor here.
7. ANY-455 follows ANY-457 and must evaluate active generic persistence separately from retained legacy CloudPayments persistence/schema that has no normal runtime consumer.
8. Update root AGENTS.md and apps/api/AGENTS.md so future AI agents are not told that CloudPayments or its verified webhooks are the current active payment path.
9. Update docs/SECURITY.md so it no longer describes CloudPayments signature verification as part of the current active ru runtime. Preserve the general security invariant that any future active external billing/payment integration must authenticate and validate authoritative external facts before trusting them. The retained CloudPayments router is not mounted and is not a current billing-fact processing path.
10. Preserve the accepted architecture direction and ADR history. Do not create or rewrite an ADR for this transitional runtime change unless an existing repository rule explicitly requires one.
11. Do not hand-edit docs/generated/openapi.json or any other generated file. The human operator will run npm run generate after this step.
12. Do not perform unrelated docs cleanup.

Implement only this step.
Do not perform broad repository research.
Inspect only directly relevant authoritative documents and direct references required to make them internally consistent.
Do not change runtime code, tests, ANY-455 implementation, or future billing code.
Run only lightweight focused checks needed to validate edited source/documentation, without regenerating derived artifacts. Do not run generators, broad tests, docs checks, architecture checks, browser suites, or repository-wide verification; the human operator runs the complete generation/verification block below.
Do not stage files and do not create commits.

After implementation:
- report every changed file;
- summarize CURRENT / TRANSITIONAL / TARGET wording;
- identify any source-of-truth document you intentionally left unchanged and why;
- remind me to run the exact manual generation/verification commands below.

If two accepted authoritative documents materially contradict the locked ANY-407/ANY-457 state, stop and report the conflict instead of silently redefining the architecture.
```

## Manual generation and verification

From repository root:

```bash
npm run generate
npm run generate:check
npm run docs:check
npm run architecture:check
```

Review the generated OpenAPI diff. Confirm `/api/cloudpayments/{endpoint}` is absent from the normal generated API contract and no generated artifact was manually edited.

Then run the canonical repository verification:

```bash
npm run check
```

Finally run the full supported browser contracts:

```bash
npm run test:e2e
npm run test:e2e:react-runtime
```

If PostgreSQL-backed retained CloudPayments tests are part of the final local environment and were not already run in Step 2, run the appropriate existing PostgreSQL test command before merge.

## Expected completion

Repository source of truth and generated API contract describe exactly one current state: CloudPayments is deactivated and unreachable in normal runtime, its implementation/schema are retained only for later cleanup, and future external billing remains a separate not-yet-selected integration.

---

# 4. Post-Merge Handoff to ANY-455

After ANY-457 is merged:

1. Rebase/create the ANY-455 implementation branch from the new `main`.
2. Revalidate the existing `ANY-455-implementation-plan.md` against the new codebase.
3. Update the plan's source-of-truth/baseline section so it includes completed ANY-457.
4. Replace stale language that describes CloudPayments runtime deactivation as future work.
5. For every persistence change proposed by the old ANY-455 plan, ask:

   ```text
   Is this persistence used by active Payment Portal runtime after ANY-457?
       yes -> evaluate under ANY-455
       no  -> do not refactor it merely for cleanliness;
              classify it as retained legacy persistence/schema or later CloudPayments cleanup
   ```

6. Do not implement any ANY-455 correction inside the ANY-457 branch.

---

# 5. Final Acceptance Mapping

| ANY-457 acceptance area | Plan coverage |
| --- | --- |
| CloudPayments not initialized in backend runtime | Step 1 |
| CloudPayments API client not required | Step 1 + Step 3 |
| No active CloudPayments provider registration | Step 1 |
| Normal checkout cannot perform provider work | Step 1 + Step 2 |
| Failed checkout creates no new provider-backed commercial state | Step 2 |
| CloudPayments webhook/API route is absent from normal runtime | Step 1 |
| Generated OpenAPI no longer exposes CloudPayments callback path | Step 6/OpenAPI |
| Frontend does not load widget | Step 4 + Step 5 |
| Frontend does not call checkout-intent while disabled | Step 4 + Step 5 |
| Normal runtime does not require CloudPayments credentials | Step 3 |
| Default API tests do not receive implicit CloudPayments activation/credential config | Step 3 |
| React-runtime E2E reflects the checkout-unavailable state | Step 5 |
| Browser CI no longer enables CloudPayments provider UI stubs/config | Step 5 |
| CloudPayments persistence schema/code is not physically cleaned up in this ticket | Locked Decision 2.9; no migrations/deletions |
| Generic billing/subscription/entitlement behavior retained | All steps; explicitly out of scope |
| CloudPayments source retained for later evidence-based cleanup | Locked Decision 2.1 |
| Agent documentation no longer claims CloudPayments is active | Step 6 |
| Security source of truth no longer describes CloudPayments signature verification as part of current active runtime | Step 6 |
| Future billing is not modeled as PaymentProviderAdapter | Locked Decision 2.2 + Step 6 |
| ANY-455 starts from deactivated runtime baseline | Post-Merge Handoff |

---

# 6. Explicit Out of Scope

Do not include any of the following in ANY-457:

- physical deletion of all CloudPayments source code;
- deletion or destructive migration/cleanup of CloudPayments provider/payment/subscription/webhook persistence structures;
- deletion/redesign of generic `Payment`, `Order`, `Subscription`, `Entitlement`, legal, identity, catalog, or audit behavior because CloudPayments used it;
- broad cleanup of CloudPayments-only query/persistence modules;
- persistence-boundary refactoring owned by ANY-455;
- transaction ownership, commit/rollback, idempotency, concurrency, lock-order, outbox/inbox or reconciliation redesign owned by the next ANY-407 step;
- broad FastAPI DI/composition redesign owned by a later ANY-407 step;
- business/domain state-machine decomposition;
- new billing provider selection or integration;
- LBX or Dodo implementation;
- generic `BillingSystemAdapter`;
- expansion of `PaymentProviderAdapter` for future external billing;
- generic provider feature-flag framework;
- hidden test-only active CloudPayments composition;
- fake frontend payment success;
- speculative redirect/hosted checkout UX;
- unrelated observability/error/persistence/frontend cleanup.

---

# 7. Final Plan Validation

This plan is implementation-ready for the current repository baseline and the updated Linear sequence.

The key design is intentionally small:

```text
CloudPayments active runtime
        ↓
ANY-457
        ↓
CloudPayments deactivated retained integration
        ↓
ANY-455 works only on persistence that still matters to active Portal runtime
        ↓
later evidence-based CloudPayments physical cleanup
```

The plan deliberately does **not** build the future billing architecture. It removes the obsolete active provider dependency first so subsequent ANY-407 architecture work is performed against the runtime Payment Portal actually intends to keep.

The most important invariants during implementation are:

1. no normal backend startup can initialize a CloudPayments adapter/client;
2. no normal browser checkout can load/start CloudPayments or create a checkout intent while payments are disabled;
3. normal application routing exposes no CloudPayments webhook/API path;
4. no compatibility/deprecated CloudPayments callback is invented for hypothetical production traffic;
5. retained CloudPayments implementation and persistence schema are not physically cleaned up in this ticket;
6. no new feature flag/provider/future-billing abstraction is invented;
7. ANY-455 is revalidated only after ANY-457 is merged.
