# ANY-505 — External Billing Architecture Authority Chain

## Plan Overview

| Field | Value |
| --- | --- |
| Parent program | `ANY-504` |
| Ticket | `ANY-505` |
| Program step | Step 1 — Canonical architecture/docs authority |
| Overall status | `done` |
| Implementation type | Documentation + repository documentation guard only |
| Runtime impact | None |
| Database / migrations impact | None |
| Frontend impact | None |
| Steps / proposed commits | 5 |
| Execution order | Sequential only: Step 1 → manual verification → commit → Step 2 → ... → Step 5 |
| Final quality gate | `npm run check:fast` |

## How to Use This Plan

Execute the steps strictly in order.

For each step:

1. Give the execution model only that step's **AI prompt**.
2. Let it inspect only the directly relevant files needed to verify the assumptions in the prompt.
3. Review the resulting diff.
4. Run the **Manual verification** commands yourself.
5. If the result is correct, create the proposed commit manually.
6. Continue to the next step.

Do not ask the execution model to implement multiple steps together.

The implementation model must not repeat the broad architecture/repository research already performed for this plan.

---

# Authoritative Baseline

This plan was researched against the current `payments-portal` repository and current Linear state for `ANY-505`, `ANY-504`, the relevant `ANY-407` history, and canceled `ANY-497`.

The authority model for this work is:

1. `ANY-504` is authoritative for the **current implementation sequence** of the RU external-billing program.
2. The new ADR introduced by this ticket will be the durable **architectural decision and precedence** entry point.
3. `docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md` is the detailed target implementation baseline for external billing.
4. `docs/superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md` is the detailed target implementation baseline for the Portal ↔ Kernel contract.
5. Existing billing ADRs, architecture documents, persisted models, CloudPayments code, and historical plans remain useful only for current-state characterization or retained history where explicitly marked.

`ANY-407` Steps 1–9 remain the engineering foundation. Its old Steps 10–13 are no longer the executable implementation program. `ANY-497` is canceled and must not be treated as the target external-billing implementation plan.

## Locked target ownership

For new billing development:

- External Billing owns commercial billing truth and commercial billing lifecycle.
- Payment Portal owns AnyToolAI identity and legal acceptance, the external-billing anti-corruption/projection/reconciliation/recovery boundary, immutable commercial-to-technical mapping where required by the accepted designs, and provider-neutral paid-access projection/delivery.
- Platform Kernel owns technical `product_id` / `metric_key`, actual usage, remaining quota, runtime quota enforcement, and execution.
- External Billing is not a `PaymentProviderAdapter` and must never be registered in `PaymentProviderRegistry`.
- Payment Portal is not the target payment orchestrator and must not derive paid access from payment-specific command success, browser callbacks, or arbitrary payment state.
- Provider-specific semantics terminate at the Integration boundary.
- Provider-dependent production semantics remain gated by LBX Phase 0 evidence.

## Execution-order decision

The earlier external-billing design contains historical wording that places clean persistence removal after LBX Phase 0.

`ANY-504` intentionally changes only that implementation ordering:

- provider-independent Steps 1–4 may execute before access to the LBX demo/test stand;
- clean pre-production replacement/removal of the superseded Portal-owned commerce / CloudPayments persistence and runtime may occur before Phase 0;
- unverified LBX-specific facts must not become production truth before Phase 0;
- Phase 0 remains the hard gate for production LBX integration, Widget behavior, provider-derived paid access, and launch-critical provider semantics.

The historical implementation-order section of the design must not be rewritten solely to mirror the current program sequence. `ANY-504` is authoritative for execution order, while the design remains authoritative for target architecture and provider-contract requirements. However, once the design is accepted it must not leave old Phase 0 ordering statements looking normative: add a concise explicit note in the relevant implementation-order/gating area that provider-independent pre-production cleanup ordering is superseded by `ANY-504`, while Phase 0 remains authoritative as the gate for provider-dependent production semantics and launch. The design is otherwise changed only where actual architectural or provider-contract contradictions must be corrected, including the known GitHub issue #112 findings.

---

# Research Findings

## Existing target specifications are not formally accepted yet

Both target specifications currently use a `review requested ...` status while older ADRs remain `accepted` and older architecture documents remain `normative`.

That creates the exact formal ambiguity described by `ANY-505`.

The status of both target specs must therefore become:

```text
Status: accepted implementation baseline
```

or an equivalent unambiguous canonical status.

## Known GitHub issue #112 findings must be resolved before acceptance

The external-billing design still requires targeted corrections before it can become an accepted baseline.

### Widget identity

The design must not assert:

```text
users.outer_id = Widget ident with ident_type=0
```

The stable architectural invariant is:

```text
billing_customer_key = users.outer_id
```

The exact Widget `ident_type` remains a Phase 0 provider-contract gate.

Current Swagger evidence makes `ident_type=6` a candidate for a unique external-system identifier, but it must not be promoted to confirmed production truth before real-stand evidence.

### Widget authorization

Widget presentation controls such as create/edit disable flags are not server-side authorization.

The design must retain explicit hostile direct client-API probes covering unauthorized creation/mutation and other launch-critical operations. The test must establish the actual server-side privilege boundary of the Widget credential.

### Widget credential lifetime

The architecture may require a bounded Widget credential lifetime, but the acceptable maximum lifetime and remint-overlap policy have not been approved numerically.

`ANY-505` must not invent that value.

The design must instead require that an explicit acceptable maximum and overlap policy are approved before the relevant Phase 0 probe, and that the probe produces deterministic PASS/FAIL evidence.

### Subscription discovery

The current documentation must not assume ordinary pagination or page-size semantics that are not part of the observed contract.

Phase 0 must validate the actual deployed list/discovery semantics, completeness and visibility behavior. Pagination must be tested only if it actually exists on the deployed provider contract.

### Portal ↔ Kernel design

The Portal ↔ Kernel design is intentionally provider-neutral.

LBX Widget identity, LBX credentials, `ident_type`, LBX subscription IDs, and other issue #112 provider semantics must not leak into it.

## Existing repository guard is reusable

`scripts/repo.py` already owns documentation consistency through:

- `CORE_AUTHORITY_LINKS`;
- `check_knowledge_hierarchy()`;
- `check_docs()`;
- `npm run docs:check`;
- `npm run check:fast`.

`apps/api/tests/test_repository_docs.py` already tests the documentation graph.

Therefore this ticket must extend this existing mechanism rather than introducing another checker, framework, CI job, or architecture-test subsystem.

## Existing documentation tests encode the old authority graph

`apps/api/tests/test_repository_docs.py` currently treats, among other things:

- `billing-authority.md`;
- ADR 0004;
- the old billing-authority link graph

as target architecture.

Those assertions must be migrated to the new authority graph. Still-valid generic safety assertions should not be deleted merely because their old document became historical.

## `payment-portal-data-model.md` must remain usable as current-state documentation

`check_docs()` currently verifies that every implemented ORM metadata table appears in `payment-portal-data-model.md`.

Therefore `ANY-505` must not delete its implemented table inventory or replace it with the future persistence design.

It becomes:

> authoritative/current-state schema characterization, but **not** target external-billing persistence design.

The target physical persistence redesign belongs to the next `ANY-504` step.

## Nested agent instructions also expose the old authority

`apps/api/AGENTS.md` currently explicitly tells backend agents to read:

- `payment-providers.md`;
- `billing-authority.md`;
- the current data-model document

before backend work.

The root `AGENTS.md` alone is therefore insufficient to guarantee that a backend coding agent receives the correct target architecture.

`apps/api/AGENTS.md` must also route new billing development through ADR 0005 and the accepted design specs, while retaining legacy docs only as current-state references.

## Repository entry points require alignment

The following entry points currently lead readers into the old architecture graph or old planned contract:

- `README.md`;
- `docs/README.md`;
- `ARCHITECTURE.md`;
- `apps/api/AGENTS.md`;
- root `AGENTS.md`.

`ARCHITECTURE.md` also contains a now-stale reference to `ANY-497` as the future external-billing command-flow owner. `ANY-497` is canceled and the executable program is now `ANY-504`.

## Active execution-plan inventory

The following active plans materially encode the superseded target and must move to retained/superseded history:

- `ANY-165-payment-provider-boundary.md`;
- `ANY-166-cloudpayments-browser-checkout-adapter.md`;
- `ANY-167-cloudpayments-notification-adapter.md`;
- `ANY-78-subscriptions-entitlements.md`.

`ANY-78` is important: it explicitly establishes the old local Subscription/Entitlement lifecycle as the boundary for later CloudPayments recurring integration.

Other active infrastructure plans may mention CloudPayments as current-state evidence but do not define Portal-managed payment orchestration as the future target. They must not be moved merely because they contain the word `CloudPayments`.

`ANY-76-refund-result-status.md` records completed/current behavior around the retained payment-result path rather than defining a future architectural direction. General cleanup of its stale `active` placement is not required for `ANY-505`.

---

# Global Out of Scope

Do not change any of the following in this ticket:

- `apps/api/app/**` runtime behavior;
- API contracts;
- ORM entities;
- persisted semantics;
- Alembic migrations;
- database schema;
- frontend runtime or UI;
- CloudPayments runtime implementation;
- LBX client or adapter implementation;
- Widget/JWT runtime integration;
- webhook processing;
- reconciliation runtime;
- paid-access runtime projection;
- Portal ↔ Kernel runtime APIs;
- actual clean schema reset/removal;
- the future persistence design owned by the next `ANY-504` step.

Repository documentation tooling and its tests are in scope because the ticket explicitly requires an automated documentation-precedence guard.

## Global documentation constraint

All engineering Markdown added or modified by this ticket must remain English. Do not copy Russian wording from Linear into repository documentation. This preserves the existing `docs:check` invariant that engineering Markdown contains no Cyrillic text.

---

# Step 1 — Establish the canonical target decision and accept the design baselines

**Status:** `done`

## Goal

Atomically establish the new formal target architecture authority:

- correct the known external-billing design contradictions/findings;
- accept both target design specs;
- add ADR 0005;
- supersede ADR 0002 and ADR 0004 for new billing development;
- update the ADR index and the relevant ADR 0001 amendment pointer without changing unrelated contour decisions.

After this step, the repository must no longer contain competing `accepted` ADRs claiming incompatible target billing semantics.

## Scope / affected code

Primary files:

- `docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md`
- `docs/superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md`
- `docs/architecture/decisions/0005-external-billing-boundary.md` — new
- `docs/architecture/decisions/0002-plan-based-checkout-identity.md`
- `docs/architecture/decisions/0004-billing-authority-and-consistency.md`
- `docs/architecture/decisions/0001-multi-contour-billing.md` — only if needed to route its existing amendment note to ADR 0005
- `docs/architecture/decisions/README.md`

No runtime files.

## Implementation decisions

1. Set both 2026-09-15 specs to an unambiguous accepted baseline status.

2. In the external-billing design, resolve the known issue #112 documentation findings without fabricating provider evidence:
   - preserve `billing_customer_key = users.outer_id`;
   - remove `ident_type=0` as an asserted mapping;
   - describe `ident_type=6` only as the currently identified candidate pending Phase 0 confirmation;
   - make exact `ident_type` a deterministic Phase 0 gate;
   - explicitly distinguish Widget UI/presentation flags from provider-enforced server authorization;
   - retain hostile direct client-API authorization probes;
   - require an explicitly approved maximum Widget credential lifetime and remint-overlap policy before the relevant probe, without inventing the numerical value in this ticket;
   - remove assumptions that subscription discovery has pagination/page-size;
   - require verification of the actual deployed list/discovery semantics and completeness/visibility behavior;
   - only test pagination if the deployed provider actually exposes it.

3. Do not rewrite the external-billing design's historical implementation-order section solely to match the current `ANY-504` sequence.
   - `ANY-504` controls the current implementation sequence;
   - the design remains authoritative for target architecture and provider-contract requirements;
   - add a concise explicit note in the design's relevant implementation-order/gating area that any older requirement to delay provider-independent pre-production cleanup until Phase 0 PASS is superseded for execution ordering by `ANY-504`;
   - the same note must preserve Phase 0 as the hard gate for provider-dependent production semantics, Widget/LBX production behavior and launch;
   - ADR 0005 and repository authority/navigation must reinforce this precedence;
   - otherwise edit the design only where an actual architecture/provider-contract contradiction must be corrected, including the known GitHub issue #112 findings.

4. Keep the Portal ↔ Kernel design provider-neutral. Do not add LBX Widget/security/identity semantics to it.

5. Add `ADR 0005` as a short decision/precedence ADR. It must record, without duplicating the large specs:
   - `Status: accepted`;
   - External Billing commercial authority;
   - Portal identity/legal/external-billing boundary/paid-access projection authority;
   - Kernel technical vocabulary/usage/quota authority;
   - External Billing is not `PaymentProviderAdapter` / `PaymentProviderRegistry`;
   - Portal is not the target payment orchestrator;
   - the two 2026-09-15 specs are the normative implementation baselines;
   - new target development follows ADR 0005 + those specs;
   - conflicting target semantics in ADR 0002 / ADR 0004 and related legacy docs are superseded;
   - retained implementation remains available until its later gated removal;
   - provider-independent pre-production cleanup may precede Phase 0, while provider-dependent production semantics remain gated.

6. Change ADR 0002 and ADR 0004 status/intro so they are explicitly superseded **for new billing development** by ADR 0005.
   - Preserve their bodies as historical/current-state decision context.
   - Do not rewrite their historical decisions as though they never existed.

7. Preserve ADR 0001's still-valid contour isolation / Region Resolver decisions.
   - Its existing ADR 0004 amendment pointer must not leave ADR 0004 looking like the current external-billing authority.
   - Add/adjust only enough context to route current external-billing target semantics to ADR 0005.

8. Update the decision index:
   - add ADR 0005;
   - make the supersession of 0002/0004 visible;
   - make ADR 0005 the obvious target billing entry point.

## Invariants

- Known provider facts are not invented.
- `ident_type=6` is not presented as `CONFIRMED_ON_TEST`.
- The lack of a real LBX stand does not keep the architecture baseline in `review requested`.
- Test-dependent provider assumptions remain explicit gates.
- Portal ↔ Kernel remains provider-neutral.
- ADR 0001's unrelated contour-isolation decisions remain accepted.
- No runtime or persisted semantics change.
- `ANY-504` controls sequence; the accepted specs control architecture/provider requirements.

## Out of scope

- Reclassifying the larger legacy architecture documents — Step 2.
- Rewriting `AGENTS.md` / `ARCHITECTURE.md` / repository entry points — Step 3.
- Moving exec plans — Step 4.
- Adding or changing the automated guard — Step 5.
- Resolving Phase 0 questions with guessed provider values.
- Runtime implementation of any accepted design.

## AI prompt

Implement only Step 1 of the approved ANY-505 implementation plan: establish the canonical external-billing decision and accept the two target design baselines.

Follow the decisions in this prompt exactly. Do not perform broad repository research or redesign the architecture. Keep all engineering Markdown added or modified by this step in English; do not copy Russian wording from Linear into repository docs. You may inspect only these directly relevant current files, plus immediately adjacent sections needed to preserve their existing structure:

- `docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md`
- `docs/superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md`
- `docs/architecture/decisions/0001-multi-contour-billing.md`
- `docs/architecture/decisions/0002-plan-based-checkout-identity.md`
- `docs/architecture/decisions/0004-billing-authority-and-consistency.md`
- `docs/architecture/decisions/README.md`

Create:

- `docs/architecture/decisions/0005-external-billing-boundary.md`

Required implementation:

1. Change both 2026-09-15 design specs from their current review status to `Status: accepted implementation baseline` or an exactly equivalent canonical status.
2. Before accepting the external-billing design, resolve the known documentation findings represented by GitHub issue #112:
   - keep the architectural identity invariant `billing_customer_key = users.outer_id`;
   - remove the claim that Widget `ident_type=0` is the required mapping;
   - describe `ident_type=6` only as the currently identified candidate pending real-stand confirmation;
   - make the exact Widget identity type a Phase 0 PASS/FAIL gate;
   - make clear that Widget presentation flags are not server-side authorization and retain hostile direct client-API authorization probes;
   - require an explicitly approved acceptable maximum Widget credential lifetime and remint-overlap policy before the relevant probe, but do not invent a duration;
   - do not assume subscription-list pagination/page-size; require tests of the actual deployed list/discovery semantics and only test pagination if the deployed contract actually exposes it.
3. Do not rewrite the historical execution-order section of the external-billing design solely to mirror `ANY-504`. Preserve it as historical design context, but add a concise explicit note in the relevant implementation-order/gating area so an accepted design cannot be read as still prohibiting the current Step 4 ordering: `ANY-504` is the implementation-sequence authority and supersedes older ordering that delayed provider-independent pre-production cleanup until Phase 0 PASS. The design remains authoritative for target architecture and provider-contract requirements, and Phase 0 remains the hard gate for provider-dependent production semantics, Widget/LBX production behavior and launch. Reinforce the same precedence through ADR 0005 and repository navigation. Otherwise edit the design only where actual architectural/provider-contract contradictions must be corrected, including the known GitHub issue #112 findings.
4. Keep `2026-09-15-portal-kernel-access-contract-design.md` provider-neutral. Do not copy LBX Widget identity, credential, subscription-discovery, or other vendor-specific findings into it.
5. Add a concise accepted ADR 0005 that records the durable ownership and precedence decision without duplicating either design spec:
   - External Billing owns commercial billing truth/lifecycle;
   - Payment Portal owns AnyToolAI identity/legal acceptance, the external-billing anti-corruption/projection/reconciliation/recovery boundary and provider-neutral paid-access projection/delivery;
   - Platform Kernel owns technical product/metric vocabulary, actual usage and quota enforcement;
   - External Billing is never a `PaymentProviderAdapter` and is never registered in `PaymentProviderRegistry`;
   - Payment Portal is not the target payment orchestrator;
   - the two 2026-09-15 design specs are the normative implementation baselines;
   - conflicting target semantics in ADR 0002 / ADR 0004 and related legacy documentation are superseded;
   - retained legacy implementation remains until later controlled cleanup;
   - provider-independent pre-production cleanup may precede Phase 0 while provider-dependent production semantics remain gated.
6. Mark ADR 0002 and ADR 0004 as superseded for new billing development by ADR 0005 and add explicit links to ADR 0005. Preserve their historical body/context rather than rewriting history.
7. Preserve ADR 0001's contour-isolation and Region Resolver decisions. Adjust its existing amendment note only as needed so it does not route current external-billing target semantics exclusively through superseded ADR 0004.
8. Update the ADR index with ADR 0005 and visible supersession annotations for ADR 0002 and ADR 0004.

Do not perform unrelated documentation cleanup. Do not modify runtime Python/API code, frontend code, database models, migrations, generated documentation, or future ANY-504 implementation steps.

Do not run tests, linters, formatters, documentation checks, generators, `npm run check`, `npm run check:fast`, or any other automated verification commands.

Do not stage files and do not create commits.

After implementation:
- report the changed files;
- briefly summarize the authority/precedence changes;
- identify the Phase 0 assumptions that remain intentionally unconfirmed;
- report the exact verification commands I should run manually.

If the current files materially contradict an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
npm run docs:check
```

Then manually inspect the diff and confirm that no provider-dependent candidate was promoted to confirmed production truth.

## Expected completion

- ADR 0005 exists and is accepted.
- Both target specs are accepted implementation baselines.
- The accepted external-billing design explicitly marks older Phase 0 cleanup-order wording as superseded for execution sequencing by `ANY-504`, while preserving Phase 0 as the gate for provider-dependent production semantics and launch.
- Known issue #112 documentation errors are corrected.
- Remaining provider-dependent uncertainty is expressed as Phase 0 gates.
- ADR 0002 and ADR 0004 no longer compete as accepted target billing authority.
- ADR 0001 still preserves its unrelated accepted contour decisions.
- The ADR index exposes the new authority unambiguously.

## Proposed commit

`docs(architecture): establish external billing authority`

---

# Step 2 — Reclassify retained legacy architecture documents

**Status:** `done`

## Goal

Keep the current implementation documentation available for characterization while making it impossible to mistake it for target billing architecture.

## Scope / affected code

Primary files:

- `docs/architecture/billing-authority.md`
- `docs/architecture/payment-providers.md`
- `docs/architecture/platform-kernel-contract.md`
- `docs/architecture/payment-portal-data-model.md`

No runtime files.

## Implementation decisions

1. `billing-authority.md`
   - reclassify from normative target architecture to historical/superseded target architecture;
   - add a prominent warning near the top;
   - link ADR 0005 and the target specs;
   - preserve the body as historical/current-state context unless a small wording change is necessary to remove a current normative claim.

2. `payment-providers.md`
   - explicitly mark as:
     `LEGACY / TRANSITIONAL REFERENCE — NOT TARGET ARCHITECTURE`;
   - preserve its value as characterization of the retained direct-provider boundary;
   - state that it must not be extended for LBX/external billing;
   - point to ADR 0005 and the external-billing design.

3. `platform-kernel-contract.md`
   - mark as superseded by the accepted Portal ↔ Kernel access-contract design;
   - retain it only as historical planned-contract context;
   - link ADR 0005 and the new contract design.

4. `payment-portal-data-model.md`
   - reclassify as an authoritative **current-state schema reference**, not target external-billing persistence design;
   - retain the implemented table inventory and current ORM semantics;
   - link ADR 0005 and the target external-billing design;
   - make clear that the next `ANY-504` persistence step owns the future physical-model/reset design.

5. Every warning must distinguish:
   - current/retained implementation facts;
   - target architecture;
   - future cleanup.

6. Do not rewrite legacy bodies merely to make them look like the new design. Their purpose after this step is characterization/history.

## Invariants

- Current implementation remains understandable before destructive cleanup.
- Every implemented ORM table remains documented in `payment-portal-data-model.md`.
- Legacy direct-provider behavior remains available for characterization.
- No legacy document can reasonably be interpreted as the authority for new external-billing code.
- New target semantics come only from ADR 0005 and the accepted specs.
- No runtime behavior changes.

## Out of scope

- Rewriting repository navigation or agent instructions — Step 3.
- Moving exec plans — Step 4.
- Automated enforcement — Step 5.
- Designing the future schema.
- Removing legacy implementation.

## AI prompt

Implement only Step 2 of the approved ANY-505 implementation plan: reclassify the retained legacy architecture documents without deleting their current-state/historical information.

Follow the decisions in this prompt exactly. Do not perform broad repository research. Keep all engineering Markdown added or modified by this step in English; do not copy Russian wording from Linear into repository docs. Inspect only these directly relevant files and the ADR/spec links created by completed Step 1 if needed to verify paths:

- `docs/architecture/billing-authority.md`
- `docs/architecture/payment-providers.md`
- `docs/architecture/platform-kernel-contract.md`
- `docs/architecture/payment-portal-data-model.md`
- `docs/architecture/decisions/0005-external-billing-boundary.md`
- the two accepted 2026-09-15 design specs

Required implementation:

- Reclassify `billing-authority.md` as a superseded target-architecture / historical-current-state reference and add a prominent warning that new billing development follows ADR 0005 and the accepted design specs.
- Mark `payment-providers.md` explicitly as `LEGACY / TRANSITIONAL REFERENCE — NOT TARGET ARCHITECTURE`. Preserve its retained direct-provider characterization, but state that it must not be extended for LBX or another external billing system.
- Mark `platform-kernel-contract.md` as superseded by the accepted Portal ↔ Kernel access-contract design and retain it only for historical context.
- Reclassify `payment-portal-data-model.md` as the current-state schema reference and explicitly state that it is not the target external-billing persistence design.
- Preserve the implemented table inventory and current-state ORM descriptions in the data-model document because repository documentation validation depends on that inventory until a later persistence step changes the actual schema.
- Add appropriate links from each legacy/current-state document to ADR 0005 and the relevant accepted design baseline(s).
- Where a legacy document contains still-useful safety/context information, keep it. Do not rewrite the historical body into the new architecture just to remove old terminology.

Do not modify repository entry-point docs, `AGENTS.md`, `ARCHITECTURE.md`, exec-plan placement, or documentation guard code in this step.

Do not modify runtime Python/API code, frontend code, database models, migrations, generated files, or any future ANY-504 implementation.

Do not run tests, linters, formatters, documentation checks, generators, `npm run check`, `npm run check:fast`, or any other automated verification commands.

Do not stage files and do not create commits.

After implementation:
- report the changed files;
- summarize how each document is now classified;
- confirm that the current implemented table inventory was preserved;
- report the exact verification commands I should run manually.

If the current code or documents materially contradict an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
npm run docs:check
```

## Expected completion

All four legacy/current-state architecture documents are still useful for understanding the repository, but each has an explicit role and direct path to the new authority chain.

## Proposed commit

`docs(architecture): classify legacy billing references`

---

# Step 3 — Align repository entry points and agent instructions

**Status:** `done`

## Goal

Make the new billing authority chain the path followed by both humans and coding agents from normal repository entry points, while preserving factual current-state descriptions.

## Scope / affected code

Primary files:

- `AGENTS.md`
- `apps/api/AGENTS.md`
- `ARCHITECTURE.md`
- `README.md`
- `docs/README.md`

`docs/AGENTS.md` should remain unchanged unless a minimal navigation adjustment is actually required after inspecting the completed Step 1–2 paths.

## Implementation decisions

### Root `AGENTS.md`

Introduce an explicit billing-specific authority order for new development:

1. ADR 0005;
2. external-billing boundary design;
3. Portal ↔ Kernel access-contract design.

Classify the old data model, provider docs, billing-authority docs, superseded ADRs, and retained plans as current-state/historical/migration references only.

Add non-negotiable rules equivalent to:

- do not extend `PaymentProviderAdapter` / CloudPayments for new external billing except explicitly scoped characterization/removal work;
- external billing never uses `PaymentProviderAdapter` / `PaymentProviderRegistry`;
- do not introduce new target commercial authority around Portal-owned Product/Plan/Order/Payment;
- do not infer target behavior from legacy documents;
- ADR 0005 + accepted design specs win on target-architecture conflict;
- provider-independent cleanup may precede Phase 0;
- provider-dependent production behavior remains Phase 0 gated.

Existing root-agent rules that present ANY-71, the retained Portal data model, or the current local Subscription/Entitlement model as target billing authority must be removed or explicitly reclassified as current-state/historical guidance. Do not leave conflicting old target rules beside the new ADR 0005 authority chain.

### `apps/api/AGENTS.md`

Because this is a more specific instruction file for backend work:

- add the same target authority navigation before legacy billing documents;
- retain current-state docs as characterization references;
- keep existing layering/error/DI/coding rules that do not conflict with the new billing target;
- avoid duplicating the entire design.

### `ARCHITECTURE.md`

Preserve the factual current system description, but separate it clearly from the target:

- CURRENT / RETAINED: implemented Products/Plans/Orders/Payments/Subscriptions/Entitlements and deactivated CloudPayments source;
- TARGET: external billing + Portal paid-access boundary + Kernel usage/quota model from ADR 0005/specs.

Also:

- make ADR 0005 the canonical target decision;
- link both accepted specs;
- remove the impression that current Portal-owned commercial objects are the future billing authority;
- remove the impression that the current local-entitlement representation is automatically the final paid-access wire model;
- replace stale ownership/reference to canceled `ANY-497` with the current architecture/program direction;
- do not describe future steps as implemented.

### `README.md`

Keep current implementation facts, but route readers to the new authority chain instead of the old `billing-authority.md` as the target architecture entry point.

Update old wording around the planned private entitlement API if it implies the superseded entitlement-check design. State only that the accepted Portal ↔ Kernel contract is the target and runtime implementation remains future program work.

### `docs/README.md`

Expose the new target billing documents prominently and classify the old billing docs by role.

Preserve its general rule that Linear issues/execution plans describe temporary implementation scope rather than durable architecture.

## Invariants

- A coding agent entering through root or backend `AGENTS.md` gets the same target answer.
- Current implementation facts are not falsely described as already migrated.
- Legacy docs remain discoverable, but clearly subordinate.
- The Portal ↔ Kernel target remains provider-neutral.
- `ARCHITECTURE.md` remains a factual current-state map rather than pretending future code already exists.
- No runtime code changes.

## Out of scope

- Rewriting product/legal/security docs without an actual contradiction.
- Changing the web agent guide unless it contains a discovered billing-authority conflict.
- Moving execution plans — Step 4.
- Adding enforcement code — Step 5.
- Implementing any target runtime architecture.

## AI prompt

Implement only Step 3 of the approved ANY-505 implementation plan: align repository entry points and coding-agent instructions with the external-billing authority chain established in Steps 1–2.

Follow the decisions defined here. Do not perform broad repository research. Keep all engineering Markdown added or modified by this step in English; do not copy Russian wording from Linear into repository docs. Inspect only the directly relevant current files:

- `AGENTS.md`
- `apps/api/AGENTS.md`
- `ARCHITECTURE.md`
- `README.md`
- `docs/README.md`

You may inspect ADR 0005, the two accepted 2026-09-15 design specs, and the legacy classification banners from Step 2 only to verify links and exact authority wording.

Required behavior:

1. In root `AGENTS.md`, make the target billing authority chain explicit for all new billing work:
   1. ADR 0005;
   2. External Billing Boundary Design;
   3. Portal ↔ Kernel Access Contract Design.
2. In root `AGENTS.md`, clearly classify the old data model, payment-provider docs, old billing-authority docs, superseded ADRs and retained historical plans as current-state/historical/migration references rather than target behavior.
3. Add concise non-negotiable billing rules:
   - no new external-billing functionality through `PaymentProviderAdapter` or `PaymentProviderRegistry`;
   - do not extend CloudPayments/direct-provider architecture for new external billing except explicitly scoped characterization/removal work;
   - do not introduce new target commercial authority based on the old Portal-owned Product/Plan/Order/Payment model;
   - legacy documents cannot override ADR 0005 or the accepted design specs;
   - provider-independent clean pre-production cleanup may occur before Phase 0;
   - provider-dependent LBX production semantics and paid-access derivation remain Phase 0 gated.
4. Remove or explicitly reclassify existing root-agent rules that still present ANY-71, the retained Portal data model, or the current local Subscription/Entitlement model as target billing authority. They may remain only as current-state/historical guidance where still useful. Do not leave contradictory target rules beside the new ADR 0005 chain.
5. Update `apps/api/AGENTS.md` because it is the backend-specific instruction file. New billing work must be routed through the same ADR/spec chain before any legacy/current-state billing documents. Preserve its valid Presentation/Application/Domain/Persistence/Integration, error, DI and coding rules.
6. Update `ARCHITECTURE.md` to distinguish `CURRENT / RETAINED` from `TARGET`. Preserve accurate current implementation facts, but make ADR 0005 and the two accepted specs the target billing references. Current Product/Plan/Order/Payment/Subscription/Entitlement code may be described as current/retained implementation, not as target commercial authority.
7. Remove or replace stale target ownership references to canceled `ANY-497`. Do not rewrite the old canceled ticket; only stop using it as current architecture direction.
8. Update `README.md` so its normal onboarding path points to the new billing authority chain. Preserve truthful current implementation statements. Do not continue advertising the old entitlement-check contract as the future Portal ↔ Kernel API.
9. Update `docs/README.md` so the new ADR/specs are obvious target billing architecture entry points and the old billing documents are labelled by their retained role.

Keep current legacy-document links where useful and where the existing documentation checker still requires them, but make their subordinate role explicit. Do not intentionally break the existing documentation checker before Step 5 updates its guard graph.

Do not perform unrelated documentation cleanup or rewrite large sections that already describe current state accurately.

Do not modify runtime Python/API code, frontend code, database schema/models, migrations, generated files, exec-plan placement, or future ANY-504 implementation.

Do not run tests, linters, formatters, documentation checks, generators, `npm run check`, `npm run check:fast`, or any other automated verification commands.

Do not stage files and do not create commits.

After implementation:
- report the changed files;
- summarize the final human/agent authority path;
- identify any retained current-state links that intentionally remain;
- report the exact verification commands I should run manually.

If the current files materially contradict an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
npm run docs:check
```

## Expected completion

Starting from either `README.md`, root `AGENTS.md`, backend `apps/api/AGENTS.md`, `docs/README.md`, or `ARCHITECTURE.md`, a developer reaches the same target architecture and cannot reasonably conclude that LBX should be implemented through the retained payment-provider architecture.

## Proposed commit

`docs(agents): align external billing authority entry points`

---

# Step 4 — Move superseded billing execution plans out of `active`

**Status:** `done`

## Goal

Make `docs/exec-plans/active/` mean what its README says: current executable work, not historical implementation direction.

Preserve useful old implementation evidence without letting it compete with the target architecture.

## Scope / affected code

Create/use:

- `docs/exec-plans/superseded/`

Move and reclassify:

- `docs/exec-plans/active/ANY-165-payment-provider-boundary.md`
- `docs/exec-plans/active/ANY-166-cloudpayments-browser-checkout-adapter.md`
- `docs/exec-plans/active/ANY-167-cloudpayments-notification-adapter.md`
- `docs/exec-plans/active/ANY-78-subscriptions-entitlements.md`

Update:

- `docs/exec-plans/README.md`
- only direct Markdown references whose relative paths break because of these moves.

## Implementation decisions

1. Add `superseded/` as an official execution-plan category.

2. Define it as retained implementation/history that must not be continued as the current target.

3. Move the four researched plans above.

4. Each moved plan must have an explicit top-level classification equivalent to:
   - superseded / retained implementation history;
   - do not continue this plan as the target billing direction;
   - implemented source may remain temporarily for characterization/gated cleanup;
   - new billing work follows ADR 0005 and the accepted external-billing designs.

   `ANY-78-subscriptions-entitlements.md` is a special case: it represents completed implementation evidence, so label it as **completed implementation history that is superseded as the target billing direction**, not as work that never happened. Preserve that distinction while moving it out of `active`.

5. Do not rewrite the historical implementation/evidence body.

6. Repair only links broken directly by moving these files.

7. Do not use a word-based search to move every plan mentioning CloudPayments.

8. Leave unrelated infrastructure plans active.

9. Do not move `ANY-76-refund-result-status.md` as part of this step merely because it describes retained current behavior. Its directory/status housekeeping is not needed to establish the new target authority.

## Invariants

- Historical implementation evidence remains available.
- No known plan that explicitly establishes the old provider/CloudPayments/subscription target remains in `active`.
- `active` plans that merely mention retained CloudPayments as current-state evidence are not incorrectly superseded.
- Documentation links remain valid.
- Runtime implementation is untouched.

## Out of scope

- Editing runtime CloudPayments code.
- Moving every old or completed-looking plan in the repository.
- General execution-plan cleanup.
- Reclassifying unrelated infrastructure plans.
- Automated guard enforcement — Step 5.

## AI prompt

Implement only Step 4 of the approved ANY-505 implementation plan: reclassify the known superseded billing execution plans as retained history.

Follow the decisions in this prompt exactly. Do not perform broad repository research. Keep all engineering Markdown added or modified by this step in English; do not copy Russian wording from Linear into repository docs.

Create `docs/exec-plans/superseded/` if it does not exist.

Move these exact plans out of `docs/exec-plans/active/`:

- `ANY-165-payment-provider-boundary.md`
- `ANY-166-cloudpayments-browser-checkout-adapter.md`
- `ANY-167-cloudpayments-notification-adapter.md`
- `ANY-78-subscriptions-entitlements.md`

For each moved plan:

- mark it as superseded / retained implementation history;
- add a concise prominent statement that the plan must not be continued as the target billing direction;
- state that already implemented source may remain temporarily for characterization and later gated cleanup;
- link new billing development to ADR 0005 and the accepted external-billing design baselines;
- preserve the historical implementation/evidence content instead of rewriting it into the new architecture.

For `ANY-78-subscriptions-entitlements.md`, explicitly preserve that it is **completed implementation history** whose architectural direction is now superseded. Do not describe it as abandoned or unimplemented work.

Update `docs/exec-plans/README.md` so:

- `active` means current work;
- `completed` means completed work/evidence;
- `superseded` means retained history from a direction that must not be continued;
- `tech-debt.md` keeps its existing role.

Inspect only directly relevant Markdown references to these four moved paths and repair links that would otherwise become broken. Do not perform general documentation cleanup.

Do not move other active plans simply because they contain the word `CloudPayments`, `Payment`, `Order`, or `Subscription`. In particular, do not reclassify unrelated infrastructure plans. Leave `ANY-76-refund-result-status.md` unchanged in this ticket unless the current file materially contradicts the researched assumption that it records retained completed/current-state behavior rather than a future architectural direction.

Do not modify runtime Python/API code, frontend code, database models, migrations, generated files, or future ANY-504 implementation.

Do not run tests, linters, formatters, documentation checks, generators, `npm run check`, `npm run check:fast`, or any other automated verification commands.

Do not stage files and do not create commits.

After implementation:
- report the moved and changed files;
- summarize why each moved plan is superseded;
- report any direct links that had to be repaired;
- report the exact verification commands I should run manually.

If the current files materially contradict an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

```bash
npm run docs:check
```

## Expected completion

The four known old billing-direction plans are absent from `active`, preserved under `superseded`, explicitly marked not to continue, and the execution-plan README formally defines the category.

## Proposed commit

`docs(plans): supersede legacy billing plans`

---

# Step 5 — Enforce the documentation precedence with the existing repository guard

**Status:** `done`

## Goal

Turn the authority chain established in Steps 1–4 into a small automated regression guard integrated with the existing repository documentation checks.

The guard must detect documentation-authority drift without attempting to ban legacy implementation vocabulary or source code.

## Scope / affected code

Primary files:

- `scripts/repo.py`
- `apps/api/tests/test_repository_docs.py`

Potentially touch documentation files from Steps 1–4 only if a new guard exposes a concrete missed link/classification defect.

Do not add a new standalone checker/framework unless the existing `scripts/repo.py` mechanism cannot express a required invariant.

## Implementation decisions

### Reuse the current documentation-check infrastructure

Extend the existing:

- `CORE_AUTHORITY_LINKS`;
- `check_knowledge_hierarchy()`;
- `check_docs()`;

with a narrowly scoped external-billing precedence check.

Prefer a helper such as:

```text
check_external_billing_documentation_precedence(...)
```

with deterministic, actionable errors and testable inputs.

The exact helper name is not an architectural invariant; reuse existing local patterns.

### Required authority links

The automated graph should enforce the new target links where they matter, including at least:

- root `AGENTS.md` → ADR 0005 + both accepted specs;
- `apps/api/AGENTS.md` → ADR 0005 + relevant accepted specs;
- `ARCHITECTURE.md` → ADR 0005 + both specs;
- `docs/README.md` → ADR 0005 + both specs;
- ADR decision index → ADR 0005;
- ADR 0002 → ADR 0005;
- ADR 0004 → ADR 0005;
- legacy billing/current-state docs → ADR 0005 and the relevant target spec(s).

`README.md` is a guarded authority/navigation entry point after Step 3. Require it to link consistently to ADR 0005 and both accepted design specs through the same authority-graph mechanism; do not leave it as an optional or special parallel check.

### Required content-state checks

The guard must verify material classification, not every sentence.

At minimum:

- ADR 0005 exists and has accepted status;
- external-billing spec is an accepted implementation baseline;
- Portal ↔ Kernel spec is an accepted implementation baseline;
- ADR 0002 is marked superseded for new billing development;
- ADR 0004 is marked superseded for new billing development;
- `payment-providers.md` is explicitly legacy/transitional and not target architecture;
- `payment-portal-data-model.md` is explicitly current-state and not target persistence design;
- `platform-kernel-contract.md` is superseded;
- `billing-authority.md` is no longer normative target billing architecture;
- root agent instructions expose the new priority chain;
- the four known superseded plan filenames no longer exist under `docs/exec-plans/active/`;
- the retained copies exist under `docs/exec-plans/superseded/`.

A concise stable marker vocabulary may be enforced where the marker itself is intentional repository policy.

### What the guard must NOT do

Do not fail merely because:

- `Plan`;
- `Order`;
- `Payment`;
- `Subscription`;
- `Entitlement`;
- `PaymentProviderAdapter`;
- `CloudPayments`

still exist in source code or historical/current-state documentation.

Their physical removal belongs to later `ANY-504` steps.

Do not scan runtime imports for this ticket.

### Update existing documentation tests

`apps/api/tests/test_repository_docs.py` currently protects the old authority graph.

Update the tests so that:

- ADR 0005/specs are the target;
- legacy documents are tested for classification, not treated as target architecture;
- old link-graph expectations route through ADR 0005;
- tests whose only purpose was to keep ADR 0004 / `billing-authority.md` as target are replaced;
- generic security/reliability invariants that remain valid are preserved rather than deleted indiscriminately;
- if a still-valid invariant is currently asserted by reading ADR 0004 or `billing-authority.md`, move that assertion to the new canonical source that now owns the invariant instead of preserving the superseded document as current authority.

Add focused regression tests for the new helper/guard, including useful failure messages.

### Integration

The new precedence check must run through `npm run docs:check`, and therefore through the existing `npm run check:fast` chain.

Do not add a second CI invocation if the existing path already provides enforcement.

## Invariants

- Documentation drift fails automatically.
- The guard enforces authority/classification, not implementation vocabulary.
- Retained legacy code remains legal until later cleanup.
- `payment-portal-data-model.md` continues satisfying implemented-table documentation validation.
- Existing unrelated docs tests remain valid.
- No runtime behavior changes.
- `npm run check:fast` remains the final repository gate.

## Out of scope

- Architecture import bans for old runtime code.
- Deleting old classes/models.
- New CI framework/jobs.
- Testing LBX.
- Runtime contract tests for future billing.
- Migration/schema verification.

## AI prompt

Implement only Step 5 of the approved ANY-505 implementation plan: add a focused automated documentation-precedence guard using the repository's existing documentation-check infrastructure.

Steps 1–4 are complete. Treat their authority decisions, classifications and moved-plan locations as authoritative.

Do not perform broad repository research. Keep all engineering Markdown added or modified by this step in English; do not copy Russian wording from Linear into repository docs. Inspect only:

- `scripts/repo.py`, especially `CORE_AUTHORITY_LINKS`, `check_knowledge_hierarchy()`, `check_docs()` and directly adjacent helper patterns;
- `apps/api/tests/test_repository_docs.py`, especially existing knowledge-hierarchy and billing-documentation tests;
- the final files changed by Steps 1–4 only where necessary to verify exact links/markers.

Implementation requirements:

1. Reuse the existing documentation-check path rather than introducing another checker framework or CI job.
2. Extend the authority link graph so the repository's key human/agent entry points route new billing development through:
   - ADR 0005;
   - External Billing Boundary Design;
   - Portal ↔ Kernel Access Contract Design.
3. Add a small focused precedence/classification check integrated into `check_docs()`.
4. The check must verify at minimum:
   - ADR 0005 exists and is accepted;
   - both 2026-09-15 specs are accepted implementation baselines;
   - ADR 0002 and ADR 0004 are superseded for new billing development and link to ADR 0005;
   - `billing-authority.md` is no longer normative target billing architecture;
   - `payment-providers.md` is explicitly legacy/transitional and not target architecture;
   - `payment-portal-data-model.md` is explicitly current-state and not target persistence design;
   - `platform-kernel-contract.md` is explicitly superseded;
   - root `AGENTS.md` exposes the new target authority chain;
   - `README.md` links to ADR 0005 and both accepted design specs as part of the guarded repository authority/navigation graph;
   - the known superseded plans `ANY-165-payment-provider-boundary.md`, `ANY-166-cloudpayments-browser-checkout-adapter.md`, `ANY-167-cloudpayments-notification-adapter.md`, and `ANY-78-subscriptions-entitlements.md` are absent from `docs/exec-plans/active/` and retained under `docs/exec-plans/superseded/`.
5. Produce actionable errors that identify the missing/incorrect document or classification.
6. Do not create a guard that bans the words or imports `Plan`, `Order`, `Payment`, `Subscription`, `Entitlement`, `PaymentProviderAdapter`, or `CloudPayments`. Legacy implementation remains valid characterization until later ANY-504 cleanup.
7. Update `apps/api/tests/test_repository_docs.py` so the old target-authority tests no longer treat ADR 0004 or `billing-authority.md` as the current target. Replace those expectations with the new ADR 0005/spec authority graph and legacy classifications.
8. Preserve still-valid generic reliability/security/privacy assertions, but do not keep a current architectural invariant anchored to a document that Steps 1–2 classify as historical or superseded. If such an assertion remains valid, migrate its authoritative test/source to ADR 0005, an accepted design spec, or another current normative document instead of continuing to treat `billing-authority.md` or ADR 0004 as target authority.
9. Prefer a testable helper with a configurable/root argument if that matches the existing test patterns, so focused tests can validate failure cases without manipulating the real repository.
10. Keep the change narrowly scoped to repository documentation validation.

Do not modify runtime `apps/api/app/**`, frontend runtime code, ORM models, migrations, generated files, or future ANY-504 implementation.

Do not redesign the architecture and do not perform unrelated refactoring.

Do not work on future steps.

Do not run tests, linters, formatters, documentation checks, generators, `npm run check`, `npm run check:fast`, or any other automated verification commands.

Do not stage files and do not create commits.

After implementation:
- report the changed files;
- summarize the new enforced invariants;
- identify which old documentation tests were updated and why;
- report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

## Manual verification

Run the focused documentation-test file first:

```bash
./.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_repository_docs.py
```

Run the documentation checker explicitly:

```bash
npm run docs:check
```

Run the architecture checker explicitly:

```bash
npm run architecture:check
```

Finally run the required repository fast gate:

```bash
npm run check:fast
```

## Expected completion

- The new authority chain is mechanically enforced.
- Known superseded documents/plans cannot silently regain target status.
- A future edit removing the target links or restoring one of the old active plans fails repository checks.
- Retained legacy code/vocabulary remains legal until the later cleanup step.
- The complete `ANY-505` acceptance criteria are covered without runtime, frontend, migration, or DB-schema changes.

## Proposed commit

`test(docs): guard external billing authority precedence`

---

# Final Acceptance Mapping

| ANY-505 requirement | Covered by |
| --- | --- |
| Accepted ADR 0005 | Step 1 |
| Both design specs accepted | Step 1 |
| Old Phase 0 cleanup-order wording explicitly superseded for execution sequencing by `ANY-504` | Step 1 |
| GitHub #112 documentation findings resolved | Step 1 |
| Unverified provider facts remain Phase 0 gates | Step 1 |
| Portal ↔ Kernel spec remains provider-neutral | Step 1 |
| ADR 0002 / 0004 superseded | Step 1 |
| Legacy architecture documents classified | Step 2 |
| `payment-portal-data-model.md` retained as current-state schema reference | Step 2 |
| Correct root agent priority chain | Step 3 |
| Backend-specific agent instructions cannot bypass new authority | Step 3 |
| `ARCHITECTURE.md` aligned with target/current distinction | Step 3 |
| Normal README/docs navigation leads to new target | Step 3 |
| Legacy CloudPayments/provider plans removed from `active` | Step 4 |
| `superseded` exec-plan category documented | Step 4 |
| Automated precedence guard | Step 5 |
| Relevant documentation/architecture checks pass | Step 5 manual verification |
| `npm run check:fast` passes | Step 5 final verification |
| No runtime/frontend/migration/schema changes | Invariant across all five steps |

# Explicitly Deferred to Later ANY-504 Steps

Do not pull any of the following into `ANY-505`:

- target persistence model design;
- clean Alembic/schema reset;
- removal of Product/Plan/Order/Payment/CloudPayments runtime;
- identity/session/legal runtime stabilization;
- LBX Phase 0 execution;
- LBX integration/client/Widget;
- catalog synchronization;
- `PurchaseIntent`;
- provider webhooks/reconciliation;
- grants/allowances/`AccessSnapshot`;
- access revisions/invalidation;
- Portal ↔ Kernel runtime integration;
- Kernel usage/quota enforcement;
- rewriting old Linear tickets `ANY-79` / `ANY-286` / `ANY-287`.

Those remain owned by the later sequential steps of `ANY-504`.

# Completion State

After Step 5, a developer or coding agent following normal repository instructions must arrive at:

```text
ADR 0005
    ↓
External Billing Boundary Design
    ↓
Portal ↔ Kernel Access Contract Design
    ↓
current ANY-504 implementation step
    ↓
code
```

Legacy ADRs, architecture documents, persisted models and execution plans remain available only as explicitly labelled current-state, historical or transitional evidence.

There must no longer be a valid repository-instruction path by which a developer can reasonably conclude that new LBX/external-billing work should extend `PaymentProviderAdapter`, reproduce CloudPayments-style Portal payment orchestration, or treat the retained Portal `Plan` / `Order` / `Payment` model as target commercial authority.
