# ANY-411 — Establish Architecture Direction & Authority ADR — Implementation Plan

## Plan Overview

| Field | Value |
| --- | --- |
| Parent | `ANY-407` |
| Ticket | `ANY-411` |
| Ticket type | `type:chore` |
| Current base | current `main` after `ANY-326` and `ANY-327` |
| Research status | complete |
| Plan status | implementation-ready |
| ANY-411 deliverable | research result + sequential implementation of Steps 1–4 |
| Production runtime changes in ANY-411 | none |
| ADR/doc/test changes in ANY-411 | required by Steps 1–4 |
| Database migration | not required |
| Public API change | not required |
| OpenAPI change | not required |
| Runtime behavior change | not required |
| Planned implementation steps | 4 |
| Execution order | Step 1 → manual verification → human commit → Step 2 → manual verification → human commit → Step 3 → manual verification → human commit → Step 4 → final verification → human commit |
| Implementation ownership | `ANY-411` |

## How to Use This Plan

1. This file is the execution plan for `ANY-411`. The ticket is complete only after Steps 1–4 and final verification are complete.
2. Execute Steps 1–4 sequentially under `ANY-411`; no additional implementation child-ticket or ownership gate is required.
3. Give the execution AI only one step at a time: first ask it to execute Step 1, review the result, then proceed to Step 2, and so on.
4. The execution AI must use the locked decisions in this plan and must not repeat the broad repository/architecture research already completed here.
5. The execution AI must implement only the files and responsibilities explicitly owned by the current step and must not pull later `ANY-407` work forward.
6. After every step:
   - review the diff;
   - run the listed verification commands manually;
   - create the commit yourself;
   - only then continue to the next step.
7. The execution AI must not run verification commands, stage files, or create commits; it reports the exact commands for you to run manually.
8. Repository engineering documentation created by these steps remains **English**, even though this implementation plan is written in Russian.

---

# Research Result

## 1. Current source of truth

The following already accepted decisions must be treated as locked:

- ADR-0001 remains authoritative for **one-contour-per-production-instance**, contour isolation and Region Resolver separation. Its assumption that every contour is represented by a `PaymentProviderAdapter` is the part that must be amended, not the contour architecture itself. 
- ADR-0002 remains authoritative for checkout:
  - exact persisted `Plan.id` is purchase identity;
  - `all_access` is internal access scope;
  - `all-access` is not purchase authority;
  - external/provider identifiers are opaque;
  - entrypoint fields are provenance only. 
- ADR-0003 / ANY-326 remains authoritative for persistence:
  - `app.models` owns the canonical persisted model contract;
  - confirmed closed persisted vocabularies are canonical Python enums;
  - physical PostgreSQL representation remains `TEXT`/`VARCHAR`;
  - provider vocabularies remain separate from local model vocabularies. 
- Platform Kernel consumes local entitlements and does not consume external billing state directly. 

ANY-326 is already `Done`, so this work must not recreate enum/model ownership work. ANY-327 is also `Done` and already establishes exact `Plan.id` purchase identity. 
---

## 2. Main documentation contradiction

The current architecture documentation still models this as the general architecture:

```text
Payment Portal
    ↓
PaymentProviderAdapter
    ↓
contour payment provider
```

That accurately describes the **current direct CloudPayments flow**, but no longer describes the target architecture for an external billing system.

The contradiction appears in several authoritative places:

- `ARCHITECTURE.md` presents the contour payment provider as the general payment boundary and describes registered provider adapters as the normal abstraction. 
- `payment-providers.md` says a payment provider is an adapter registered for the local contour and currently projects future `eu`/`us` contours through more adapters. 
- ADR-0001 says every contour registers its own payment-provider adapter. 
- `contours.md` makes adapter registration and `payment_provider_accounts` part of the generic contour-enablement checklist. 
- `payment-portal-data-model.md` states Portal ownership of orders/payments/subscriptions without distinguishing authoritative Portal-managed state from an external system's authoritative lifecycle and local projections. 
- `PRODUCT.md` similarly describes future contours in terms of provider adapters. 

The target model must instead support two distinct flows:

```text
Portal-managed billing flow
Payment Portal
    ↓
PaymentProviderAdapter
    ↓
payment provider
```

and:

```text
External-billing-managed flow
Payment Portal Application
    ↓ command
external billing system
    ↓ authoritative webhook / reconciliation
normalized local projections
    ↓
Portal entitlement rules
    ↓
local entitlements
```

An external billing system is **not** another implementation of `PaymentProviderAdapter`.

---

## 3. Authority matrix

The following ownership must be fixed as the normative rule.

| Concern | Authority |
| --- | --- |
| Anytool user identity | Payment Portal |
| Catalog / Product / Plan semantics | Payment Portal |
| Exact purchase identity | Payment Portal `Plan.id` |
| Local entitlement rules | Payment Portal |
| Local entitlements | Payment Portal |
| Runtime access decision | Payment Portal entitlements consumed by Platform Kernel |
| Workflow execution / usage consumption | Platform Kernel |
| Direct CloudPayments orchestration | Payment Portal, while the transitional Portal-managed flow exists |
| External customer lifecycle | external billing system |
| External invoice lifecycle | external billing system |
| External payment lifecycle | external billing system |
| External subscription lifecycle | external billing system |
| Local `Order`/`Payment`/`Subscription` under external billing | normalized projections used by Payment Portal |
| Vendor HTTP schema/status vocabulary | owning Integration only |

For an externally managed subscription:

```text
external billing state
        ↓
verified fact
        ↓
normalized Payment Portal transition
        ↓
local Order / Payment / Subscription projection
        ↓
Payment Portal entitlement rules
        ↓
local entitlement
```

The external system does not write entitlements and Platform Kernel does not query the external system.

---

## 4. Billing ownership invariant

The durable invariant is:

```text
one subscription → one billing owner
```

Conceptually the owner is either:

```text
Portal-managed
```

or:

```text
external billing system X
```

ANY-411 must **not** choose the eventual database representation.

Do not introduce yet:

- `billing_owner` column;
- owner enum;
- external subscription table;
- generic external customer table;
- `BillingSystemAdapter`;
- provider capability hierarchy.

Those belong to later ANY-407 implementation stages after the concrete integration requirements are known.

---

## 5. Authoritative billing facts

An outbound command is not confirmation of a billing state transition.

Target external flow:

```text
1. Persist/find local idempotent operation
2. Commit local intent
3. Send external command
4. Persist external command result/mapping
5. Commit
6. Wait for verified authoritative fact
   or reconcile after uncertain/missing delivery
7. Apply the same local transition path
8. Recalculate affected entitlements
```

Therefore:

```text
external REST 200
!= confirmed payment
!= confirmed subscription activation
!= entitlement activation
```

Verified webhook is the primary asynchronous fact.

Reconciliation is a recovery path for the same authoritative lifecycle and must converge through the same local transition logic.

There must not be:

```text
webhook state machine
+
reconciliation state machine
```

and there must not be:

```text
last-write-wins
```

for conflicting billing facts.

A stale or conflicting fact must be rejected/ignored according to transition rules or trigger reconciliation rather than blindly overwriting newer confirmed local state.

---

## 6. Identity and correlation rules

Billing correlation must never rely on email alone.

Preferred evidence is conceptually:

```text
local operation/order ↔ known external invoice/subscription mapping
        ↓
known external customer mapping
        ↓
previously recorded internal UUID carried in a verified external payload
```

An internal UUID arriving from an external webhook is correlation evidence only after authenticity and context validation; its mere presence does not prove identity.

Email may be customer/contact data but is not a billing identity key.

This matters immediately because current direct CloudPayments checkout still passes:

```python
account_id=user.email
```

to the adapter. That is current CloudPayments legacy behavior and must be explicitly marked **TRANSITIONAL**, not copied into an external-billing design. 

Changing this runtime behavior is not part of this architecture step.

---

# Logical Layer Model

## 7. Responsibility and dependency matrix

### Presentation

Owns:

- HTTP/webhook/CLI/job entrypoints;
- FastAPI request/response contracts;
- authentication context;
- external request decoding;
- presentation-level error mapping;
- FastAPI dependency declaration;
- invoking an Application use case.

Must not own:

- billing lifecycle state machines;
- arbitrary ORM mutations;
- transaction orchestration;
- concrete external billing workflows;
- provider-specific business decisions.

Target direction:

```text
Presentation → Application
```

---

### Application

Owns:

- use cases;
- commands and queries;
- orchestration;
- transaction boundaries;
- idempotent operations;
- consistency/recovery orchestration;
- calls to persistence/integration capabilities;
- normalized internal command/result contracts.

May depend on:

```text
Domain
internal contracts
persistence ports/capabilities
integration ports/capabilities
```

Must not depend on:

- FastAPI;
- routers;
- raw provider payloads;
- LBX/Dodo/CloudPayments DTOs;
- vendor status strings.

---

### Domain

Owns:

- business invariants;
- valid transition semantics;
- entitlement rules;
- decisions independent of transport and vendor protocol.

Must not depend on:

- FastAPI;
- HTTP;
- provider SDK/client;
- vendor schemas;
- SQLAlchemy `Session`;
- logging/monitoring SDKs.

`app.models` remains the canonical persisted model contract established by ADR-0003. Step 1 does **not** introduce a second "pure domain entity" model beside it.

---

### Persistence / Infrastructure

Owns:

- SQLAlchemy queries;
- loading/saving;
- locking;
- persistence-specific mechanics.

Must not decide:

- payment lifecycle semantics;
- entitlement semantics;
- billing ownership rules.

Target direction is capability implementation for Application, not:

```text
Domain → SQL queries
```

---

### Integrations

Owns:

- external protocol details;
- HTTP clients;
- authentication/signature verification;
- raw payload parsing;
- redaction;
- provider/vendor DTOs;
- mapping external states into normalized internal contracts;
- mapping Application commands into vendor requests.

Must not own:

- a second local business state machine;
- arbitrary local ORM mutation;
- entitlement decisions.

---

### Core

Owns:

- settings/configuration;
- database/session factories;
- logging;
- tracing/metrics infrastructure;
- generic security helpers;
- time and infrastructure utilities.

Must not become:

```text
shared business logic
```

and must not depend inward on billing domains or integrations.

---

### Composition / Wiring

Owns:

- constructing concrete adapters/clients;
- application startup/shutdown;
- binding concrete implementations to required capabilities;
- FastAPI composition.

May see concrete modules because this is where dependency inversion closes.

It must not become a deep runtime service locator.

---

## 8. Dependency direction

Normative logical direction:

```text
Presentation
    ↓
Application
    ↓
Domain
```

Application may call abstract/currently named capabilities implemented by:

```text
Persistence
Integrations
```

Composition wires concrete implementations.

Forbidden directions include:

```text
Domain → Integrations
Application → FastAPI
Application → vendor DTO
Domain → vendor status
Persistence → external HTTP
Integration → Domain router
Core → Domain/Integration business dependency
```

No new package hierarchy has to be created merely to make the filesystem resemble this diagram.

---

# Current Package Mapping

## 9. Already-correct or useful boundaries

### `app.main`

Current composition root:

- builds `CloudPaymentsAdapter`;
- builds/registers `PaymentProviderRegistry`;
- wires routers;
- owns application lifespan.

That is legitimately Composition/Wiring. 

The current `app.state` mechanism may remain as transitional wiring in Step 1. Replacing it with another DI architecture belongs to later work.

---

### `app.models`

Canonical persisted model contract from ANY-326 / ADR-0003.

Do not move or duplicate it.

---

### `app.infrastructure.queries`

Already represents useful persistence extraction for repeated/query-specific access.

It does **not** imply that every table needs a repository.

The current architecture rule remains:

```text
extract persistence boundaries where they isolate real persistence complexity
or establish a required application boundary
```

not:

```text
one repository per ORM model
```

---

### `app.integrations.cloudpayments`

The adapter/client side already performs important external-boundary work:

```text
raw request
→ parse
→ signature verification
→ redaction
→ Pydantic validation / normalization
```

before a valid provider event reaches business processing.  

This trust-boundary behavior should be retained.

---

### Existing architecture guards

Current AST checks already reject important reverse dependencies, including:

- `core → domains/integrations`;
- `domain → integration`;
- domain service/model → router;
- integration → domain router;
- router → router;
- CloudPayments-specific literals in provider-neutral billing modules.  

ANY-326 also added guards around canonical persisted model/enums. 

These guards are useful and must not be replaced.

---

# Transitional Exceptions

## 10. `integrations/cloudpayments/processing.py`

Current CloudPayments processing both:

- interprets provider input;
- performs SQLAlchemy queries;
- directly mutates `Order` and `Payment`;
- invokes subscription lifecycle transitions.

For example, the module contains direct payment/order state changes before invoking `activate_paid_period()` or `apply_refund()`.  

This contradicts the target Integration boundary, but it is **known transitional debt**.

Step 1 documents it.

Step 1 does not move it.

The later projection-transition stage of ANY-407 owns removal of this duplicate mutation responsibility.

---

## 11. Checkout in `domains/identity/router.py`

Current checkout performs significant orchestration inside an HTTP router and directly resolves:

- persisted plans;
- legal state;
- provider account;
- provider adapter;
- order/session persistence.

It also sends `user.email` as CloudPayments `account_id`.  

That is current/transitional structure, not the target Application boundary.

Step 1 documents the exception and does not refactor it.

---

## 12. `app.payment_providers`

The current `PaymentProviderAdapter` contains checkout, transaction lookup, refund and recurring-subscription operations. 

Its future meaning is explicitly narrowed to:

```text
Portal-managed direct payment-provider flow
```

It is **not** renamed into or generalized as:

```text
BillingSystemAdapter
```

and LBX/Dodo/another external billing system must not be registered in `PaymentProviderRegistry` merely because an external integration is required.

Concrete external-billing capability boundaries are introduced later only when there is an actual consumer.

---

# Trust Boundary

Normative flow:

```text
untrusted HTTP/vendor input
        ↓
authentication / authenticity verification
        ↓
schema validation / decoding
        ↓
redaction where necessary
        ↓
normalization into typed internal contract
        ↓
Application
        ↓
Domain transition
```

Rules:

- raw provider/vendor `dict[str, Any]` stays at the external edge;
- Application and Domain do not consume raw external payloads;
- vendor status strings are mapped before Application/Domain logic;
- signature verification precedes trusting billing facts;
- raw sensitive payloads do not enter logs/traces;
- browser return URLs remain informational;
- an external command result is not final payment authority.

Current CloudPayments already implements much of the verification/redaction/normalization boundary and that behavior must remain intact.  

---

# Current / Target / Transitional terminology

Every affected architecture document should distinguish these explicitly.

### CURRENT

What exists in `main` today.

Example:

```text
ru Payment Portal
→ CloudPayments widget / direct provider API
→ CloudPayments verified webhook
→ local billing lifecycle
```

### TARGET

Durable architecture future integrations must respect.

Example:

```text
external billing owns external lifecycle
→ Portal stores normalized local projection
→ Portal derives local entitlements
```

### TRANSITIONAL

Current behavior that is allowed to remain temporarily but must not be copied as target architecture.

Examples:

- broad `PaymentProviderAdapter`;
- `PaymentProviderRegistry`;
- CloudPayments direct orchestration;
- CloudPayments `AccountId=email`;
- SQLAlchemy mutations in CloudPayments `processing.py`;
- checkout orchestration inside the identity HTTP router;
- `app.state` adapter lookup.

Calling something transitional does **not** authorize removing it in Step 1.

---

# Required glossary

The documentation must use the following concepts consistently.

### Payment provider

A direct payment/acquiring provider used by a Portal-managed flow.

Current example: CloudPayments.

A payment provider may be hidden behind `PaymentProviderAdapter`.

### External billing system

A system authoritative for its own customer/invoice/payment/subscription lifecycle.

It is not a `PaymentProviderAdapter`.

### Portal-managed flow

Payment Portal orchestrates the billing lifecycle and uses a direct payment provider for payment operations/facts.

### External-billing-managed flow

The external billing system owns the external lifecycle; Portal sends commands and projects authoritative facts locally.

### Billing owner

The single authority allowed to manage one subscription's billing lifecycle.

No persisted representation is chosen in Step 1.

### Command

An outbound request/intention.

Success of the command call is not final billing-state authority.

### Authoritative fact

A verified fact from the owning billing source, normally webhook delivery or verified reconciliation result.

### Normalized local projection

Payment Portal's local normalized representation of externally authoritative billing state.

It is not a bidirectional synchronization peer.

### Reconciliation

Recovery/verification of authoritative external state that feeds the **same** local transition path as webhook processing.

### Entitlement

Payment Portal's local access authority consumed by Platform Kernel.

### Internal identity

Portal-owned UUID identity.

### External mapping

Persisted correlation between internal records and opaque external identifiers.

Email is not such an identity mapping.

---

# Documentation source roles

Do not confuse runtime agent-instruction precedence with architectural source roles.

The architectural knowledge hierarchy should be documented as:

1. **ADRs** — durable architectural decisions and amendments.
2. **`ARCHITECTURE.md`** — factual current system map plus clearly labelled target/transitional constraints.
3. **Topic architecture docs** — detailed current/target semantics governed by the ADRs.
4. **Data model doc** — canonical persistence meaning and local model invariants.
5. **PRODUCT / SECURITY / RELIABILITY** — authoritative only for their respective product/security/reliability dimensions.
6. **CODING_CONVENTIONS** — ratchet for new/changed implementation.
7. **AGENTS.md** — concise working instructions and navigation into the authoritative documents.
8. **Linear tickets / execution plans** — temporary work scope; they stop being long-term architecture authority after their decisions are incorporated into ADR/docs.

Existing AGENTS instruction precedence remains unchanged.

---

# Python typing decision

The project currently has Ruff and pytest but no Python type checker in the API dependency/toolchain, and CI does not run mypy/pyright.  

Therefore Step 1 establishes only a ratchet:

```text
all new or materially changed Python functions and methods
must have explicit parameter and return annotations
```

Existing untyped code does not have to be mass-migrated.

Do not add:

- mypy;
- pyright;
- basedpyright;
- another checker;
- repository-wide typing cleanup.

Automated Python type enforcement requires a separate follow-up after existing debt is measured.

---

# Explicitly Out of Scope

The implementation described below must not:

- change production business behavior;
- move runtime packages;
- create `app.application`;
- create repositories per table;
- introduce a generic billing adapter;
- introduce an external customer schema;
- add external billing tables;
- change subscription schema;
- add billing-owner persistence;
- implement LBX/Dodo contracts;
- change checkout API;
- change `Plan.id` identity;
- change `all_access`;
- change CloudPayments `AccountId=email`;
- refactor CloudPayments webhook processing;
- implement reconciliation;
- implement new transaction boundaries;
- implement error architecture;
- implement Sentry;
- change sync/async behavior;
- change FastAPI DI architecture;
- remove `app.state`;
- remove CloudPayments;
- add Python type checker;
- fix `DEFAULT_TENANT_ID`, legacy `all-access` read projection or `utc_now` cleanup from ANY-408. Those already have a separate owner.

---

# Execution Scope

**Status:** `ready-to-execute`

`ANY-411` owns both the completed research/planning phase and the focused implementation described by Steps 1–4 below.

No separate implementation child-ticket is required. The implementation remains deliberately limited to ADR/documentation/agent-rule/guard changes and must not expand into production runtime refactoring or later `ANY-407` work.

The approved decisions in the Research Result section are locked for execution. An execution model should implement one step at a time and stop only if the current repository materially contradicts an assumption required by that step.

---

# Step 1 — Establish the normative billing authority decision

**Status:** `done`

## Goal

Create the minimal new normative foundation that definitively separates the Portal-managed payment-provider flow from the external-billing-managed flow without changing the existing runtime.

## Scope / affected code

Create:

- `docs/architecture/decisions/0004-billing-authority-and-consistency.md`
- `docs/architecture/billing-authority.md`

Update:

- `docs/architecture/decisions/0001-multi-contour-billing.md`
- `docs/architecture/decisions/README.md`

No production Python or TypeScript files.

## Implementation decisions

### ADR-0004

ADR must establish:

- Payment Portal ownership of identity, catalog semantics, entitlement rules and local entitlements;
- external billing ownership of its external customer/invoice/payment/subscription lifecycle;
- local `Order`/`Payment`/`Subscription` as normalized projections for the external-billing-managed flow;
- Platform Kernel consuming only local entitlements;
- explicit distinction between:
  - Portal-managed direct payment provider;
  - external billing system;
- `PaymentProviderAdapter` applies only to the Portal-managed provider flow;
- external billing systems are not registered in `PaymentProviderRegistry`;
- one subscription has exactly one billing owner;
- outbound REST command success is not final billing authority;
- verified webhooks are the primary asynchronous facts;
- reconciliation feeds the same local transition path;
- no last-write-wins;
- email is not billing identity;
- raw vendor payloads/statuses do not become Application/Domain contracts;
- direct CloudPayments remains transitional and separately removable.

ADR relationship:

```text
ADR-0004 amends ADR-0001
```

Specifically, it supersedes only the universal assumption:

```text
each contour registers its own payment-provider adapter
```

It preserves ADR-0001 contour isolation.

`ADR-0001` must receive a minimal amendment note/link to ADR-0004 so a reader entering through the older ADR can see that only the universal payment-provider-adapter assumption was amended. Do not rewrite the rest of ADR-0001.

It must explicitly preserve ADR-0002 and ADR-0003.

### `billing-authority.md`

Document:

- CURRENT / TARGET / TRANSITIONAL distinction;
- authority matrix;
- terminology/glossary;
- Portal-managed and external-billing-managed flows;
- authoritative fact vs command result;
- reconciliation consistency;
- identity/correlation rules;
- trust boundary;
- logical layer responsibility matrix;
- current package mapping;
- known transitional exceptions:
  - `domains/identity/router.py` checkout orchestration;
  - `integrations/cloudpayments/processing.py` persistence/mutations;
  - `payment_providers` broad direct-provider contract;
  - `app.state` adapter lookup;
  - CloudPayments `AccountId=email`;
- no requirement to physically move packages in this step;
- no speculative external-billing interfaces/schema.

The document must be written in English.

## Invariants

- ADR-0001 contour isolation remains valid.
- ADR-0002 `Plan.id` purchase identity remains unchanged.
- ADR-0003 canonical persisted model contract remains unchanged.
- Current CloudPayments runtime remains unchanged.
- Platform Kernel continues to depend only on Portal entitlements.
- No future vendor is selected or modeled.
- No persistence schema is introduced.

## Out of scope

Except for the minimal ADR-0001 amendment note/link described above, do not update existing architecture/provider/product docs yet; that is Step 2/3.

Do not:

- modify Python code;
- modify tests;
- create vendor interfaces;
- add migrations;
- rename existing runtime abstractions;
- implement external billing;
- remove CloudPayments.

## AI prompt

Implement only Step 1 of the approved `ANY-411` implementation plan. `ANY-411` owns this implementation; do not create or require another Linear ticket before executing the step.

Goal: establish the normative Billing Authority & Consistency decision without changing runtime behavior.

Create only:

- `docs/architecture/decisions/0004-billing-authority-and-consistency.md`
- `docs/architecture/billing-authority.md`

Update only:

- `docs/architecture/decisions/0001-multi-contour-billing.md`
- `docs/architecture/decisions/README.md`

Follow these locked decisions:

1. Payment Portal owns Anytool identity, catalog semantics, entitlement rules, and local entitlements.
2. An external billing system owns its external customer, invoice, payment, and subscription lifecycle.
3. For an external-billing-managed flow, local `Order`, `Payment`, and `Subscription` records are normalized local projections, not a competing source of truth.
4. Platform Kernel consumes local Payment Portal entitlements only.
5. A direct payment provider and an external billing system are different architectural concepts.
6. `PaymentProviderAdapter` and `PaymentProviderRegistry` apply only to the Portal-managed direct-provider flow. An external billing system must not be modeled as another `PaymentProviderAdapter`.
7. One subscription has exactly one billing owner. Do not choose a database representation for billing ownership in this step.
8. An outbound REST command/result is not final payment/subscription authority.
9. Verified webhooks are the primary asynchronous billing facts. Reconciliation is a recovery path and must converge through the same future local transition rules, not a second state machine.
10. Do not allow a last-write-wins ownership model.
11. Billing identity/correlation must not rely on email alone. Current CloudPayments `AccountId=email` is transitional legacy and must not be copied into the target design.
12. Raw HTTP/vendor payloads and vendor-specific statuses must stop at the Integration boundary and be normalized before Application/Domain use.
13. Direct CloudPayments remains the current transitional Portal-managed implementation and is not removed by this work.
14. ADR-0004 must explicitly amend only the universal payment-adapter assumption in ADR-0001 while preserving ADR-0001 contour isolation. Add a minimal amendment note/link in ADR-0001 pointing to ADR-0004; do not otherwise rewrite ADR-0001.
15. Preserve ADR-0002 exactly: `Plan.id` is purchase identity, access scope is backend-derived, external/provider IDs remain opaque.
16. Preserve ADR-0003 exactly: `app.models` owns the canonical persisted model contract.
17. Do not invent `BillingSystemAdapter`, external-customer tables, billing-owner fields/enums, vendor DTOs, or another speculative abstraction.

`billing-authority.md` must clearly distinguish CURRENT, TARGET, and TRANSITIONAL architecture and include:

- the authority matrix;
- Portal-managed vs external-billing-managed flows;
- authoritative fact vs command result;
- reconciliation semantics;
- identity/correlation rules;
- the trust-boundary chain:
  untrusted input -> authentication/authenticity verification -> validation/decoding -> redaction as needed -> normalized typed internal contract -> Application;
- logical responsibilities for Presentation, Application, Domain, Persistence/Infrastructure, Integrations, Core, and Composition/Wiring;
- current package mapping;
- explicit transitional exceptions, without requiring package moves.

Repository engineering documentation must be written in English.

Implement only this step. Follow the decisions defined above.

Do not perform broad repository research. Inspect only the Step 1 target paths, the existing ADR-0001/0002/0003, and directly relevant current documentation if necessary to verify wording or links.

Do not redesign the architecture beyond these locked decisions.

Do not perform unrelated refactoring.

Do not work on future steps.

Do not run tests, linters, formatters, documentation checks, generators, or any other automated verification commands.

Do not stage files.

Do not create commits.

After implementation:
1. report every changed/created file;
2. briefly summarize the architectural decision recorded;
3. confirm that ADR-0001 contains only the minimal amendment note/link and that its contour-isolation decision was not rewritten;
4. confirm how ADR-0004 relates to ADR-0001, ADR-0002, and ADR-0003;
5. report the exact manual verification commands I should run.

If the current repository materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
npm run docs:check
```

Review manually that the new ADR explicitly says:

```text
amends ADR-0001
preserves ADR-0002
preserves ADR-0003
external billing system != PaymentProviderAdapter
```

Also review the focused diff and confirm ADR-0001 contains only the minimal amendment note/link:

```bash
git diff -- docs/architecture/decisions/0001-multi-contour-billing.md docs/architecture/decisions/0004-billing-authority-and-consistency.md docs/architecture/billing-authority.md docs/architecture/decisions/README.md
```

## Expected completion

Step is complete when:

- ADR-0004 exists and has a clear relationship to existing ADRs;
- ADR-0001 contains a minimal link/note showing that ADR-0004 amends only its universal payment-provider-adapter assumption;
- the billing-authority document contains the locked authority/dependency/trust model;
- ADR index references the new ADR;
- no runtime or test file changed.

## Proposed commit

```text
docs(architecture): define billing authority model
```

---

# Step 2 — Align core architecture and billing documentation

**Status:** `done`

## Goal

Remove contradictions between the new authority ADR and the existing core architecture documents while preserving an accurate description of the current CloudPayments runtime.

## Scope / affected code

Update:

- `ARCHITECTURE.md`
- `docs/architecture/payment-providers.md`
- `docs/architecture/contours.md`
- `docs/architecture/payment-portal-data-model.md`

Read but normally do not modify:

- `docs/architecture/platform-kernel-contract.md`

## Implementation decisions

### `ARCHITECTURE.md`

Preserve it as the current-state map.

Explicitly separate:

```text
CURRENT: ru + direct CloudPayments
TARGET: Portal-managed or external-billing-managed ownership
TRANSITIONAL: current broad provider abstractions/mixed boundaries
```

Do not rewrite the current CloudPayments implementation as if external billing already existed.

Replace the old universal adapter framing with a link to billing authority.

Document the logical dependency direction:

```text
Presentation → Application → Domain

Application → required persistence/integration capabilities

Persistence / Integrations implement outer capabilities

Composition wires concrete implementations
```

Do not claim the physical package tree already fully implements those layers.

### `payment-providers.md`

Narrow this document to the **Portal-managed direct payment-provider boundary**.

Keep CloudPayments as current `ru` implementation.

Explicitly state:

```text
external billing system != payment provider adapter
```

Remove the implication that every future contour must register another adapter.

Do not turn this document into the external billing architecture document; link to `billing-authority.md`.

### `contours.md`

Keep all contour/data-plane isolation rules.

Change generic enablement language so a contour does not inherently imply a `PaymentProviderAdapter`.

Conceptually:

```text
a contour must have an explicitly configured billing integration/owner
```

For a Portal-managed flow that may mean provider account + provider adapter.

For an external-billing-managed flow it will mean the external integration defined by its implementation ticket.

Do not design that integration here.

### `payment-portal-data-model.md`

Preserve all existing implemented tables and persisted semantics.

Clarify:

- current direct CloudPayments flow remains implemented;
- `payment_provider_accounts` belongs to the direct provider flow;
- external billing can own external lifecycle while Portal models are local normalized projections;
- Portal remains authority for entitlement rules/entitlements;
- no new tables or mappings are being introduced by this architecture documentation step.

Do not update generated DB schema.

## Invariants

- Current runtime remains accurately documented.
- No implemented table is described as removed.
- No nonexistent external-billing table is documented as implemented.
- `Plan.id`, `all_access`, model enums, entitlements and Platform Kernel boundary remain unchanged.
- Current CloudPayments capabilities remain documented as current rather than target.

## Out of scope

Do not change:

- Python;
- TypeScript;
- Alembic;
- generated DB schema;
- OpenAPI;
- `platform-kernel-contract.md` unless a direct factual contradiction is discovered;
- Product/Security/Reliability/AGENTS/Coding conventions — Step 3 owns them.

Do not redesign package structure.

## AI prompt

Implement only Step 2 of the approved `ANY-411` architecture-documentation plan.

Step 1 is complete: `docs/architecture/decisions/0004-billing-authority-and-consistency.md` and `docs/architecture/billing-authority.md` now define the normative authority model.

Update only:

- `ARCHITECTURE.md`
- `docs/architecture/payment-providers.md`
- `docs/architecture/contours.md`
- `docs/architecture/payment-portal-data-model.md`

You may inspect `docs/architecture/platform-kernel-contract.md` only to verify that it remains compatible; do not modify it unless there is a direct contradiction with the locked decisions below.

Locked decisions:

1. `ARCHITECTURE.md` remains a truthful current-state map. Do not pretend external billing is already implemented.
2. Clearly distinguish CURRENT, TARGET, and TRANSITIONAL behavior where needed.
3. Current `ru` uses the Portal-managed direct CloudPayments flow.
4. `PaymentProviderAdapter` is only the Portal-managed direct-provider boundary.
5. An external billing system is a separate authority boundary and is not registered in `PaymentProviderRegistry`.
6. External billing owns its external customer/invoice/payment/subscription lifecycle; Portal `Order`/`Payment`/`Subscription` records become normalized local projections for that flow.
7. Payment Portal still owns identity, catalog semantics, entitlement rules, and local entitlements.
8. Platform Kernel still consumes local entitlements only.
9. Preserve the full ADR-0001 contour/data-plane isolation model.
10. Preserve ADR-0002 exact `Plan.id` checkout identity and opaque identifiers.
11. Preserve ADR-0003 canonical persisted model/enums.
12. Do not create or document speculative external billing tables, schemas, adapters, fields, enums, or vendor APIs.
13. Do not remove or deprecate current CloudPayments runtime in code.
14. Keep the existing data model honest: current tables remain implemented as documented.
15. The target logical dependency direction is Presentation -> Application -> Domain, with Application using persistence/integration capabilities and Composition wiring concrete implementations. Do not claim that the current physical package tree fully conforms yet; link to the transitional package mapping in `billing-authority.md`.

For `payment-providers.md`, narrow the document to the Portal-managed direct-provider boundary and remove statements implying all future contours use a PaymentProviderAdapter.

For `contours.md`, make contour enablement billing-model-neutral: a contour needs an explicitly defined billing integration/owner, while provider account + adapter is only the Portal-managed variant.

For the data-model document, distinguish external lifecycle authority from Portal local projection semantics without changing the schema.

Repository documentation must remain in English.

Implement only this step. Follow the decisions defined in this prompt.

Do not perform broad repository research. Inspect only these documents and their direct ADR links if needed to verify assumptions.

Do not redesign the architecture.

Do not perform unrelated refactoring.

Do not work on future steps.

Do not run tests, linters, formatters, documentation checks, generators, or any other automated verification commands.

Do not stage files.

Do not create commits.

After implementation:
1. report every changed file;
2. summarize which previous provider assumptions were changed;
3. identify every statement deliberately kept as CURRENT CloudPayments behavior;
4. report the exact manual verification commands I should run.

If current code or documentation materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
npm run docs:check
```

Also review the diff for accidental future-tense implementation claims:

```bash
git diff -- ARCHITECTURE.md docs/architecture/payment-providers.md docs/architecture/contours.md docs/architecture/payment-portal-data-model.md
```

## Expected completion

Step is complete when:

- the four core docs no longer imply `PaymentProviderAdapter` is the universal billing architecture;
- current CloudPayments behavior is still accurately represented;
- external billing remains target architecture rather than falsely documented as implemented;
- no schema/runtime changes occurred.

## Proposed commit

```text
docs(architecture): align billing ownership documentation
```

---

# Step 3 — Align agent rules, engineering conventions and cross-cutting authority docs

**Status:** `done`

## Goal

Codify the new vocabulary, source hierarchy, and trust model in working instructions and engineering rules, and update the generic Product/Security/Reliability wording that currently assumes only the payment-provider flow.

## Scope / affected code

Update:

- `AGENTS.md`
- `apps/api/AGENTS.md`
- `docs/README.md`
- `docs/PRODUCT.md`
- `docs/SECURITY.md`
- `docs/RELIABILITY.md`
- `docs/engineering/CODING_CONVENTIONS.md`

Do not modify:

- `apps/web/AGENTS.md` unless a direct broken link created by prior steps requires it.

## Implementation decisions

### Root `AGENTS.md`

Add `billing-authority.md` to authoritative architecture navigation.

Keep existing instruction precedence.

Add concise working rules:

- payment provider and external billing system are different boundaries;
- do not model external billing as another `PaymentProviderAdapter`;
- local entitlements remain access authority;
- raw external contracts stop at Integration;
- current CloudPayments is transitional/current implementation;
- replace the existing generic `Activate paid access only from a verified webhook` rule with the broader authority invariant: paid access changes only from verified authoritative billing facts; current CloudPayments obtains those facts through verified webhooks, while future reconciliation may also provide verified authoritative facts and must feed the same local transition path.

Do not turn AGENTS into a duplicate ADR.

### `apps/api/AGENTS.md`

Add a direct link to `docs/architecture/billing-authority.md` in the backend architecture/navigation guidance so future backend work reaches the normative billing-authority decision.

Align boundary summary with:

```text
Presentation
Application
Domain
Persistence/Infrastructure
Integrations
Core/Composition
```

while making clear that current physical packages are transitional.

Change generic:

```text
dict[str, Any] only at provider edge
```

to:

```text
dict[str, Any] only at untrusted external/integration edge
```

Clarify ANY-326 persisted enum rule:

```text
Python persisted attributes use canonical app.models enums
while physical evolving DB status columns remain TEXT/VARCHAR
```

Do not recreate enums or move modules.

### `docs/README.md`

Add `Billing authority` to architecture index.

Document source **roles**, without overriding AGENTS instruction precedence:

- ADR = durable decision;
- ARCHITECTURE = current-state map;
- topic architecture docs = detailed rules;
- data model = persistence semantics;
- PRODUCT/SECURITY/RELIABILITY = own dimension;
- CODING_CONVENTIONS = new/changed-code ratchet;
- AGENTS = navigation/working digest;
- Linear/exec plans = temporary implementation scope.

### `PRODUCT.md`

Keep current `ru` + CloudPayments product fact.

Remove the assumption that future `eu`/`us` necessarily mean another provider adapter.

Generalize payment authority to:

```text
paid access advances from verified authoritative billing facts
```

and explain that current `ru` obtains those facts through CloudPayments.

Browser return remains non-authoritative.

### `SECURITY.md`

Generalize trust-boundary wording from only payment-provider adapters to any external billing/payment integration.

Preserve:

- signature/authenticity checks;
- secret handling;
- redaction;
- card-data rules.

### `RELIABILITY.md`

Generalize provider-specific reliability rules to authoritative billing facts where appropriate.

Record:

```text
webhook receipt is durable before processing
duplicate facts must be idempotent
late facts must not downgrade confirmed state
reconciliation cannot be a competing state machine
browser return is informational
```

Do not design the future reconciliation implementation.

### `CODING_CONVENTIONS.md`

Add Python typing ratchet:

```text
new or materially changed Python functions/methods
must annotate parameters and return types
```

Do not require migration of untouched code.

Do not add a type-checking tool.

Clarify:

```text
dict[str, Any]
```

is limited to raw/external boundaries.

Clarify:

```text
PostgreSQL status storage remains TEXT/VARCHAR
```

does not mean Python callers should bypass canonical enums created by ANY-326.

## Invariants

- Root agent instruction precedence is preserved.
- No type checker/dependency is introduced.
- Existing untyped code remains valid until touched.
- Current CloudPayments product/security behavior remains valid.
- No UI behavior changes.
- No generated files.
- No production code.

## Out of scope

Do not:

- modify application runtime;
- modify `apps/web/AGENTS.md` without a direct necessity;
- add mypy/pyright;
- perform typing cleanup;
- alter error architecture;
- redesign observability;
- implement reconciliation;
- introduce new API contracts.

## AI prompt

Implement only Step 3 of the approved `ANY-411` architecture-documentation plan.

Steps 1 and 2 are complete. The repository now contains the accepted Billing Authority ADR and the core architecture documents already distinguish the current direct CloudPayments flow from the target external-billing authority model.

Update only:

- `AGENTS.md`
- `apps/api/AGENTS.md`
- `docs/README.md`
- `docs/PRODUCT.md`
- `docs/SECURITY.md`
- `docs/RELIABILITY.md`
- `docs/engineering/CODING_CONVENTIONS.md`

Do not modify `apps/web/AGENTS.md` unless a link produced by the previous steps is actually broken.

Locked decisions:

1. Keep the existing AGENTS instruction priority unchanged. Architecture source roles are a separate concept.
2. Add `docs/architecture/billing-authority.md` to the appropriate architecture navigation.
3. A direct payment provider and an external billing system are different boundaries.
4. External billing must not be described as another `PaymentProviderAdapter`.
5. Payment Portal owns local entitlements and Platform Kernel consumes them.
6. Current CloudPayments is a current/transitional Portal-managed implementation and remains supported.
7. Raw external payloads and provider/vendor status vocabularies stop at the Integration boundary.
8. `dict[str, Any]` is allowed only at a genuinely untrusted external/integration boundary; do not spread it into Application/Domain contracts.
9. Preserve ADR-0003: Python persisted model attributes use canonical enums from `app.models`, while physical database status storage remains TEXT/VARCHAR.
10. Establish a Python typing ratchet: all new or materially changed Python functions and methods must have explicit parameter and return annotations.
11. Do not require mass typing changes in untouched files.
12. Do not introduce mypy, pyright, basedpyright, or another type checker.
13. Product/Security/Reliability wording should refer to verified authoritative billing facts where the rule is generic, while explicitly preserving current CloudPayments behavior where the document describes CURRENT implementation.
14. Replace any generic agent rule that says paid access can advance only from a verified webhook with the broader authority invariant: paid access changes only from verified authoritative billing facts. For CURRENT CloudPayments, those facts arrive through verified webhooks; future reconciliation may also supply verified authoritative facts, but only through the same local transition path.
15. Browser return URLs remain informational and cannot activate access.
16. Webhook authenticity verification, sensitive-data redaction, and durable/idempotent processing constraints remain in force.
17. Reconciliation must eventually feed the same local transitions as webhook facts; document the invariant only, do not design or implement reconciliation here.

In `docs/README.md`, document the architecture knowledge-source roles:

- ADRs: durable architectural decisions;
- ARCHITECTURE.md: factual current-state map plus clearly labelled target/transitional constraints;
- topic architecture docs: detailed architecture under ADRs;
- data-model doc: persistence meaning and local model invariants;
- PRODUCT/SECURITY/RELIABILITY: their own authoritative dimensions;
- CODING_CONVENTIONS: new/changed-code ratchet;
- AGENTS files: concise working instructions and navigation;
- Linear issues/execution plans: temporary implementation scope rather than permanent architecture authority.

Keep repository documentation in English.

Implement only this step. Follow the decisions defined in this prompt.

Do not perform broad repository research. Inspect only these target files and the already-created billing authority documents when necessary to verify links/wording.

Do not redesign the architecture.

Do not perform unrelated refactoring.

Do not work on future steps.

Do not run tests, linters, formatters, documentation checks, generators, or any other automated verification commands.

Do not stage files.

Do not create commits.

After implementation:
1. report every changed file;
2. summarize the agent/source-of-truth rules added;
3. state the exact Python typing ratchet;
4. confirm that no Python type checker was added;
5. report the exact manual verification commands I should run.

If current repository content materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
npm run docs:check
```

Focused diff:

```bash
git diff -- AGENTS.md apps/api/AGENTS.md docs/README.md docs/PRODUCT.md docs/SECURITY.md docs/RELIABILITY.md docs/engineering/CODING_CONVENTIONS.md
```

## Expected completion

Step is complete when:

- both root `AGENTS.md` and `apps/api/AGENTS.md` point to the new authority doc;
- provider vs external-billing terminology is consistent;
- source roles are explicit;
- Python typing ratchet is documented;
- security/reliability rules cover either billing ownership model;
- no runtime/toolchain dependency changed.

## Proposed commit

```text
docs(engineering): codify billing authority rules
```

---

# Step 4 — Guard the architecture knowledge graph

**Status:** `todo`

## Goal

Minimally enforce the new normative documents through the existing documentation-check mechanism without introducing premature AST guards for layers that do not yet physically exist in the codebase.

## Scope / affected code

Primary:

- `scripts/repo.py`
- `apps/api/tests/test_repository_docs.py`

Explicitly preserve:

- `apps/api/tests/test_architecture.py`

unless a purely documentation-related reference requires no runtime rule change.

## Implementation decisions

Use the existing documentation consistency mechanism.

Do not create a second doc-validation framework.

Extend existing authority-link checks so the repository mechanically requires the important relationships established by Steps 1–3.

At minimum guard that:

- root `AGENTS.md` reaches `docs/architecture/billing-authority.md`;
- `apps/api/AGENTS.md` reaches `docs/architecture/billing-authority.md`;
- `ARCHITECTURE.md` reaches the billing-authority source;
- `docs/README.md` indexes billing authority;
- `payment-providers.md` links to billing authority rather than standing as universal billing authority;
- ADR-0001 links to/amends via ADR-0004;
- ADR-0004 remains indexed in `decisions/README.md`;
- the new billing-authority document links to the relevant ADR authority.

Use existing helpers such as the current authority-link/Markdown-link checks where possible.

Tests should cover:

- valid new authority graph passes;
- missing required billing-authority link produces an actionable error.

Avoid brittle assertions for entire paragraphs or exact prose.

### Architecture AST guards

Do **not** add new physical-layer rules yet for:

```text
Application
Persistence ports
Integration ports
```

because the current repository does not yet physically expose the target package structure and contains known transitional mixed responsibilities.

Retain current guards that already enforce valid boundaries:

- Domain must not import integrations;
- Core must not import domain/integration business code;
- routers do not import routers;
- integration does not import domain router;
- provider-neutral code does not contain CloudPayments-specific literals;
- canonical persisted model/enums remain guarded.

Those are already useful and do not need redesign.

## Invariants

- Existing architecture guards continue to pass unchanged.
- New guard covers documentation authority links only.
- No production behavior changes.
- No target package structure is enforced before it exists.
- No prose parser or custom architecture framework is introduced.
- Tests remain focused.

## Out of scope

Do not:

- modify runtime packages;
- move files;
- add layer directories;
- add mypy/pyright;
- introduce dependency-injection framework;
- add AST rules that current intentional transitional code cannot satisfy;
- enforce provider/billing terminology by grepping every source string;
- redesign `scripts/repo.py`.

## AI prompt

Implement only Step 4 of the approved `ANY-411` architecture-documentation plan.

Steps 1-3 are complete. The new Billing Authority ADR/documentation is now the normative architecture source, and existing architecture/product/agent/convention documents have been aligned.

Goal: minimally guard the new architecture documentation relationships using the repository's existing documentation-check infrastructure.

Work primarily in:

- `scripts/repo.py`
- `apps/api/tests/test_repository_docs.py`

Do not modify production runtime code.

Preserve `apps/api/tests/test_architecture.py` and the existing AST architecture rules. Do not add new physical Application/Persistence/Integration layer guards in this step.

Implementation requirements:

1. Reuse the existing documentation knowledge-hierarchy/link checking mechanism. Do not create a second documentation parser/framework.
2. Extend the existing authority graph so important Billing Authority relationships are mechanically required.
3. At minimum ensure the existing mechanism guards:
   - root `AGENTS.md` -> `docs/architecture/billing-authority.md`;
   - `apps/api/AGENTS.md` -> `docs/architecture/billing-authority.md`;
   - `ARCHITECTURE.md` -> `docs/architecture/billing-authority.md`;
   - `docs/README.md` -> billing authority architecture entry;
   - `docs/architecture/payment-providers.md` -> billing authority;
   - ADR-0001 -> ADR-0004 amendment relationship;
   - `docs/architecture/decisions/README.md` -> ADR-0004;
   - billing authority document -> its governing ADR(s), using the existing link mechanism where appropriate.
4. Follow the existing `CORE_AUTHORITY_LINKS`, `check_required_markdown_links`, or equivalent current mechanism rather than inventing another pattern.
5. Add focused tests in `apps/api/tests/test_repository_docs.py` proving:
   - the new authority graph is accepted;
   - omission of a required billing-authority link produces an actionable error.
6. Avoid tests that snapshot whole Markdown documents or assert large exact prose blocks.
7. Do not change the existing AST dependency boundaries simply because the target documentation now names Presentation/Application/Domain/Persistence/Integrations/Core/Composition. The current physical code still has explicitly documented transitional exceptions.
8. Preserve the existing canonical persisted-model guards from ANY-326.
9. Preserve existing CloudPayments/provider-neutral AST guards.
10. No database, API, generated-file, application-runtime, or frontend changes are allowed.

Implement only this step. Follow the decisions defined in this prompt.

Do not perform broad repository research. Inspect only `scripts/repo.py`, `apps/api/tests/test_repository_docs.py`, `apps/api/tests/test_architecture.py` for verification of the existing mechanism, and the architecture documents whose links are being guarded.

Do not redesign the architecture.

Do not redesign the repository harness.

Do not perform unrelated refactoring.

Do not work on future steps.

Do not run tests, linters, formatters, documentation checks, generators, or any other automated verification commands.

Do not stage files.

Do not create commits.

After implementation:
1. report every changed file;
2. list the exact new documentation relationships being guarded;
3. confirm that no new target-layer AST rule was introduced;
4. confirm that existing architecture guards were preserved;
5. report the exact manual verification commands I should run.

If the current repository materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

Use the repository's canonical harness rather than invoking pytest directly. Run the fast API suite first so the changed repository-doc tests and the preserved architecture tests execute in the supported API environment:

```bash
npm run test:api:fast
```

Then run the repository architecture/documentation gates and fast canonical check:

```bash
npm run docs:check
npm run architecture:check
npm run check:fast
```

Before final PR/handoff, run the canonical full check:

```bash
npm run check
```

## Expected completion

Step is complete when:

- deleting/breaking the required billing-authority links, including the root and API agent-guide links, would fail the existing docs check;
- the new ADR is mechanically part of the documented authority graph;
- existing AST boundaries still pass;
- no premature target-layer guard has been added;
- the full repository check passes.

## Proposed commit

```text
test(architecture): guard billing authority documentation
```

---

# Final Plan Validation

## Acceptance criteria coverage

### Research based on current repository

Covered:

- current authoritative docs;
- accepted ADRs;
- current package structure;
- actual CloudPayments wiring;
- webhook trust boundary;
- direct provider registry;
- persistence/query layer;
- existing architecture/doc guards;
- current Python tooling;
- ANY-326;
- ANY-327;
- ANY-408;
- ANY-407 direction.

### Already implemented parts retained

Retained:

- `app.models` canonical ownership;
- `Plan.id` purchase identity;
- contour isolation;
- Platform Kernel entitlement boundary;
- verified webhook trust principle;
- CloudPayments signature verification/redaction;
- current architecture AST guards;
- current documentation guard harness;
- useful `infrastructure/queries` extraction;
- `main.py` composition-root role.

### Stale contradictions identified

Identified and explicitly assigned to implementation steps:

- universal `PaymentProviderAdapter` architecture;
- universal future provider-adapter assumption;
- Portal ownership wording that does not distinguish external authority/local projection;
- provider-only trust vocabulary;
- provider-only `dict[str, Any]` language;
- missing Python annotation ratchet;
- physical layer diagram that is too weak for the new direction.

### Future work not stolen

Not included:

- projection mutation refactor;
- command flows;
- external customer implementation;
- external billing integration;
- persistence extraction;
- transaction architecture;
- error architecture;
- observability rollout;
- DI refactor;
- reconciliation implementation;
- subscription owner schema/cutover;
- CloudPayments removal;
- Sentry;
- vendor APIs.

### Execution readiness

There is no unresolved architecture or ownership decision blocking the plan.

`ANY-411` owns Steps 1–4. The research phase is complete, the implementation surfaces are fixed per step, and the plan is ready to execute sequentially under the same ticket.

No architectural question should be reopened during execution unless the current repository materially contradicts one of the locked assumptions in the relevant step.
