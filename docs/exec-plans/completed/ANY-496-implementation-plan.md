# ANY-496 — Establish Subscription / Entitlement Application Transitions — Final Implementation Plan

**Overall status:** `done`

## Objective

Establish one canonical, provider-neutral and transport-neutral **Application-owned transition boundary** for Subscription and Entitlement lifecycle changes.

The implementation must evolve the already existing lifecycle implementation instead of replacing it with a new abstraction.

The final design must preserve these authority boundaries:

- `Application` owns Subscription / Entitlement business transitions.
- Local `Entitlement` remains the Payment Portal source of truth for access.
- ANY-493 / Step 8 owns commercial `Order` / `Payment` / `Refund` state transitions.
- ANY-496 / Step 9 consumes only commercial outcomes that have local Subscription / Entitlement consequences.
- Trial and manual access remain valid without an external/provider subscription.
- Future externally owned billing facts must reuse provider-neutral Application semantics.
- CloudPayments remains deactivated from normal runtime and must not become the target architecture.

---

# Implementation baseline

## Branch inheritance

ANY-496 is implemented **directly on top of the reviewed/accepted ANY-493 head**.

Expected sequence:

```text
ANY-490
  ↓
ANY-493
  ↓
ANY-496
```

Rules:

- Create the ANY-496 working branch from the currently reviewed/accepted `ANY-493` head.
- A merge of ANY-493 into `main` is **not required** to begin ANY-496 implementation.
- Treat the inherited ANY-493 repository state as the current predecessor baseline.
- ANY-490 and all earlier completed ANY-407 steps are already included in that baseline.
- Do not reimplement, replay, or redesign ANY-490 or ANY-493 work.
- Do not compare against older pre-490 / pre-493 architecture unless a concrete contradiction is discovered in current local code.
- Do not pull ANY-497, reconciliation, or later ANY-407 work into this ticket.
- Before final ANY-496 verification / merge, synchronize any later accepted ANY-493 delta using the team's normal Git workflow.
- After synchronization, revalidate **only** assumptions affected by the predecessor delta.
- Do not restart broad Step 8 research because ANY-493 later merges.
- If a late ANY-493 change materially alters the Step 8 → Step 9 handoff, transaction ownership, persistence boundaries, or commercial outcome semantics assumed by ANY-496, stop and update only the affected plan/implementation area.

Before Step 1, perform only a **minimal local baseline check** that the expected ANY-493 Step 8 handoff still exists.

Relevant current files are expected to include:

- `apps/api/app/domains/billing/service/commercial_contracts.py`
- `apps/api/app/domains/billing/service/commercial_transitions.py`
- `apps/api/app/integrations/cloudpayments/processing.py`
- `apps/api/app/integrations/cloudpayments/refunds.py`
- `apps/api/app/domains/billing/service/__init__.py`

Expected Step 8 → Step 9 contract:

- a newly applicable confirmed payment can trigger paid subscription activation;
- a newly confirmed refund can trigger Subscription / Entitlement consequences;
- Step 8 continues to own financial/commercial truth;
- Step 9 owns local Subscription / Entitlement consequences;
- both transition groups may participate in the same caller-owned transaction;
- neither boundary commits or rolls back the caller's outer transaction.

If current ANY-493-derived code materially contradicts these assumptions, stop before implementation and report the contradiction.

Otherwise, do not perform broad Step 8 research.

---

# Current-state conclusions

The repository already contains a substantial Subscription / Entitlement lifecycle implementation.

ANY-496 must **consolidate, clarify, and harden it**, not replace it.

Canonical persisted lifecycle models remain:

- `Subscription`
- `Entitlement`
- `SubscriptionEvent`

The existing Application lifecycle already covers:

- trial start;
- paid period activation;
- automatic renewal enablement;
- renewal payment result;
- normalized external/provider subscription state;
- cancellation;
- refund consequences;
- expiration.

The canonical public boundary remains:

```text
app.domains.billing.service
```

The implementation must continue using explicit typed commands and explicit transition functions.

Do not introduce:

- a generic `apply_transition(...)`;
- repository-per-table abstractions;
- generic CRUD repositories;
- a generic Unit of Work;
- parallel pure-domain entity hierarchies.

---

# Existing persistence contract

Use the existing selective persistence boundary:

- `app.infrastructure.queries` owns read/query/locking mechanics;
- `app.infrastructure.persistence` is used only for focused storage-specific mechanics where justified;
- Application owns orchestration and business decisions;
- persistence helpers may query, lock, flush, or use savepoints;
- persistence helpers must not commit or roll back the outer transaction.

No schema migration is currently expected for ANY-496.

Existing `SubscriptionEvent.operation_idempotency_key` uniqueness and lifecycle event history should be reused unless current local code proves them insufficient for a required invariant.

Do not add a migration merely to improve naming or layering aesthetics.

---

# Preserved lifecycle semantics

The behavior below is already part of the baseline and must be preserved unless a concrete Step 9 invariant requires an explicitly justified correction.

Codex must treat this section as established behavior, not as research work to repeat.

## Trial

- Trial creates a local `Subscription` plus trial `Entitlement`.
- Trial does not require an `Order`, `Payment`, or external/provider subscription.
- Portal-owned trial access remains valid in the future external-billing architecture.

## Paid activation

- Paid access activates only from confirmed commercial/payment context.
- Step 8 owns payment/commercial truth.
- Step 9 decides the local Subscription / Entitlement consequence.
- Trial-to-paid conversion preserves existing lifecycle period rules.
- Same-plan paid activation preserves existing period behavior.

## Replacement / supersession / carry-forward

- Plan replacement within the same access scope preserves existing replacement and supersession semantics.
- Existing paid-through access may be carried forward according to current entitlement rules rather than silently truncated.
- Superseded entitlements remain historical records where the current model already preserves them.
- Existing replacement linkage must remain intact where currently supported.

## Renewal

- Renewal success extends the paid lifecycle according to existing rules and grants/extends the corresponding entitlement.
- Renewal failure changes lifecycle state without directly revoking still-valid paid access unless existing lifecycle rules explicitly require it.
- Automatic renewal remains enabled only under existing consent/scope rules.

## External authoritative subscription state

- Normalized authoritative external subscription state updates the local `Subscription` projection.
- It does not directly become the access authority.
- Entitlement consequences continue to be decided by Payment Portal lifecycle rules.

## Cancellation / expiration

- Existing distinction between Subscription state and Entitlement validity remains intact.
- Cancellation does not automatically imply access disappearance when current entitlement rules preserve already-paid access.
- Expiration keeps current terminal/access semantics.

## Refunds

- Full and partial refunds preserve the existing atomic lifecycle consequences.
- Existing full/partial calculation and entitlement semantics remain authoritative.
- A refund must not resurrect expired/revoked access.
- Step 8 owns confirmed commercial refund truth.
- Step 9 owns local Subscription / Entitlement consequences.

## Transactions and concurrency

- Caller owns the outer transaction.
- Lifecycle services participate in the caller-owned transaction.
- Lifecycle services do not commit or roll back the outer transaction.
- Existing operation-key idempotency and row-locking protections remain in force.
- Existing concurrency guarantees from ANY-380 and predecessor work must not be weakened.

---

# Canonical lifecycle ownership

The target ownership after ANY-496 is:

```text
Presentation / Integration / Operational caller
                    ↓
      Billing Application lifecycle boundary
                    ↓
        Subscription / Entitlement rules
                    ↓
      focused query / persistence helpers
                    ↓
               SQLAlchemy ORM
```

External provider/vendor state must never become an alternate access authority.

Local access remains:

```text
Entitlement -> access
```

not:

```text
provider subscription -> access
```

and not:

```text
Payment -> access
```

A Payment, Refund, or external billing fact may trigger an Application transition, but the final local access decision remains owned by Subscription / Entitlement semantics.

---

# Implementation strategy

Use **two implementation steps only**.

The plan intentionally avoids separate micro-steps for naming changes, DTO adjustments, small query helpers, architecture guards, or documentation-only edits when those changes exist only to support the same semantic outcome.

Execute sequentially:

```text
Step 1
Canonical Application contract + lifecycle semantics
        ↓
Step 2
Outer handoffs + ownership guards + regressions + documentation
```

Do not parallelize the steps.

Each step should leave the repository in a coherent, reviewable state with meaningful behavior.

---

# Step 1 — Establish and harden canonical Subscription / Entitlement Application transitions

**Status:** done

## Goal

Establish the existing billing lifecycle facade as the canonical provider-neutral Application boundary and make its authoritative subscription-state, idempotency, ordering, terminal-state, refund, and concurrency semantics explicit and safe.

This step combines contract cleanup and the behavior that depends on that contract so no intermediate implementation exists solely to prepare a later step.

---

## Scope / affected code

Primary Application/lifecycle files:

- `apps/api/app/domains/billing/enums.py`
- `apps/api/app/domains/billing/service/commands.py`
- `apps/api/app/domains/billing/service/lifecycle.py`
- `apps/api/app/domains/billing/service/lifecycle_operations.py`
- `apps/api/app/domains/billing/service/state_machine.py`
- `apps/api/app/domains/billing/service/support.py` only if justified
- `apps/api/app/domains/billing/service/__init__.py`

Persistence/query boundary:

- `apps/api/app/infrastructure/queries/subscriptions.py`

Tests:

- `apps/api/tests/test_billing_lifecycle.py`
- `apps/api/tests/test_billing_lifecycle_concurrency_postgres.py`

Only touch other directly related lifecycle files when required by the current implementation.

Do not broaden the scope merely because adjacent code could be cleaned up.

---

## Implementation decisions

### 1. Canonical Application boundary

Keep:

```text
app.domains.billing.service
```

as the canonical public Application lifecycle facade.

Preserve explicit operation-specific commands/functions.

Supported lifecycle operations remain conceptually explicit:

- start trial;
- activate paid period;
- enable automatic renewal;
- apply renewal success/failure;
- apply normalized authoritative subscription state;
- request cancellation;
- apply refund consequence;
- expire due subscriptions.

Do not introduce a generic transition dispatcher.

Do not create a new parallel lifecycle service tree.

---

### 2. Provider/vendor-neutral Application vocabulary

Application-facing concepts for authoritative external subscription state must be provider/vendor-neutral.

Application vocabulary must describe normalized business meaning, not:

- CloudPayments terminology;
- raw provider DTOs;
- vendor statuses;
- future LBX/Dodo-specific concepts.

Retained persisted historical enum values may remain unchanged when renaming would require a migration solely for aesthetics.

For example, an already persisted event type such as:

```text
PROVIDER_SUBSCRIPTION_STATE_APPLIED
```

may remain as a storage/audit compatibility value even if the Application command/type becomes vendor-neutral.

---

### 3. Explicit authoritative occurrence time

Normalized authoritative subscription-state input must carry an explicit, timezone-aware authoritative `occurred_at`.

For this operation:

- omission must not silently substitute processing-time `utc_now()`;
- timezone-naive timestamps must fail validation;
- receipt time, processing time, DB update time, or request arrival order are not authoritative freshness signals.

Do not generalize this requirement to unrelated lifecycle commands unless current existing semantics already require it.

---

### 4. Operation idempotency is semantic identity

For normalized authoritative-state transitions:

`operation_idempotency_key` is an operation identity, not merely a duplicate hint.

An exact replay must match the persisted semantic operation at least by:

- `subscription_id`;
- normalized authoritative-state transition kind;
- normalized target state;
- authoritative `occurred_at`.

Behavior:

- same operation key + same semantic input → return/converge on the already-established semantic result;
- same operation key + different semantic input → transport-neutral idempotency/operation conflict; fail closed;
- valid replay must not create another lifecycle event or duplicate business effect.

Preserve existing ANY-380 concurrency-idempotency behavior.

Do not weaken uniqueness or locking protections.

---

### 5. Freshness / stale / reordered authoritative-state semantics

These rules apply **only** to normalized authoritative external subscription-state facts.

They must not become generic last-write-wins semantics for all lifecycle operations.

Processing sequence:

1. Resolve exact operation-key replay/conflict according to the semantic identity rules above.
2. Lock the target `Subscription` through the existing focused query/locking boundary.
3. Determine the latest previously applied ordering-aware authoritative-state event.
4. Compare authoritative `occurred_at`.
5. Apply the explicit policy below.

Policy:

- older than the latest applied authoritative state → **stale safe no-op**;
- same occurrence time + same normalized target state → **safe duplicate/no-op**;
- same occurrence time + different normalized target state → **transport-neutral conflict / fail closed**;
- newer occurrence time → validate through the existing lifecycle transition graph;
- valid exact replay → return existing semantic result;
- terminal-state rules remain authoritative and cannot be bypassed by stale/reordered input.

Do not use:

- webhook receipt timestamp;
- processing timestamp;
- ORM `updated_at`;
- current wall clock;
- arrival order

as freshness authority.

---

### 6. Legacy authoritative-state event timestamps

Existing historical `PROVIDER_SUBSCRIPTION_STATE_APPLIED` rows may have been created when generic `LifecycleCommand.occurred_at` could default to processing-time `utc_now()`.

Therefore, do not automatically assume every historical event timestamp is an authoritative external occurrence timestamp.

Before implementing freshness ordering:

- verify whether existing relevant historical events can be proven to contain authoritative occurrence time;
- if not provable, introduce the **smallest no-schema distinction** using existing event metadata or another already persisted field so newly ordering-aware events can be distinguished from legacy processing-time events;
- freshness comparison must use only events whose `occurred_at` is known to be authoritative.

Do not add a DB migration only for this distinction unless current persisted structure makes the required safe semantics impossible.

If safe semantics cannot be implemented without a material schema decision, stop and report the contradiction instead of improvising.

---

### 7. Unknown / unsupported / non-normalizable authoritative state

Unknown external state must have explicit safe behavior.

Rule:

```text
unknown / unsupported / non-normalizable authoritative state
    -> reject before mutation
    -> transport-neutral error
    -> no Subscription mutation
    -> no Entitlement mutation
    -> no lifecycle event
```

Do not guess an internal state.

Do not silently map unknown input to an existing state.

Do not defer this decision to Integration-specific code.

---

### 8. Existing transition graph remains authoritative

For a newer normalized authoritative state:

- use the existing lifecycle transition graph;
- preserve valid transition semantics;
- preserve terminal-state protection;
- do not resurrect canceled/expired/refunded/other terminal local state merely because a later-delivered external fact asks for an older/non-permitted state;
- do not introduce a parallel provider-specific transition graph.

---

### 9. Refund lifecycle applicability moves into Application

The ANY-493-derived retained CloudPayments integration currently contains policy equivalent to:

```text
does this confirmed commercial refund have a local Subscription / Entitlement lifecycle consequence?
```

That is Step 9 policy and belongs inside the canonical Application lifecycle boundary.

Move this decision inward.

Preserve current business meaning:

- if a confirmed refund belongs to an order with a linked Subscription, apply existing refund lifecycle rules;
- if a canceled order legitimately has no linked Subscription, the lifecycle consequence may be a safe no-op;
- if a linked Subscription is required by the lifecycle but data is inconsistent, fail closed rather than inventing state;
- existing full-vs-partial refund calculations remain unchanged;
- existing provenance rules remain unchanged;
- existing Subscription/Entitlement status behavior remains unchanged;
- refund application must not resurrect expired access.

The Application API may represent a legitimate “no local lifecycle consequence” outcome.

Do not force Integration code to query Subscription persistence and decide policy.

Do not freeze a large result hierarchy if a small transport-neutral result/disposition is enough.

---

### 10. Concurrency semantics

Concurrency must preserve the same invariants as sequential execution.

Relevant Postgres coverage must prove, where applicable:

- identical operation-key retries converge;
- no duplicate lifecycle events;
- stale and newer authoritative facts cannot race into a regressed final state;
- equal-time conflicting authoritative facts fail safely;
- row-lock / uniqueness behavior does not surface as avoidable `IntegrityError` / 500 for valid duplicate retries;
- no duplicate/overlapping entitlement effects are introduced by retry races;
- outer transaction ownership remains unchanged.

Do not introduce broad locking unrelated to demonstrated lifecycle races.

---

## Invariants

After Step 1:

- Application-facing lifecycle vocabulary is vendor-neutral.
- Entitlement remains the local access authority.
- Step 8 retains financial/commercial ownership.
- Step 9 owns Subscription / Entitlement consequences.
- Exact replay is idempotent.
- Reuse of an operation key for different semantic input fails closed.
- Stale authoritative facts cannot regress local state.
- Equal-time same-target input is safe.
- Equal-time conflicting input fails closed.
- Unknown/non-normalizable input is rejected before mutation.
- Legacy processing-time timestamps are not silently treated as authoritative ordering facts.
- Terminal local state cannot be resurrected by stale/reordered facts.
- Refund lifecycle applicability is Application-owned.
- Existing correct trial/paid/renewal/cancel/refund/expire semantics remain intact.
- No generic dispatcher, repository-per-table, or Unit of Work is introduced.
- Application/query/persistence helpers do not commit or roll back the outer transaction.

---

## Out of scope

- ANY-497 external billing command flows;
- external billing ports/adapters;
- reconciliation/polling;
- provider migration;
- CloudPayments deletion;
- Platform Kernel implementation changes;
- new public entitlement-management APIs;
- generic event sourcing;
- global timestamp ordering for all lifecycle operations;
- schema redesign without a demonstrated Step 9 invariant;
- unrelated cleanup.

---

## AI prompt

```text
Implement ONLY Step 1 of the approved ANY-496 implementation plan.

Repository baseline:
- The working branch is derived directly from the currently reviewed/accepted ANY-493 head.
- ANY-490 and all earlier completed ANY-407 work are already included.
- A merge of ANY-493 into main is not required for this implementation step.
- Treat the current local ANY-493-derived repository state as the source of truth.
- Do not re-research or reimplement ANY-490 or ANY-493.
- Perform only minimal local inspection of directly relevant files needed to implement this step.

Goal:
Establish and harden the canonical provider-neutral Application boundary for Subscription / Entitlement transitions.

Implement the Step 1 decisions as one coherent change set.

Required contract and semantics:

1. Keep app.domains.billing.service as the canonical Application lifecycle facade.
2. Preserve explicit operation-specific lifecycle commands/functions; do not introduce a generic transition dispatcher.
3. Make Application-facing authoritative external subscription-state vocabulary provider/vendor-neutral.
4. Keep persisted historical enum values unchanged when renaming would require a migration solely for naming aesthetics.
5. Require an explicit timezone-aware authoritative occurred_at for normalized authoritative subscription-state input. Do not silently substitute processing time.
6. Treat operation_idempotency_key as semantic operation identity:
   - same key + same subscription/transition kind/target/occurred_at => valid replay, converge on existing semantic result;
   - same key + different semantic input => transport-neutral idempotency/operation conflict, fail closed.
7. Preserve existing ANY-380 concurrency-idempotency behavior.
8. Lock the target Subscription through the existing focused query/locking boundary.
9. Implement authoritative-state freshness only for normalized authoritative external subscription-state facts:
   - older authoritative occurred_at => stale safe no-op;
   - equal timestamp + same target => safe no-op;
   - equal timestamp + different target => transport-neutral conflict;
   - newer timestamp => evaluate using the existing lifecycle transition graph.
10. Never use arrival time, processing time, receipt time, ORM updated_at, or current wall-clock time as ordering authority.
11. Do not automatically trust legacy PROVIDER_SUBSCRIPTION_STATE_APPLIED occurred_at values if older code may have substituted processing-time utc_now().
12. Verify whether historical relevant events contain true authoritative occurrence time. If that cannot be proven, use the smallest no-schema marker/versioning mechanism in existing persisted event metadata (or an equivalently minimal existing field) so ordering-aware events can be distinguished from legacy events.
13. Unknown / unsupported / non-normalizable authoritative state must be rejected before mutation with a transport-neutral error. It must create no Subscription mutation, Entitlement mutation, or lifecycle event.
14. Preserve existing lifecycle transition and terminal-state rules.
15. Move the decision “does this confirmed commercial refund have a local Subscription / Entitlement consequence?” into the Application lifecycle boundary.
16. Preserve current full/partial refund behavior, provenance, lifecycle semantics, and fail-closed inconsistent-data behavior.
17. Keep Step 8 commercial truth ownership unchanged.
18. Keep outer transaction ownership unchanged.
19. Add only focused query/persistence mechanics required for the approved semantics.
20. Add/adjust focused unit and PostgreSQL concurrency coverage for the new semantics.

Preserve existing lifecycle behavior:
- trial without Order/Payment/provider subscription;
- paid activation from confirmed commercial state;
- trial-to-paid and same-plan period semantics;
- replacement/supersession/carry-forward behavior;
- renewal success/failure semantics;
- cancellation/expiration distinction from entitlement validity;
- full/partial refund consequences;
- existing caller-owned transaction semantics.

Test discipline:
- Existing tests are behavioral evidence.
- Do not weaken, delete, skip, or broadly rewrite existing assertions merely to make the implementation pass.
- Change an existing behavioral expectation only when the approved Step 1 plan explicitly requires that behavior change.
- Add focused new assertions/tests for the approved semantics instead of masking regressions.

Architecture constraints:
- No generic repository.
- No repository-per-table abstraction.
- No generic Unit of Work.
- No new parallel pure-domain model hierarchy.
- No future ANY-497 work.
- No reconciliation.
- No CloudPayments reactivation.
- No unrelated refactoring.
- No broad repository research.

Execution constraints:
- DO NOT run tests, linters, formatters, builds, or verification commands.
- Do not stage or commit changes.

If you find a material contradiction with the approved plan or the current ANY-493-derived baseline, stop and report it before making that contradictory change.

When finished, report:
1. changed files;
2. concise implementation summary;
3. exact lifecycle/idempotency/freshness/refund semantics implemented;
4. any local assumptions you had to verify;
5. exact manual verification commands I should run.
```

---

## Manual verification

Run focused lifecycle tests:

```bash
(cd apps/api && uv run pytest tests/test_billing_lifecycle.py -q)
```

Run focused PostgreSQL concurrency tests:

```bash
(cd apps/api && uv run pytest tests/test_billing_lifecycle_concurrency_postgres.py -q)
```

If Step 1 changes another existing focused test file because current code places the same lifecycle semantics there, run that exact file as reported by Codex.

---

## Expected completion

The repository has one coherent provider-neutral Application lifecycle contract with explicit safe semantics for:

- exact replay;
- operation-key conflicts;
- authoritative occurrence time;
- stale/reordered state;
- equal-time conflicts;
- unknown external state;
- terminal-state protection;
- refund lifecycle applicability;
- concurrency.

The existing lifecycle remains intact for already-correct behavior.

---

## Proposed commit

```text
refactor(billing): establish subscription transition semantics
```

---

# Step 2 — Route callers through the boundary, enforce ownership, and finalize the contract

**Status:** done

## Goal

Make all mutation-oriented outer paths delegate Subscription / Entitlement policy to the canonical Application lifecycle boundary, protect that ownership with focused guards/regressions, and document the completed Step 9 contract.

This step intentionally combines outer handoff cleanup, architecture protection, compatibility verification, and documentation because these changes all describe and protect the same finalized boundary.

---

## Scope / affected code

### Production / outer handoff

- `apps/api/app/integrations/cloudpayments/processing.py`
- `apps/api/app/integrations/cloudpayments/refunds.py`
- `apps/api/app/commands/expire_subscriptions.py` — verify first; modify only if required
- `apps/api/app/domains/billing/service/__init__.py` if facade exports need adjustment

### Architecture guard

- `scripts/repo.py`
- `apps/api/tests/test_architecture.py`

### Regression tests

- `apps/api/tests/test_cloudpayments_webhook_postgres.py`
- `apps/api/tests/test_expire_subscriptions_cli.py`
- relevant existing API/account-read tests identified in the current repository
- focused lifecycle tests only if required by handoff changes

### Documentation

- `ARCHITECTURE.md`
- `docs/architecture/billing-authority.md`
- `docs/RELIABILITY.md`

Review for contradiction only:

- `docs/architecture/decisions/0004-billing-authority-and-consistency.md`

Only modify ADR-0004 if the completed code materially contradicts its current normative text and project ADR policy allows/needs clarification.

---

## Implementation decisions

### 1. Preserve ANY-493 commercial ownership

ANY-493 Step 8 remains authoritative for:

- `Order`;
- `Payment`;
- `Refund`;
- commercial state transitions;
- confirmed commercial outcome semantics.

ANY-496 must not duplicate or reopen that ownership.

---

### 2. Paid commercial outcome handoff

For a newly applicable confirmed paid commercial outcome:

```text
ANY-493 commercial transition
    ↓
newly applicable paid result
    ↓
ANY-496 Application paid-period transition
```

Outer Integration code may trigger the handoff but must not:

- directly mutate Subscription;
- directly mutate Entitlement;
- recreate paid-period lifecycle policy;
- independently decide access semantics.

The Step 9 Application boundary remains responsible for local lifecycle consequences.

---

### 3. Refund commercial outcome handoff

For a newly confirmed refund:

```text
ANY-493 commercial refund transition
    ↓
newly applicable refund result
    ↓
ANY-496 Application refund lifecycle transition
```

Integration must not decide:

```text
does this refund affect local subscription/access?
```

Remove retained Integration policy/helper equivalent to:

```text
refund_lifecycle_applies(...)
```

when it still exists in the inherited ANY-493 code.

The Application boundary decides whether:

- the refund has a Subscription / Entitlement consequence;
- the result is a legitimate no-op;
- inconsistent data must fail closed.

---

### 4. Preserve webhook transaction semantics

Preserve the retained webhook compatibility transaction model established by predecessor work.

Expected model:

1. durable/redacted receipt/inbox transaction is committed according to existing behavior;
2. normalized processing happens in the existing second caller-owned transaction;
3. commercial Step 8 transition participates in that transaction;
4. Subscription / Entitlement Step 9 consequence participates in the same transaction;
5. lifecycle failure rolls back commercial + lifecycle effects from that transaction;
6. already committed durable receipt remains preserved.

Do not move network calls into open DB transactions.

Do not make lifecycle helpers own outer commit/rollback.

---

### 5. Expiry CLI

Verify `expire_subscriptions` rather than redesigning it.

Correct target shape:

- CLI/job constructs the Application lifecycle command;
- CLI/job invokes the canonical Application lifecycle boundary;
- caller owns the explicit outer transaction;
- post-commit diagnostic/output behavior remains outside business transition ownership.

If current code already satisfies this:

**leave it unchanged.**

Do not make a cosmetic modification only to include the file in the ticket.

---

### 6. Architecture guard

Add the minimum stable architecture protection needed to prevent Step 9 ownership from drifting back outward.

The guard should protect semantic violations such as:

- Integration code directly mutating canonical Subscription / Entitlement lifecycle state;
- outer operational code bypassing the Application lifecycle boundary for mutation semantics;
- Integration code directly using subscription query/persistence helpers to make lifecycle policy decisions;
- provider-specific code becoming an alternate local access state machine.

The guard must remain narrow.

It must not prohibit:

- legitimate read-side Application account/access queries;
- ORM model usage where already architecturally allowed;
- focused Infrastructure query helpers;
- tests/fixtures that legitimately inspect persisted state.

Prefer dependency/import/semantic boundary checks over exact helper-name or exact-file freezing.

Do not encode incidental implementation details.

---

### 7. API / account-read compatibility

ANY-490 Presentation/Application behavior and current account/access read paths must remain valid.

Verify relevant existing API/account-read tests for:

- subscription presentation where applicable;
- entitlement-derived access;
- account/product access behavior;
- no provider/vendor state becoming a second read-time access authority.

Do not invent a new API contract for ANY-496.

Do not modify Presentation code unless a concrete regression caused by the approved Step 9 boundary requires it.

---

### 8. Existing tests remain behavioral evidence

When adapting handoffs or architecture:

- do not weaken existing assertions to accommodate an incorrect implementation;
- do not delete/skip compatibility tests merely because retained CloudPayments is deactivated;
- retained webhook tests remain useful characterization of Step 8 → Step 9 compatibility where semantically applicable;
- update expectations only when the approved Step 9 behavior explicitly changes them.

---

### 9. Documentation

Update authoritative documentation to record the architecture that now exists.

Document explicitly:

#### Application authority

Subscription / Entitlement mutations are owned by the billing Application lifecycle boundary.

#### Access authority

Local `Entitlement` is the Payment Portal source of truth for product access.

#### Step 8 → Step 9 handoff

- Step 8 owns confirmed commercial Order / Payment / Refund truth.
- Step 9 consumes only newly applicable commercial outcomes with local lifecycle consequences.
- Step 9 does not duplicate financial ownership.

#### Idempotency

- exact semantic replay is safe;
- operation-key reuse with different semantic input fails closed.

#### Authoritative-state freshness

- normalized authoritative external subscription-state input carries explicit authoritative occurrence time;
- stale facts do not revert newer local state;
- equal-time same-state facts are safe;
- equal-time conflicting state fails closed;
- unknown/non-normalizable facts are rejected before mutation;
- legacy processing-time event timestamps are not silently promoted into authoritative ordering facts;
- freshness ordering is not a generic rule for all lifecycle commands.

#### Transactions

- outer caller owns commit/rollback;
- Application/query/persistence helpers may load/lock/flush but do not finalize the outer transaction.

#### Portal-owned lifecycles

- local free trial/manual-renewal behavior remains valid without provider subscription identity.

#### Retained direct-provider behavior

- retained CloudPayments/direct-provider code is compatibility/transitional code;
- it is deactivated from normal runtime;
- it is not the target external billing architecture.

#### Future work

- ANY-497 owns external billing command flows;
- reconciliation remains later work;
- no vendor-specific LBX/Dodo design is introduced by ANY-496.

---

## Invariants

After Step 2:

- Step 8 remains commercial authority.
- Step 9 remains Subscription / Entitlement authority.
- Integration owns normalization/handoff, not local lifecycle policy.
- no Integration-owned refund applicability decision remains.
- no duplicate access authority exists.
- retained CloudPayments remains deactivated.
- expiry processing uses the Application lifecycle boundary.
- account/read behavior remains entitlement-based.
- architecture guards protect stable ownership boundaries without freezing incidental structure.
- docs describe the code that actually exists.
- ANY-497 and reconciliation remain deferred.
- no outer commit/rollback moves into lifecycle services.

---

## Out of scope

- deleting CloudPayments;
- reactivating CloudPayments;
- external billing adapters;
- customer provisioning;
- outbound external billing command orchestration;
- provider migration;
- reconciliation;
- Platform Kernel implementation work;
- generic architecture checker redesign;
- public API redesign;
- opportunistic provider cleanup unrelated to Step 9 ownership.

---

## AI prompt

```text
Implement ONLY Step 2 of the approved ANY-496 implementation plan.

Repository baseline:
- The current branch is derived from the reviewed/accepted ANY-493 predecessor baseline.
- ANY-496 Step 1 is already complete and manually verified.
- Treat the current local Step 8 commercial transition contract and completed Step 1 lifecycle semantics as authoritative.
- Do not re-research ANY-490, ANY-493, or Step 1 broadly.

Goals:
1. Route all remaining mutation-oriented Subscription / Entitlement handoffs through the canonical billing Application lifecycle boundary.
2. Remove outer Integration ownership of refund lifecycle applicability policy.
3. Protect the ownership boundary with focused architecture/regression guards.
4. Verify existing CLI and API/account-read compatibility.
5. Document the completed Step 9 contract.

Required behavior:

Commercial handoff:
- Preserve the ANY-493 commercial transition API and semantics.
- Newly applicable paid commercial outcomes may invoke the Step 9 paid-period lifecycle transition.
- Newly confirmed refunds must delegate to the Step 9 Application refund transition.
- Integration must not query Subscription persistence to decide whether a refund has an access/lifecycle consequence.
- Remove retained helper/policy equivalent to refund_lifecycle_applies(...) if it still exists.

Transactions:
- Preserve the existing retained webhook two-transaction compatibility behavior.
- Keep commercial + lifecycle effects in the existing caller-owned processing transaction.
- Preserve already committed durable receipt if downstream lifecycle processing fails.
- Do not add commit/rollback inside Application lifecycle helpers.
- Do not put external network I/O inside an open DB transaction.

Expiry CLI:
- Verify the existing expiry command.
- If it already constructs/calls the canonical Application lifecycle boundary and owns the outer transaction correctly, leave it unchanged.
- Do not make cosmetic changes solely to touch the file.

Architecture guard:
- Add the minimum stable guard that prevents Integration/outer operational layers from directly owning Subscription/Entitlement mutation or lifecycle policy.
- Prevent direct use of subscription query/persistence mechanics from Integration when used to decide lifecycle mutation policy.
- Do not block legitimate read-side Application account/access queries.
- Do not freeze exact helper names, function signatures, type annotations, or incidental file layout.

API/account reads:
- Preserve existing ANY-490 Presentation/Application behavior.
- Verify relevant existing API/account-read tests for subscription/entitlement/account access behavior.
- Access must continue to be derived from local Entitlements, not provider/vendor state.
- Do not invent a new public API contract.

Test discipline:
- Existing tests are behavioral evidence.
- Do not weaken, delete, skip, or broadly rewrite assertions merely to make the implementation pass.
- Retained CloudPayments webhook tests remain valid characterization where they still cover supported compatibility semantics.
- Change existing expectations only when the approved ANY-496 semantics explicitly require it.
- Add focused regression coverage for the handoff/ownership rule where needed.

Documentation:
Update the relevant architecture/reliability documentation to describe:
- billing Application ownership of Subscription/Entitlement transitions;
- Entitlement as local access source of truth;
- ANY-493 Step 8 -> ANY-496 Step 9 handoff;
- commercial truth vs local access/lifecycle consequences;
- semantic idempotency behavior;
- authoritative occurred_at stale/reordered/equal-time/unknown rules;
- caller-owned transaction boundaries;
- trial/manual access without provider subscription;
- retained CloudPayments/direct-provider code as deactivated compatibility code;
- ANY-497 external billing command flows and reconciliation as future work.

Review ADR-0004 only for contradiction. Change it only if the completed implementation materially conflicts with current normative text and clarification is required.

Constraints:
- Do not redesign Step 8.
- Do not implement ANY-497.
- Do not implement reconciliation.
- Do not delete or reactivate CloudPayments.
- Do not redesign Platform Kernel.
- Do not introduce generic repositories, Unit of Work, or broad architecture frameworks.
- Do not perform broad repository research.
- Inspect only directly relevant current files and tests needed for this step.
- No unrelated refactoring.

Execution constraints:
- DO NOT run tests, linters, formatters, builds, or verification commands.
- Do not stage or commit changes.

If a material contradiction is found with the approved plan, current Step 1 semantics, or ANY-493 handoff, stop and report it before improvising a redesign.

When finished, report:
1. changed files;
2. concise implementation summary;
3. exact outer handoff and architecture-guard behavior;
4. relevant API/account-read test files identified;
5. documentation updated;
6. exact manual verification commands I should run.
```

---

## Manual verification

### Architecture guard

```bash
(cd apps/api && uv run pytest tests/test_architecture.py -q)
```

### Retained Step 8 → Step 9 webhook compatibility

```bash
(cd apps/api && uv run pytest tests/test_cloudpayments_webhook_postgres.py -q)
```

### Expiry command

```bash
(cd apps/api && uv run pytest tests/test_expire_subscriptions_cli.py -q)
```

### API / account-read compatibility

Run the relevant existing API/account-read test file(s) identified by Codex from the current repository.

Do not invent test filenames in advance if the actual baseline names differ.

The verification must cover, where existing tests already provide it:

- account access derived from Entitlements;
- subscription/account presentation behavior;
- no provider state becoming a second access authority.

---

## Final focused verification

After Step 2 implementation and documentation are complete, run:

```bash
(cd apps/api && uv run pytest \
  tests/test_billing_lifecycle.py \
  tests/test_billing_lifecycle_concurrency_postgres.py \
  tests/test_commercial_transitions.py \
  tests/test_commercial_transitions_postgres.py \
  tests/test_cloudpayments_webhook_postgres.py \
  tests/test_expire_subscriptions_cli.py \
  tests/test_architecture.py \
  -q)
```

Then run the relevant existing API/account-read test file(s) identified from the current repository.

Finally run the repository quality gate:

```bash
python scripts/repo.py check
```

Before final verification / final merge:

1. synchronize any later accepted ANY-493 delta into ANY-496;
2. inspect only the affected Step 8 → Step 9 assumptions;
3. rerun affected focused tests if the predecessor delta touched relevant behavior;
4. do not restart broad research if the predecessor delta is irrelevant.

---

## Expected completion

Payment Portal has one documented, test-protected, provider-neutral Application transition boundary for local Subscription projections and Entitlement consequences.

All supported mutation triggers converge through that boundary.

Commercial ownership remains with ANY-493.

Access ownership remains with local Entitlements.

Outer integrations/jobs do not own a competing lifecycle state machine.

---

## Proposed commit

```text
refactor(billing): enforce subscription transition ownership
```

If documentation is intentionally committed separately after the implementation portion of this same step, an optional second commit is acceptable:

```text
docs(billing): document subscription transition authority
```

Do not create a separate implementation step solely for that documentation commit.

---

# Explicitly deferred scope

The following must not be implemented in ANY-496:

- ANY-497 external billing command flows;
- LBX/Dodo or other vendor-specific integration design;
- external customer/subscription command execution;
- external command result persistence architecture;
- provider polling;
- reconciliation;
- provider migration/coexistence framework;
- CloudPayments deletion;
- CloudPayments reactivation;
- Platform Kernel implementation changes;
- new public entitlement-management APIs;
- repository-per-table abstractions;
- generic Unit of Work;
- generic lifecycle dispatcher;
- generic event-sourcing framework;
- broad Application/Domain model rewrite;
- opportunistic cleanup of retained provider code unrelated to Step 9 ownership.

---

# Final plan validation

Before considering ANY-496 complete, verify the implementation against all sections below.

## Scope and inheritance

- ANY-496 began from the reviewed/accepted ANY-493 head.
- A merged-main ANY-493 baseline was not required to begin implementation.
- Before final ANY-496 verification/merge, any later accepted ANY-493 delta was synchronized.
- Only affected Step 8 → Step 9 assumptions were revalidated after synchronization.
- ANY-490 and earlier ANY-407 work were treated as completed baseline.
- No Step 7 or Step 8 functionality was reimplemented.
- No ANY-497 or reconciliation scope was pulled forward.

---

## Application ownership

- There is one canonical Application-owned semantic path for supported Subscription / Entitlement mutations.
- Existing lifecycle components were evolved rather than replaced by a parallel abstraction.
- Outer Presentation / Integration / operational code delegates lifecycle policy inward.
- Existing correct lifecycle behavior was preserved unless an explicitly justified Step 9 correction was required.

---

## Access authority

- Local Entitlement remains the only Payment Portal access source of truth.
- Provider/vendor subscription state does not directly grant/revoke access.
- Payment state does not directly become access state.
- Platform Kernel / consumers continue deriving access from local Entitlement state only.

---

## Step 8 → Step 9 separation

- ANY-493 retains Order / Payment / Refund financial/commercial ownership.
- ANY-496 owns Subscription / Entitlement consequences.
- Newly applicable commercial outcomes feed Step 9 through a clear Application handoff.
- Integration no longer decides refund lifecycle applicability.
- Step 9 does not duplicate financial ownership.

---

## Lifecycle contract

- Application-facing authoritative subscription-state vocabulary is provider/vendor-neutral.
- Explicit operation-specific commands/functions remain.
- No generic lifecycle dispatcher was introduced.
- Portal trial/manual lifecycle remains possible without provider subscription identity.

---

## Idempotency

- Exact semantic replay is idempotent.
- Same operation key with different semantic input fails closed.
- Replays do not duplicate lifecycle events, entitlement periods, grants, revocations, expirations, or other business effects.
- Concurrent exact retries preserve the same semantic result.

---

## Authoritative-state ordering

- authoritative external state carries explicit timezone-aware `occurred_at`;
- stale normalized state is a safe no-op;
- equal-time same-target input is safe;
- equal-time conflicting target fails closed;
- newer valid authoritative state goes through the existing transition graph;
- unknown/unsupported/non-normalizable state is rejected before mutation;
- terminal state cannot be resurrected by stale/reordered input;
- processing/receipt/arrival/`updated_at` timestamps are not freshness authority;
- legacy processing-time lifecycle events are not silently treated as authoritative ordering facts.

---

## Refund semantics

- commercial refund truth remains Step 8-owned;
- local refund lifecycle consequence is Step 9-owned;
- Integration does not decide lifecycle applicability;
- legitimate no-consequence cases are represented safely;
- inconsistent required lifecycle correlation fails closed;
- existing partial/full refund and access semantics are preserved;
- refund cannot resurrect expired/revoked access.

---

## Transaction and persistence boundaries

- caller owns the outer transaction;
- Application/query/persistence helpers do not commit or roll back it;
- focused existing query/locking infrastructure is reused;
- no external network call is introduced into an open business DB transaction;
- no repository-per-table abstraction was introduced;
- no generic Unit of Work was introduced;
- no unnecessary schema migration was introduced.

---

## Concurrency

- identical concurrent retries converge;
- no avoidable IntegrityError/500 is exposed for a valid exact retry;
- stale/newer races cannot regress the final lifecycle state;
- equal-time conflicts fail safely;
- duplicate/overlapping entitlement effects are not introduced by concurrency;
- relevant PostgreSQL concurrency coverage exists.

---

## Compatibility

- trial remains valid without Order/Payment/provider subscription;
- existing paid activation semantics remain intact;
- existing replacement/supersession/carry-forward semantics remain intact;
- existing renewal behavior remains intact;
- cancellation/expiration semantics remain intact;
- existing refund semantics remain intact;
- retained CloudPayments remains deactivated from normal runtime;
- retained compatibility tests remain valid where semantically applicable.

---

## API / account reads

- existing Presentation/Application behavior from ANY-490 remains intact;
- relevant API/account-read tests pass;
- account/product access remains derived from local Entitlement state;
- provider/vendor state was not introduced as a second read-time access source.

---

## Architecture protection

- architecture guards prevent outer-layer lifecycle mutation/policy bypass;
- guards do not block legitimate read-side Application behavior;
- guards protect stable semantic ownership rather than exact helper signatures or incidental file layout.

---

## Documentation

- `ARCHITECTURE.md` describes the final Step 9 ownership.
- billing authority docs distinguish commercial truth from local access consequences.
- reliability docs describe retry/freshness/conflict behavior where operationally relevant.
- docs record caller-owned transaction semantics.
- docs record CloudPayments as retained/deactivated compatibility code.
- docs identify ANY-497 and reconciliation as later work.
- no speculative LBX/Dodo contract was introduced.

---

# Recommended execution order

Execute strictly sequentially:

```text
Step 1
  ↓
manual verification
  ↓
Step 2
  ↓
final verification
```

Do not split either step into separate implementation runs merely because a sub-change is small.

Within each step, Codex may organize edits internally in the order required by dependencies, but the user-facing execution unit remains the complete step.

Do not parallelize the two steps.
