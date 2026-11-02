# ANY-765 — Paid Access Projection, Allowances, Revision & Invalidation

Status: Steps 1–4 DONE (implementation); post-rebase aggregate check PASS; configured test-LBX acceptance NOT_RUN
Validation: **READY WITH GATES** — validated using the validate-plan skill
Updated: 2026-11-02
Issue: [ANY-765](https://linear.app/paveldik/issue/ANY-765)
Program: [ANY-504](https://linear.app/paveldik/issue/ANY-504)

The implementation-ready plan is preserved at
[`96e3b0c`](https://github.com/gushinets/payments-portal/blob/96e3b0c/docs/exec-plans/active/ANY-765-implementation-plan.md).
The four approved steps and execution prompts below are retained as the scope
contract. Current delivery and verification replace the superseded per-run
journals; their detailed history remains in Git through `5eb88c8`.
Implementation is published in [PR #157](https://github.com/gushinets/payments-portal/pull/157).
Implementation completion does not close the acceptance gates in Section 6.

## 1. Goal & Final Expected Outcome

After a supported purchase is linked, Portal independently consumes Step 8's
authoritative subscription observations and determines the user's paid product
access. Where the accepted purchase includes fixed metered terms, Portal
materializes exactly those allowances.

For the approved development examples:

- ProposalAI provides `proposal_ai.test_generations`, unit `generation`,
  quantity **100** per confirmed cycle.
- Brief Decoder provides `brief_decoder.test_analyses`, unit `analysis`,
  quantity **300** per confirmed cycle.

These quantities remain explicitly **SIMULATED**. Actual commercial price and
subscription lifecycle continue to come from LBX.

The completed scenario is:

1. Portal reads current LBX terms and Kernel capabilities, presents the selected
   offer and its applicable test limits, and verifies the buyer's exact accepted
   version.
2. The immutable purchase snapshot preserves those values and their provenance.
3. Step 8 independently verifies customer, seller, dedicated agreement,
   subscription, effective commercial terms, supported prepaid policy and
   lifecycle.
4. Complete eligible facts permit safe primary selection and the first effective
   paid grant/allowances.
5. Portal atomically commits the complete effective state, revision `1`, causal
   audit and pending invalidation.
6. The authenticated cabinet reads that local committed state without contacting
   LBX.
7. Blocking, termination, proven conflict or expiry removes affected access
   through the same commit path. Independent products survive.
8. Same-cycle recovery reuses allowance IDs and quantities. A proven later
   current cycle receives one new allowance per metric, including after missed
   observations; skipped periods receive nothing.
9. Repeated equal facts do not duplicate allowances or manufacture revisions.

An outage never extends the original six-hour source lease. Local deadline work
continues without provider availability. If a deadline writer is late, reads fail
closed until the reduction is committed; GET does not alter the effective set
under an existing revision.

Success requires PostgreSQL evidence, ordinary Application/API/cabinet flows,
meaningful failure/concurrency tests and a separately recorded configured
test-LBX acceptance path.

**Deferred:** Kernel AccessSnapshot HTTP delivery, invalidation networking,
cache/revision-floor enforcement, actual usage/remaining, coordinated B10 wire
changes and production rollout remain Steps 10–11.

## 2. Current State & Reusable Implementation

### Delivered baseline

- Portal branch: `ANY-765`; original four-step runtime/UI delivery at `5eb88c8`.
  The owner-requested current rebase replays all eight commits through `ac9fffe`
  onto freshly fetched `ANY-715` at `76ea1a7` (2026-11-02). Integration fix and
  current tested runtime are `aff7343`. Original delivery is retained at
  `codex/any765-before-715-refresh-ac9fffe`.
- The predecessor includes the relevant Step 7 corrections, the operations
  runbook rename and inventory/Widget/deadline regressions. Current integration
  verification below supersedes historical pre-rebase results.
- Current migration head: `20261031_0006`, following `20261028_0005`.
- Kernel source inspection on 2026-11-02: local `main` at
  `331e086ca9e0c72eb757aacc476bad5bacb5bae5`. The manifest producer is present;
  paid snapshot/invalidation endpoints remain absent from its API composition.
  Source inspection is not deployed HTTP conformance.
- Real test-LBX-to-cabinet acceptance is **NOT_RUN**. Synthetic tests and
  SIMULATED quantities do not establish production enablement.

### Implemented seams

- [Purchase acceptance](../../../apps/api/app/domains/purchases/service.py)
  pins v2 technical terms and their digest while preserving readable v1 history.
  The dev/test-only 100/300 dataset is outside the Kernel manifest.
- [Authoritative reconciliation](../../../apps/api/app/domains/billing/reconciliation.py)
  performs bounded source reads outside database transactions and applies their
  normalized proof under permanent ownership/fence checks. Preparation cannot
  authorize access.
- [Primary selection and paid commit](../../../apps/api/app/domains/billing/paid_access.py)
  use complete first-selection discovery, frozen cycle allowances and one
  user-serialized, caller-transaction revision/audit/outbox writer.
- [Paid deadlines](../../../apps/api/app/domains/billing/paid_deadlines.py)
  reuse the existing durable worker. Local reductions and deadline repair remain
  available without LBX configuration. Supported operator actions reuse fresh
  original-object proof and the same writer.
- [Customer paid read](../../../apps/api/app/domains/billing/paid_read.py) and
  [cabinet](../../../apps/web/src/features/billing/AccountBilling.tsx) expose
  committed local state independently of catalog/LBX availability, with deadline
  refusal, generated contracts and session lifetime guards.

Runtime configuration and incident handling belong to the
[purchase runbook](../../engineering/ANY-709-billing-runbook.md) and
[billing operations guide](../../engineering/billing-background-operations.md).
The [schema reference](../../architecture/payment-portal-data-model.md) owns the
as-built persistence details; the [Kernel map](../../integrations/platform-kernel.md)
owns peer evidence and remaining interface boundaries.

## 3. Architecture, Decisions & Dependencies

### 3.1 Authority and execution boundaries

Follow root and applicable subtree instructions,
[architecture](../../../ARCHITECTURE.md),
[coding conventions](../../engineering/CODING_CONVENTIONS.md),
[delivery workflow](../../engineering/AGENT_WORKFLOW.md) and
[testing strategy](../../engineering/TESTING.md). Relevant authorities are:

- [ADR 0005](../../architecture/decisions/0005-external-billing-boundary.md).
- [External Billing Boundary Design](../../superpowers/specs/2026-09-15-external-billing-boundary-design.md):
  B9–B11, allowances, primary selection, trust, deterministic boundaries and
  manual review.
- [Portal–Kernel Access Contract Design](../../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md):
  revision semantics, clock safety and outbox obligations.
- [Accepted live-source admission amendment](../../superpowers/specs/2026-10-15-live-source-commercial-admission-design-amendment.md)
  and [Phase 0 handoff](../../superpowers/phase0/2026-10-14-any-634-lbx-evidence-handoff.md).
- The inherited [Step 7 plan](../completed/ANY-709-implementation-plan.md),
  [Step 7 runbook](../../engineering/ANY-709-billing-runbook.md),
  [Step 8 delivery history](https://github.com/gushinets/payments-portal/blob/b202ad3/docs/exec-plans/completed/ANY-715-implementation-plan.md) and the current background operations runbook.
- [Kernel integration map](../../integrations/platform-kernel.md) and
  producer-owned
  [ANY-711 manifest contract](https://github.com/gushinets/anytoolai-platform/blob/e627bf296a6476efcca839a0328cf1a5683555e2/docs/contracts/kernel-capability-manifest/v1/README.md).
- [As-built schema](../../architecture/payment-portal-data-model.md),
  [security](../../SECURITY.md) and [reliability](../../RELIABILITY.md).

Apply the accepted ANY-715/765 clarification: complete supported prepaid
ACTIVE/unblocked subscription truth is the operational eligibility signal. The
retained "paid authority" wording means this verified provider conclusion
together with original ownership/terms, not an additional Portal settlement
reconstruction.

Integration alone interprets LBX codes. Application owns transactions and
orchestration; pure provider-neutral policy owns access decisions. Use canonical
ORM models and focused query/storage helpers. Do not introduce a generic
billing framework or repository per table.

Necessary normative wording alignment belongs to the reviewed implementation
change. Do not rewrite canonical decisions during planning or implement the
Step 10 wire redesign here.

### 3.2 Accepted purchase terms

The owner approved a local, explicitly enabled dev/test source for 100/300.

- Use one versioned development data fixture for the two examples, accessible
  to API development composition and mock documentation without importing
  mock-server code into Portal.
- Include source version, content digest, `SIMULATED` provenance, product,
  metric, unit and strict integer quantity. Bind selected terms to the exact
  reviewed link/component/offer.
- Keep price and lifecycle in LBX; metric/unit ownership and availability come
  from the live configured Kernel manifest.
- Use a simple explicit enablement setting, default disabled. Reject enablement
  under `APP_ENV=production`, including a test deployment using that value.
  Do not silently fall back to simulated terms.
- Present technical limits before confirmation.
- Add a separate expected technical-terms digest to review/confirmation and
  purchase request meaning. Revalidate it for every genuinely new acceptance.
  Keep the existing commercial fingerprint's LBX meaning unchanged.
- Store complete values, version, digest and provenance in a new
  accepted-purchase snapshot version. No per-field quota columns or external
  terms service are required.
- Preserve readable `accepted-purchase:v1` and exact same-key replay semantics.
  Existing purchases receive no invented metering.
- After acceptance, derive from the snapshot. Fixture changes or disablement
  affect new acceptances only within dev/test; changing environment never
  upgrades simulated provenance.
- Missing technical quantity evidence does not mean an access-only offer.
  A verified legacy purchase may produce its product grant, but provides no
  metered allowance without historical proof. Metered execution must remain
  unavailable.

Retain existing legal content and legal-event semantics. The new digest binds
additional purchased meaning to the existing immutable acceptance; it does not
authorize legal-text edits.

### 3.3 Normalized decision rules

Use an explicit provider-neutral decision result, tested independently from
persistence.

- **Preparation-only/unverified:** no primary, positive grant or allowance.
- **Complete owned commercial match, ACTIVE/ALLOWED, valid trust:** eligible
  for primary policy; derive product access and proven purchased allowances.
- **Known waiting/inactive, financial/admin block or ended:** deny/revoke
  affected access immediately. Missing unrelated commercial fields must not
  mask decisive owned negative evidence.
- **Complete ownership/effective-term/policy conflict or terminal revival:**
  deny affected source and retain durable review; no LKG masking.
- **Incomplete/error/unknown:** no new positive access or trust extension.
  Preserve only previously proven facts within unchanged original bounds.
- **Expired trust:** remove dependent facts through a local committed revision.
- **Ambiguous cycle:** no new bucket; omit affected metering through a committed
  change when current metering is no longer proven. Product access and
  unrelated metrics survive when independently supported.
- **Current catalog price or manifest availability change:** does not reprice
  accepted history or resize allowances.
- **Same effective facts with refreshed source trust:** update freshness/deadline
  metadata without a material revision.
- **Duplicate effective metric sources:** omit only that metric; never sum
  quantities.

### 3.4 Primary selection and transaction ownership

Linking a subscription does not select it. Complete discovery is required for
first selection. Ordinary rereads of an existing primary use its authoritative
point proof; the existing periodic customer inventory discovers newcomers.
The apply transaction rechecks primary, so a concurrent clearing cannot turn
a reread without discovery into a new selection.

Reuse Step 8's customer inventory and point-read machinery. Persist a bounded,
complete target-product discovery observation before the final product-scope
decision transaction. Record normalized candidate conclusions, completeness,
relevant original provenance and supporting run/claim evidence. Do not create
a parallel discovery service or durable decision-attempt subsystem.

Under the product lock, evaluate the union of persisted relevant candidates and
locally known nonterminal candidates:

- Zero eligible: no primary.
- Exactly one eligible, matching the linked purchase: select it.
- One eligible candidate belonging to another purchase, multiple eligible
  candidates or incomplete relevant proof: no automatic selection; retry or
  review as appropriate.
- An existing trusted primary survives a later newcomer under its ordinary
  trust rules. The newcomer produces no access.
- Blocking never promotes another candidate. Terminal primary clearing never
  automatically promotes an old competitor.
- Unknown nonterminal same-tariff candidates cannot be classified as another
  product without permanent local purchase/agreement/effective-term proof.
  A canonical point read and verified customer ownership can exclude an ended
  candidate without inventing accepted terms for it.

Use the existing user row as the whole-user serialization boundary. Every
access-affecting transaction must acquire it before customer/product business
locks. Within the inherited order, lock affected purchases/holds/operations,
product scopes and subscriptions deterministically; then state/outbox rows;
queue ownership is checked last. No network I/O occurs inside these transactions.

The shared access writer participates in the caller-owned transaction and never
commits independently. Recheck source fences, current ownership, accepted
provenance and relevant candidate evidence after locking. Stale completion
cannot select primary, create quota or overwrite newer authority.

### 3.5 Calendar cycles and immutable allowance identity

The owner approved recovery directly into a proven later current cycle,
without backfilling skipped periods.

Normalize provider calendar evidence at Integration. Preserve date-only and
timestamp precision losslessly. A naive timestamp is not UTC; never truncate
it into a date to obtain allowance permission.

For the documented LBX date-only model, preserve inclusive calendar ranges
internally. LBX explicitly describes a June 15–July 14 period followed by
July 15; it also permits edits that change the anchor. These are reasons to
verify anchor continuity, not infer a UTC midnight.
[LBX tariff rules](https://docs.lbxbilling.ru/tariffs/add_tariff/),
[subscription edits](https://docs.lbxbilling.ru/subscriptions/edit_sub/).

Implement the classifier as follows:

1. **First proven cycle:** require complete eligible source proof, original
   accepted terms, coherent calendar range and a resolvable period/anchor.
2. **Same cycle:** identical established cycle meaning reuses existing
   ID/quantity.
3. **Later current cycle:** prove a positive integral number of accepted periods
   from the frozen anchor, unchanged source ownership/terms and no overlap,
   reversal or anchor drift. Create only the currently observed bucket.
4. **Ambiguous/conflicting:** no refill, no boundary rewrite, durable
   metric-scoped diagnosis/review.

Use calendar arithmetic, not elapsed seconds. Derive month/year boundaries from
the original anchor, preserving month-end/leap-day behavior rather than
repeatedly adding to a clipped previous boundary. Validate day/week ranges with
their accepted period length. Calendar-month anchors must follow documented
calendar boundaries. Unsupported or insufficiently evidenced combinations
remain incomplete.

Correct the demonstrated Step 8 calendar seam:

- A date-only one-day inclusive range may have equal start/end.
- Timestamp intervals retain precision and ordering checks.
- Policy-specific first/last calendar periods must not be rejected merely
  because a full calendar billing range extends beyond an activation date.
- Waiting/null/sentinel dates remain ordinary negative evidence.
- Do not add a "period contains local today" payment predicate.

Logical uniqueness is:

`(local subscription, source component, metric_key, provider_cycle_key) → one allowance_id`

The local subscription already scopes account and provider identity. Generate
an opaque allowance ID once, protected by PostgreSQL uniqueness. A new digest
of edited dates alone is not permission to issue a new ID: classification
precedes insertion.

Freeze product, metric, unit, quantity, source terms and cycle meaning at first
issuance. Charges, price changes, rereads, block/unblock, restart and configuration
changes cannot rewrite them.

### 3.6 Semantic revisions, deadlines and outbox

The persisted effective document contains a canonical, complete provider-neutral
grant/allowance set. Do not include raw provider IDs/statuses, actual usage or
source payloads.

- No state row means implicit empty revision `0`.
- First material transition inserts revision `1`.
- Later material transitions commit exactly `N+1`, including transitions to empty.
- Compare canonical authorization-relevant contents. Observation IDs, read
  times, diagnostics and trust refreshes are not material changes.
- Use existing observations for causal linkage. Populate
  `resulting_access_revision` once with a positive committed revision; append
  a new causal observation when an already-linked observation cannot describe
  a later change.
- Atomically upsert outbox `pending_revision = max(existing, committed)`.
  Preserve delivered revision, attempts and delivery bookkeeping. Never delete
  newer pending work.
- Step 10 must acknowledge only its captured sent revision; Step 9 does not
  implement delivery or acknowledgement networking.

Introduce an explicit paid-access clock-skew budget, validated as positive and
below the retained 300-second snapshot ceiling. Do not invent a production clock
guarantee or silently choose a deployment budget. Development tests supply an
explicit value; deployment enablement requires an operationally supported value.

Complete reads establish at most six hours of raw source trust. Persist/schedule
the conservative effective deadline with its supporting proof. Missing
configuration permits no new positive paid derivation, but must not prevent
local reductions of already issued state.

The existing durable worker processes the earliest supported effective
trust/grant deadline. Calendar dates alone schedule no expiry or refill.
Local work may only reduce access and never renew, unblock, create a bucket
or extend trust.

### 3.7 Conditions for implementation, acceptance and later enablement

**No unresolved business decision blocks supported Step 9 development.**
The following conditions apply at different points; they are not a blanket
prerequisite to start coding.

- **Implementation baseline — SATISFIED:** Step 8 and the relevant later Step 7
  corrections are inherited through the delivered predecessor in Section 2.
- **Mock alignment — SATISFIED:** the existing two-product fixture was reused;
  bounded all-disabled and safe producer-shaped error scenarios are delivered.
  Mock alignment is not real producer conformance.
- **Actual Step 9 acceptance — Portal engineer and owner QA:** an available
  supported test-LBX purchase, complete fresh reads and ordinary authenticated
  Portal/cabinet path are required for live acceptance, not for beginning
  implementation or deterministic tests. Reuse known objects where possible.
  Any new real LBX mutation requires explicit authorization.
- **Production metering — commercial owner and ANY-711/Steps 10–11:** real
  purchased quantities and approved technical vocabulary are required before
  production metering. The 100/300 fixture supports current development but
  cannot satisfy production enablement.
- **B10 wire — ANY-766:** jointly review/update canonical specs,
  producer/consumer DTOs, fixtures and compatibility in Step 10. This is not
  a Step 9 coding dependency; Step 9 exposes no competing internal wire.
- **Natural renewal / deployed rollout — Steps 9–11 QA owners:** preserve the
  outstanding real scenario and record its result honestly. It is not a
  prerequisite for writing or fixture-testing this implementation.
- **Webhook enablement — ANY-715:** remains disabled/polling-only until its
  existing authentication/delivery condition passes.

## 4. Functional DoD & Acceptance Coverage

- **Exact accepted limits:** Step 1 verifies displayed-versus-confirmed
  technical terms, immutable 100/300 snapshots, legacy compatibility and
  production refusal.
- **Authoritative paid derivation:** Step 2 tests preparation denial, complete
  eligibility, ordinary negative states, conflicts, finite LKG and independent
  products.
- **Safe primary:** Step 2 covers zero/one/multiple candidates, incomplete
  inventory, hidden local competitors, stale completion and trusted-primary
  preservation.
- **Stable quota identity:** Step 2 covers same-cycle reread/block/unblock/restart,
  later-cycle recovery across gaps, duplicate identities, invalid quantities,
  edited/recalculated/overlapping periods and metric-local failure.
- **Atomic semantic changes:** Step 2 verifies implicit zero, first revision,
  no-op, later empty state, concurrent different-product commits, rollback
  and outbox coalescing.
- **Autonomous expiry/recovery:** Step 3 verifies provider-free due work,
  restart/catch-up, refresh races, configuration outage, audited recovery and
  capacity isolation.
- **Truthful customer contract:** Step 4 verifies committed reads, known absence
  versus unavailable evidence, late-deadline refusal, session isolation and
  no invented usage.
- **Actual supported integration:** Final Verification traces test LBX →
  Step 8 observation → Step 9 state/revision/outbox → authenticated API/cabinet.
  Fixture-only and live evidence remain separate.

## 5. Sequential Implementation Steps

All four implementation steps below are **DONE**. Their original execution
prompts are retained for traceability, not as a queue of unfinished work.
Per-step delivery records identify the resulting commits; Section 6 owns the
current verification and acceptance status.

Use the repository-managed test environment and shared PostgreSQL fixtures.
Focused canonical selection can use command-local `PYTEST_ADDOPTS`, for example:

```bash
PYTEST_ADDOPTS="-k 'paid_access or billing_subscription_reconciliation'" npm run test:api:fast
PYTEST_ADDOPTS="-k 'paid_access or billing_subscription_reconciliation'" npm run test:api:postgres
```

Do not manually create/drop the physical test database or bypass test-database
safety checks. Expand focused selections to include the changed inherited
purchase, worker, recovery or operator suites as required by each step.

### Step 1 — Preserve consented test metering terms

**Goal**

Make approved development limits genuine immutable purchase inputs, with
protection against changes between presentation and confirmation.

**Expected behavior**

Review reads the current offer, capabilities and explicitly enabled test terms.
The buyer sees price and limit. Confirmation rejects a changed technical-terms
digest. Successful confirmation pins the full accepted terms. Replaying that
purchase uses saved history without consulting current fixture values.

**Read before implementation**

- Purchase contracts, service and composition listed in Section 2:
  `review_purchase()`, `confirm_purchase()`, `PurchaseMeaning`,
  `AcceptedPurchase`, `pin_purchase()`, `accepted()` and `_prior_request()`.
- [Purchase HTTP contracts](../../../apps/api/app/domains/purchases/router.py),
  `present_review()` and `present_purchase()`.
- [Product link/current-offer contract](../../../apps/api/app/domains/catalog/product_link.py).
- [Kernel mock](../../../tools/kernel_manifest_mock/server.py), its
  documentation and finalized preparation delta.
- Existing purchase acceptance/fencing tests,
  [any709-step4.test.tsx](../../../apps/web/tests/components/any709-step4.test.tsx)
  and ProductBilling.
- Section 3.2 and the producer-owned ANY-711 contract.

**Implementation**

- Add the small dev/test terms source and explicit enablement from Section 3.2.
  Use a single canonical example dataset; keep quantities outside the manifest.
- Reconcile remaining PR #151 examples with the inherited two-product fixture.
  Preserve independent digest pins and historical evidence labels.
- Consume the bounded mock-alignment work: all-disabled scenario, safe 500/503
  cases and Kernel-shaped errors. Preserve unauthorized-scope, duplicate-field
  and browser rejection. Do not rebuild token-rotation infrastructure beyond
  the existing preparation scope.
- Extend review/confirmation with a technical-terms digest and new immutable
  accepted-purchase version. Preserve commercial fingerprint and original
  legal associations.
- Keep v1 history and same-key replays readable. Missing technical history
  cannot acquire current fixture values.
- Show exact quantity/unit and simulation status in the existing purchase
  review UI. Client values select/compare; the server supplies authority.
- Generate OpenAPI/TypeScript artifacts through repository generation.
- Wire development data into the development runtime/image without creating
  a production fixture fallback or mandatory approval/profile workflow.
- Add typed test factories and focused acceptance, digest-race, replay and
  provenance tests.

**Invariants / Non-goals**

No new grant, allowance or revision. No real billing mutations. No quantity in
Kernel manifest or product-link commercial quantity. No legal-content changes,
production terms registry or external terms service.

**Verification**

- Test 100/300 values and metric/unit ownership independently.
- Change quantity between review and confirm: refuse confirmation without
  creating acceptance.
- Change fixture after acceptance: original snapshot/replay remains unchanged.
- Reject fractional, boolean, negative or out-of-range quantities; accept
  strict integer zero where the general contract permits it.
- Verify fixture-disabled and `APP_ENV=production` refusal.
- Run Ruff on changed Python, focused purchase/mock tests, changed purchase
  component tests, `npm run generate`, `npm run generate:check`,
  `npm run architecture:check`, `npm run docs:check`, web lint/typecheck.

**Expected completion**

After this step, a new approved test purchase can preserve exactly the technical
limits the buyer saw and accepted, and later derivation needs no mutable terms
lookup.

**AI execution prompt**

> Implement only Step 1 of ANY-765 using docs/exec-plans/active/ANY-765-implementation-plan.md, especially Sections 2 and 3.2. Read the purchase contracts/service/router/composition, product-link/current-offer contract, ProductBilling and existing purchase acceptance/fencing tests. Inspect the delivered Kernel mock preparation before changing its files.
>
> Add the explicit dev/test-only versioned 100/300 terms source, validate it against current Kernel metric/unit ownership, present it before confirmation, and bind its digest into new acceptance and idempotency meaning. Persist full immutable values/provenance in a new snapshot version while preserving v1 history and saved-purchase replay. Keep the commercial fingerprint's existing meaning. Reuse the finalized mock delta without duplicating its two-product fixture. Generate owned API contracts and test quantity changes between review/confirm, history preservation and production refusal. No paid projection is part of this step.
>
> Run focused purchase/mock API tests and purchase component tests, Ruff, npm run generate, npm run generate:check, npm run architecture:check, npm run docs:check and web lint/typecheck. Confirm that no grant, allowance, revision or outbox writer was introduced.
>
> Follow the repository's root and applicable subtree AGENTS.md files, ARCHITECTURE.md, docs/engineering/CODING_CONVENTIONS.md, docs/engineering/AGENT_WORKFLOW.md, and docs/engineering/TESTING.md. Respect existing architectural layers, coding conventions, typing, error handling, transaction ownership, dependency direction and established project structure. Use equivalent authoritative instructions in other affected repositories.
>
> Implement only the specified step. Reuse existing components and preserve the agreed functional outcome and invariants. Do not broaden the scope or start subsequent steps.
>
> Run appropriate formatters, linters and focused automated tests. Fix failures caused by your changes and rerun affected checks. Run additional relevant validation when necessary; report unexecuted or blocked checks accurately.
>
> If a material contradiction appears, investigate the relevant surrounding context and available evidence, then propose a resolution. Stop and ask only when an important decision cannot be made safely.
>
> Do not run mutating operations against real billing or other external production systems without explicit authorization.
>
> Do not stage, commit, push, switch branches, merge or rebase. Do not modify unrelated worktrees.
>
> Report the implemented behavior, changed files, verification results, remaining limitations and any required manual QA.

**Proposed commit**

`ANY-765 - Pin consented development metering terms`

### Step 1 delivery — DONE

Delivered in `85ba988` (the rebased form of original `017ab1a`). V2 acceptance
pins strict integer quantities, unit/metric ownership, digest and SIMULATED
provenance. Changed terms refuse new confirmation; saved v1/v2 replays preserve
history. The explicitly enabled dev/test fixture refuses production use.
The existing two-product mock was reused and its bounded missing scenarios
aligned with inspected ANY-711 source. No paid grant was introduced by this step.

Purchase API/PostgreSQL, component and desktop/mobile synthetic browser checks
passed. Current aggregate results and remaining limits are consolidated in
Section 6; earlier run-by-run evidence remains in Git.

### Step 2 — Derive and atomically commit paid access

**Goal**

Turn verified subscription/discovery facts into safe product grants and immutable
allowances, committed with one semantic revision/outbox path.

**Expected behavior**

A complete eligible linked purchase without a selected primary triggers complete
relevant discovery. The serialized decision selects a safe primary, classifies its cycle, reuses or
creates correct allowances and commits the user's complete effective state.
Negative/conflicting rereads reduce the affected source. Equal facts remain
a no-op.

**Read before implementation**

- On inherited ANY-715: billing `reconciliation.py`,
  `reconciliation_contracts.py`, `background_recovery.py` and corresponding
  composition/query helpers.
- LBX reconciliation/financial decoders and existing
  [subscription reconciliation tests](../../../apps/api/tests/test_billing_subscription_reconciliation.py)
  and [factories](../../../apps/api/tests/factories/reconciliation.py).
- [Subscription/scope models](../../../apps/api/app/models/billing_subscriptions.py),
  [observation model](../../../apps/api/app/models/billing_observations.py),
  allowance and access models.
- Existing Alembic head and clean-baseline allowance/observation immutability
  triggers.
- Step 1 acceptance implementation and Sections 3.3–3.6.

**Implementation**

- Add focused pure decision/classification functions and one caller-transaction
  paid-access writer within the existing billing feature. Keep vendor parsing
  in Integration.
- Extend successful inventory to persist complete target-product candidate
  evidence and normalized conclusions. Preserve bounded reads and existing
  claim/fence handling.
- Implement first-primary and trusted-primary/newcomer behavior from Section 3.4.
  Do not automatically adopt externally discovered objects.
- Correct date-only normalization, including inclusive one-day periods, and
  implement the cycle classifier from Section 3.5.
- Derive allowance quantity/unit exclusively from immutable accepted terms.
  Same-cycle recovery reuses rows. Proven later current cycles create only
  the observed cycle's rows.
- Add a forward migration from the actual inherited head:
  - Add versioned calendar evidence, explicit date-only cycle bounds and frozen
    unit/terms provenance to allowance storage.
  - Retain legacy UTC values without converting them into guessed calendar
    dates. Permit new calendar rows without fabricated UTC period bounds;
    distinguish legacy/calendar shapes with constraints.
  - Require nonnull cycle identity for new calendar rows and enforce logical
    uniqueness.
  - Preserve the existing immutable-row trigger across new fields.
  - Enforce positive persisted revisions and prevent state revision regression,
    same-revision semantic mutation or deletion/reset.
  - Strengthen observation revision positivity and outbox monotonicity where
    storage guards are appropriate.
- Preflight unexpected legacy data. Preserve it; report incompatible
  duplicates/nonpositive state instead of silently deleting, repairing or
  authorizing it. A downgrade that cannot preserve calendar meaning must refuse
  clearly.
- Canonicalize and compare the complete effective set under the user lock.
  Preserve independent product updates under concurrent transactions.
- Atomically write state, causal observations and coalesced invalidation;
  preserve delivery bookkeeping.
- Integrate ordinary authoritative reconciliation and inventory application
  with that writer before their existing commit. Step 3 completes remaining
  deadline/operator/customer paths.
- Update schema/architecture documentation and narrowly align retained
  eligibility wording with the accepted owner decision. Leave coordinated
  Kernel wire changes pending.

**Invariants / Non-goals**

No settlement reconstruction, usage ledger, stacking, automatic competitor
promotion or mutable allowance tuple. No internal AccessSnapshot endpoint or
invalidation sender. Do not expose this intermediate implementation as a
completed deployed feature before Steps 3–4 pass.

**Verification**

Use real disposable PostgreSQL for migration, trigger and concurrency checks.

Cover:

- Preparation denial and complete positive/negative/conflict decisions.
- Initial primary zero/one/multiple, incomplete inventory, hidden local
  competitor, ended external history and stale completion.
- Ordinary primary refresh avoids discovery; inventory reuses point reads.
  Concurrent primary clearing still requires fresh discovery before selection.
- Trusted-primary preservation versus newcomer; no automatic replacement
  after block/end.
- Same-cycle repeat/block/unblock/restart; skipped-period recovery; no backfill.
- Daily inclusive, monthly, month-end/leap, anchor edits, overlapping/reversed
  ranges, mixed precision and recalculation.
- Duplicate logical identity races and metric-local duplicate-source failure.
- `0→1`, equal no-op, later empty revision, concurrent different-product updates.
- Transaction rollback and crash-after-commit persistence of
  state/revision/outbox.
- Changed current catalog/fixture values cannot rewrite accepted history.

Run focused fast/PostgreSQL selections, Ruff, architecture/docs checks and
generated freshness checks. Start the test server through `make test_db_up`
and use shared fixtures.

**Expected completion**

After this step, ordinary authoritative reconciliation can safely materialize
and atomically persist the correct user-wide paid state, stable allowances,
semantic revisions and durable invalidation work.

**AI execution prompt**

> Implement only Step 2 of ANY-765 from docs/exec-plans/active/ANY-765-implementation-plan.md. Read Sections 3.3–3.6, inherited billing reconciliation/inventory composition and Application code, LBX normalization, subscription/scope/observation/allowance/access models, current migration chain and reconciliation PostgreSQL tests.
>
> Implement provider-neutral paid decisions, complete persisted discovery for first-primary selection, trusted-primary preservation, lossless calendar classification and immutable allowance identity. Recover directly into a proven later current cycle without backfilling skipped cycles. Add the minimal forward migration preserving legacy evidence, then implement the caller-owned atomic effective-state/revision/audit/outbox writer and call it from ordinary reconciliation/inventory apply. Preserve user-first serialization, current fences, exact accepted quantities, semantic no-ops and independent products. Do not implement worker deadlines, Kernel networking or customer presentation in this step.
>
> Verify meaningful policy, migration, constraint, PostgreSQL race/rollback, cycle and revision/outbox cases using the canonical focused fast/PostgreSQL selections. Run Ruff, architecture/docs checks and generated freshness checks. Do not treat SQLite or mocked persistence as evidence of PostgreSQL guarantees.
>
> Follow the repository's root and applicable subtree AGENTS.md files, ARCHITECTURE.md, docs/engineering/CODING_CONVENTIONS.md, docs/engineering/AGENT_WORKFLOW.md, and docs/engineering/TESTING.md. Respect existing architectural layers, coding conventions, typing, error handling, transaction ownership, dependency direction and established project structure. Use equivalent authoritative instructions in other affected repositories.
>
> Implement only the specified step. Reuse existing components and preserve the agreed functional outcome and invariants. Do not broaden the scope or start subsequent steps.
>
> Run appropriate formatters, linters and focused automated tests. Fix failures caused by your changes and rerun affected checks. Run additional relevant validation when necessary; report unexecuted or blocked checks accurately.
>
> If a material contradiction appears, investigate the relevant surrounding context and available evidence, then propose a resolution. Stop and ask only when an important decision cannot be made safely.
>
> Do not run mutating operations against real billing or other external production systems without explicit authorization.
>
> Do not stage, commit, push, switch branches, merge or rebase. Do not modify unrelated worktrees.
>
> Report the implemented behavior, changed files, verification results, remaining limitations and any required manual QA.

**Proposed commit**

`ANY-765 - Commit paid access with immutable cycle allowances`

### Step 2 delivery — DONE

Delivered in `f18c279`, with predecessor/rebase corrections in `d005cec`.
Migration `20261031_0006` adds lossless cycle evidence, logical allowance
uniqueness and immutable/monotonic storage guards. Reconciliation and inventory
share the caller-transaction paid writer, causal audit and coalesced outbox.

Complete discovery gates first selection. Ordinary trusted-primary refreshes
reuse point proof; newcomer conflicts do not replace that primary. Ended
customer-owned external history may be excluded without fabricated local
acceptance; unknown nonterminal/local-hidden candidates still prevent unsafe
selection. Same-cycle recovery reuses frozen IDs and quantities; proven later
current cycles receive no skipped-period backfill.

Policy, migration, PostgreSQL/concurrency and source-read regression checks
passed. Section 6 reports verification of the combined delivered state.

### Step 3 — Apply autonomous deadlines and controlled recovery

**Goal**

Ensure paid state remains correct without browser activity, during LBX failure
and across restart, including every inherited access-affecting writer.

**Expected behavior**

A legitimate proof refresh atomically schedules its effective deadline.
At that deadline the existing local worker removes only due facts through the
shared writer, without HTTP. Recovery and operator actions use verified source
proof and the same writer; they cannot assign quota or reset identity.

**Read before implementation**

- Inherited `work.py`: `schedule_reconciliation()`, `expire_trust()`, claim
  verification and enrollment repair.
- `jobs/billing.py`,
  [worker resource composition](../../../apps/api/app/composition/billing_worker.py),
  `billing_background.py` and existing worker HTTP/resource-isolation tests.
- [Customer conflicts](../../../apps/api/app/domains/billing/customer_conflicts.py),
  `customers.py::apply_customer_read()` and customer identity transitions.
- Purchase financial review transitions, existing operator
  contracts/composition/CLI and
  [operator review](../../../apps/api/app/domains/billing/operator_review.py).
- Step 2 writer and Step 8 operations runbook.

**Implementation**

- Extend existing durable scheduling/claim paths for earliest effective
  paid-access deadlines. Preserve source-trust evidence and queue
  generation/lease semantics.
- Schedule deadlines atomically with supporting facts/access changes. Local
  expiry is reduction-only and rechecks refreshed authority under the same
  user/product locks.
- Repair missing paid deadlines on startup/sweeps in bounded batches; catch up
  overdue work after restart.
- Keep the local lane operational when LBX configuration/authentication is
  unavailable. Source lanes may be unavailable while existing local reductions
  continue. Do not let current empty/changed source configuration hide old
  persisted deadlines.
- Preserve isolated source and local resources, retained cleanup ownership
  and bounded DB work. No second worker, scheduler or process mode.
- Audit all existing access-affecting commits:
  - authoritative reconciliation and discovery;
  - paired-customer identity conflicts, including interactive and
    integrity-error paths;
  - material purchase/subscription review transitions;
  - existing restore-original/bind-original resolutions;
  - local expiry and configuration/provenance reductions.
- Acquire user serialization before customer locks on paths that previously
  did not need whole-user access commits. Avoid lock inversion or nested commits.
- Preserve an existing primary on newcomer-only conflict. Genuine shared
  customer identity failure may revoke all facts depending on that customer.
- Extend the privileged CLI with the minimal audited primary-resolution
  operation. It selects only an already linked, freshly proven owned
  subscription under current review/evidence/fence checks. It cannot bind
  arbitrary objects, clear unrelated conflicts, revive ended subscriptions
  or supply quantity.
- Resolve cycle ambiguity only through restored proven original meaning.
  Supporting a different commercial/anchor meaning remains outside this ticket.
- Add bounded revision/no-op, deadline lag and conflict diagnostics. Use local
  IDs for incident lookup, never metric labels or raw provider payloads.
- Extend the existing runbook with scheduling, recovery, refused operations
  and clock/configuration behavior.

**Invariants / Non-goals**

No positive change from a timer, webhook, customer-only proof or operator
assertion. No background CREATE. No automatic hold release, financial-history
reconstruction or invalidation delivery.

**Verification**

- Expiry while all provider calls fail; assert zero provider HTTP in local work.
- Refresh versus expiry race and stale queue owner.
- Restart/backlog catch-up and missing deadline repair.
- Source-unconfigured startup still processes local reductions.
- Slow-source/new-purchase saturation preserves paid reads/local work capacity;
  validate the read endpoint after Step 4 integrates it.
- Customer identity conflict revokes all dependent products, while
  product-specific conflict affects only its dependency.
- Same-cycle controlled recovery restores original allowance IDs.
- Stale/wrong-scope/operator requests refuse without partial state.
- Failure after any intermediate write rolls back facts, access, audit and
  outbox together.

Run focused worker/recovery/operator/paid-access tests, PostgreSQL races,
architecture checks and Ruff. Reuse the existing small HTTP-capacity harness
rather than introducing a speculative benchmark.

**Expected completion**

After this step, the system autonomously reduces stale access and safely
recovers proven access through one coherent commit path, even during provider
outage or process restart.

**AI execution prompt**

> Implement only Step 3 of ANY-765 from docs/exec-plans/active/ANY-765-implementation-plan.md. Read the Step 2 writer, inherited work scheduling/enrollment/expiry, BillingWorker resource composition, customer-conflict and financial-review transitions, operator proof/audit code and Step 8 operations runbook.
>
> Attach effective access deadlines to the existing durable local lane and shared access writer. Keep local reductions running without LBX configuration or availability; preserve fences, generations, cleanup ownership and resource isolation. Integrate every demonstrated access-affecting customer/review/operator path atomically, with user-first lock order. Add the narrow proof-based audited primary selection operation to the existing privileged CLI. Timers and operators cannot invent positive proof, quantity or a new cycle.
>
> Test provider-free expiry, refresh races, restart repair, configuration outage, shared-customer versus product-specific blast radius, stale operator proof and slow-source capacity using focused fast/PostgreSQL and existing HTTP harness tests. Update the operational runbook and sanitized diagnostics.
>
> Follow the repository's root and applicable subtree AGENTS.md files, ARCHITECTURE.md, docs/engineering/CODING_CONVENTIONS.md, docs/engineering/AGENT_WORKFLOW.md, and docs/engineering/TESTING.md. Respect existing architectural layers, coding conventions, typing, error handling, transaction ownership, dependency direction and established project structure. Use equivalent authoritative instructions in other affected repositories.
>
> Implement only the specified step. Reuse existing components and preserve the agreed functional outcome and invariants. Do not broaden the scope or start subsequent steps.
>
> Run appropriate formatters, linters and focused automated tests. Fix failures caused by your changes and rerun affected checks. Run additional relevant validation when necessary; report unexecuted or blocked checks accurately.
>
> If a material contradiction appears, investigate the relevant surrounding context and available evidence, then propose a resolution. Stop and ask only when an important decision cannot be made safely.
>
> Do not run mutating operations against real billing or other external production systems without explicit authorization.
>
> Do not stage, commit, push, switch branches, merge or rebase. Do not modify unrelated worktrees.
>
> Report the implemented behavior, changed files, verification results, remaining limitations and any required manual QA.

**Proposed commit**

`ANY-765 - Enforce paid access deadlines and audited recovery`

### Step 3 delivery — DONE

Delivered in `0d360d0`, with integration corrections in `d005cec` and `b6c8802`.
The existing local worker processes conservative source/grant/UTC-allowance
deadlines and repairs missing work without provider I/O or present-day LBX
configuration. Timers only reduce; user-first locking and queue checks preserve
atomic state/revision/audit/outbox commits and stale-owner rollback.

Customer identity conflicts reduce dependent products atomically; scoped
purchase/review failures preserve independent products. Ordinary paired-key
recovery restores no access before fresh subscription proof. Audited
`select-primary` accepts only the original linked candidate with current case,
proof and fence checks. Incomplete inventory remains retryable rather than
creating a durable ambiguity review; existing review history is preserved.

PostgreSQL deadline/recovery/fence and real-loopback HTTP capacity checks passed.
The post-rebase regressions preserve original-key recovery, the common read-set
trust start and local deadlines across account-scope/configuration conflicts.
Current final verification and unresolved acceptance remain in Section 6.

### Step 4 — Expose committed paid state in the cabinet

**Goal**

Give authenticated users a truthful local paid-state read and integrate it
into the existing product-access presentation.

**Expected behavior**

The cabinet loads saved paid state independently of current catalog/LBX
availability. It shows confirmed paid access, known absence or unavailable
evidence. Purchased quantity may be shown, but used/remaining remains
unavailable. A Widget callback only causes a local read; it does not grant access.

**Read before implementation**

- Existing purchase/billing routers, bearer/session authentication and shared
  API transport.
- AccountBilling, ProductBilling, account purchase hook and
  [session-operation helpers](../../../apps/web/src/shared/session/use-session-operation.ts).
- Generated API contract workflow and locale catalogs.
- Existing cabinet/session-race component tests and
  [any709-purchase.spec.ts](../../../apps/web/e2e/any709-purchase.spec.ts).
- Step 2 document/read semantics and Step 3 deadline behavior.
- [Bundle 3](../../design-system/bundle3/README.md),
  [RU journey](../../product/ru-mvp.md), web AGENTS and installed Next.js
  documentation for affected APIs.

**Implementation**

- Add authenticated `GET /api/paid-access`, scoped exclusively to the
  authenticated user and configured tenant/region. Do not accept an arbitrary
  user ID.
- Define named backend response models containing:
  - committed revision;
  - complete provider-neutral grants;
  - allowances with opaque ID, product, metric, unit, quantity and provenance;
  - separate bounded product evidence/display status and freshness metadata.
- Do not expose internal cycle/provider identifiers, guessed UTC periods or
  an internal AccessSnapshot schema.
- For an account with no accepted/linked sources, return implicit empty
  revision `0` without paid-state/outbox writes.
- Distinguish preparation/incomplete evidence from proven negative/no-paid-access
  state. A complete current effective set can be empty while evidence for
  a particular purchase remains unavailable.
- Read committed tuples unchanged. If a committed fact has crossed an
  unprocessed effective deadline, return a safe
  `503`/`paid_access_deadline_pending`; do not filter the document, create
  a revision or enqueue repair from GET.
- Preserve existing identity authentication bookkeeping as its separate
  boundary; paid-state reads perform no billing/access/work mutations.
- Use `Cache-Control: no-store`, safe stable errors and request correlation.
- Generate OpenAPI/TypeScript contracts and consume them through existing
  transport.
- Add a bounded local-read refresh while the authenticated cabinet is visible,
  plus explicit retry. Stop on logout/unmount/session replacement and suppress
  stale responses using existing session-operation patterns. Do not add
  provider polling to the browser.
- Retain purchase preparation/Manage controls as separate facts. The existing
  purchase API's preparation result is not the paid-state authority.
- Update the cabinet/product access slot and stale deferred wording. Preserve
  Bundle 3, accessibility, desktop/mobile layout and locale-key parity.
- Never render missing allowances as unlimited or display invented zero
  usage/remaining.
- Update architecture, schema, integration map and existing billing operations
  documentation with implemented seams and the Step 10 handoff.

**Invariants / Non-goals**

No synchronous source read, GET-side access mutation, browser-derived grant,
frontend wire duplication, Kernel usage API or cross-app launch redesign.

**Verification**

- API: authentication, email/session policy, scope isolation, implicit zero,
  committed paid/empty states, unknown evidence and overdue-deadline refusal.
- Assert paid-state/work/outbox tables are unchanged by reads.
- Concurrent API reads cannot observe a mixed revision/document.
- Cabinet: confirmed/empty/unavailable states, purchased quantity without
  remaining, independent products, session races, retry and Widget refresh.
- Playwright: authenticated synthetic end-to-end path, desktop/mobile evidence
  and accessibility.
- Verify paid-read availability under the slow-source scenario from Step 3.
- Run generated freshness, architecture/docs checks, Ruff, frontend
  component/boundary tests, lint, typecheck and build.

**Expected completion**

After this step, a user can see verified paid product state in the ordinary
cabinet through an authenticated local contract, with honest unavailable states
and no dependency on live LBX reads.

**AI execution prompt**

> Implement only Step 4 of ANY-765 from docs/exec-plans/active/ANY-765-implementation-plan.md. Read the completed projection/deadline implementation, existing purchase/billing router authentication, generated-contract transport, AccountBilling/ProductBilling, session-operation helpers, locale catalogs and cabinet/session-race/browser tests.
>
> Add the authenticated local GET /api/paid-access contract and integrate it into the existing product-access presentation. Expose committed revision/grants/allowances with separate truthful evidence status. Preserve implicit zero and no-store responses. If a committed deadline is overdue, refuse safely without filtering the same revision or writing/enqueuing from GET. Keep purchase preparation separate from paid authority, suppress stale session results and show no invented used/remaining. Generate the API contracts and preserve Bundle 3 and localization rules.
>
> Verify API read-only behavior and scope isolation, cabinet states/session races, focused browser desktop/mobile/accessibility behavior, slow-source paid-read availability, generated freshness, frontend component/boundary tests, lint, typecheck and build. Update owned implementation documentation and the precise Step 10 handoff; do not implement Kernel networking.
>
> Follow the repository's root and applicable subtree AGENTS.md files, ARCHITECTURE.md, docs/engineering/CODING_CONVENTIONS.md, docs/engineering/AGENT_WORKFLOW.md, and docs/engineering/TESTING.md. Respect existing architectural layers, coding conventions, typing, error handling, transaction ownership, dependency direction and established project structure. Use equivalent authoritative instructions in other affected repositories.
>
> Implement only the specified step. Reuse existing components and preserve the agreed functional outcome and invariants. Do not broaden the scope or start subsequent steps.
>
> Run appropriate formatters, linters and focused automated tests. Fix failures caused by your changes and rerun affected checks. Run additional relevant validation when necessary; report unexecuted or blocked checks accurately.
>
> If a material contradiction appears, investigate the relevant surrounding context and available evidence, then propose a resolution. Stop and ask only when an important decision cannot be made safely.
>
> Do not run mutating operations against real billing or other external production systems without explicit authorization.
>
> Do not stage, commit, push, switch branches, merge or rebase. Do not modify unrelated worktrees.
>
> Report the implemented behavior, changed files, verification results, remaining limitations and any required manual QA.

**Proposed commit**

`ANY-765 - Show committed paid access in the cabinet`

### Step 4 delivery — DONE

Delivered in `5eb88c8`, based on clean `b6c8802` plus the reviewed Step 4 diff.
`GET /api/paid-access` uses the existing verified-email session policy and the
configured user/tenant/region scope. A shared user-row read lock stabilizes the
committed complete document and deadline/evidence metadata against paid writers.
After identity bookkeeping, only local SELECTs run; implicit zero creates no
paid state. Database time is sampled after those reads, so an overdue tuple
returns correlated no-store `503/paid_access_deadline_pending` without filtering
or scheduling repair.

Generated customer DTOs expose complete grants/allowances and separate bounded
product evidence. No provider/cycle identifiers, guessed UTC periods or Kernel
AccessSnapshot wire are exposed. The cabinet refreshes local reads while visible,
on retry/visibility return and after Widget close, with session replacement/
logout/unmount guards. Purchase preparation is separate; SIMULATED quantities
are labeled and actual usage/remaining is unavailable.

The read-only `review-full` pass found no confirmed Step 4 defect and changed no
files or test results. It does not establish actual-LBX acceptance or human merge
approval. Verification is consolidated below; Kernel networking was not started.

## 6. Final Verification & Review

### Automated acceptance

After focused checks pass, run the broadest supported canonical verification:

```bash
make test_db_up
npm run check
make test_db_stop
```

`check` includes static/generated/docs/architecture, fast tests, PostgreSQL and
the web build. Use its individual commands for focused iteration; a successful
aggregate does not require immediately repeating the same suites.

Run affected Playwright journeys with the repository's isolated stack,
including desktop/mobile and accessibility evidence. Stop the test server
through the matching repository lifecycle command.

Recheck complete Section 4 coverage against actual persisted behavior.
Inspect final diffs for unrelated changes, secrets, hand-edited generated
artifacts and accidental implementation of future steps.

Review correctness, architecture, security and recovery against the tested
HEAD plus implementation diff. Validation of this plan does not replace
implementation review or human merge approval.

### Configured test-LBX acceptance

Trace at least one supported actual purchase through:

1. Original immutable acceptance and permanent ownership.
2. Fresh complete Step 8 authoritative observation.
3. Step 9 primary, grant and applicable proven allowance.
4. Committed semantic revision and pending outbox.
5. Ordinary authenticated API and visible cabinet state.

Use an existing supported purchase where possible. A new metered test purchase
must use Step 1's acceptance path; never retrofit 100/300 into old history.
If creating/funding/changing a real LBX object is necessary, obtain explicit
authorization or have owner QA perform the ordinary supported action.

Record actual LBX lifecycle evidence separately from SIMULATED technical
quantities. Natural underfunded renewal, production quantity approval and real
Kernel consumption remain separate results.

If configuration, credentials or a supported active sample are unavailable,
mark this checkpoint **BLOCKED/NOT_RUN**. Automated fixtures cannot turn it into
PASS, and the ticket must not claim complete functional acceptance. This
condition does not block supported application implementation and deterministic
tests.

### Pre-rebase verification — runtime/UI baseline `5eb88c8`

All automated provider inputs are synthetic. PostgreSQL uses the worktree's
shared disposable-database fixtures; the source-capacity harness uses real
loopback HTTP. Results below were obtained before publication, against the
corresponding implementation diff. The documentation-only reconciliation did
not change runtime. The subsequent ANY-715 rebase changes shared backend paths;
its separate verification follows below.

- **PASS:** final `npm run check:fast`: 1,749 API-fast, 410 web components,
  38 boundaries, Ruff check/format, lint/typecheck, docs/architecture and generated
  freshness. Local evidence: `.harness/any765/step4-check-fast-deadline-final.{log,exit}`.
- **PASS:** final PostgreSQL selection, 9/9: all seven paid-read cases plus both
  variations of the worker case that failed in the aggregate. It covers auth/
  email/scope, implicit zero, paid/negative/unknown evidence, unchanged billing/
  work/outbox tables, concurrent writer/read consistency, bounded display
  evidence, slow-source availability and deadline crossing during local SELECTs.
  Evidence: `.harness/any765/step4-postgres-deadline-worker-final.{log,exit}`.
- **PASS:** final synthetic Playwright purchase/Widget/cabinet journeys, 18/18,
  desktop/mobile, including layout and serious/critical Axe checks; screenshots
  inspected. Production web build/TypeScript and affected lint/components passed.
  Evidence: `.harness/any765/step4-browser-layout-final.{log,exit}` and
  `step4-{build,lint,components}-layout-final.log` in the same directory.
- **FAIL:** broad `npm run check`: PostgreSQL 693 passed / 1 failed at
  `test_billing_worker_on_time_proof_keeps_delayed_apply_owned[False]`, line 908;
  `latest_observation_id` stayed unchanged. That unchanged test has a 0.3-second
  source budget. The logs do not establish a definitive cause. Its focused
  rerun passed without changing the budget; the aggregate remains **FAIL**.
  It precedes the final deadline-clock/UI refinements verified above.
  Evidence: `.harness/any765/step4-check-final.{log,exit}`.
- **NOT_RUN:** configured actual test-LBX purchase → authoritative observation →
  revision/outbox → ordinary API/cabinet; API image smoke and rollout. This leaves
  ANY-765 functional acceptance open. No real billing mutation was attempted.
- **NOT_RUN / later enablement:** natural renewal, deployed Kernel conformance,
  production vocabulary/quantity approval, supported deployment clock budget and
  the coordinated B10 wire rollout retain the owners in Section 3.7 and the
  operations handoff. They are not additional unfinished coding steps here.
- **NOT_RUN:** clean `npm ci` verification. Installed frontend versions were
  Next 16.3.1 / Vitest 3.2.7 versus unchanged lock pins 16.4.2 / 4.1.12.

The dedicated frontend and worktree PostgreSQL server were stopped; the database
volume was retained. Earlier execution/rebase journals are historical evidence
in `5eb88c8`, not current prerequisites or additional acceptance requirements.

### Current ANY-715 rebase — 2026-11-02

All eight ANY-765 commits were replayed onto `76ea1a7`; the original `ac9fffe`
result is retained in the backup ref above. Current tested runtime is `aff7343`.
Inventory keeps its common read-set start, attempt-local point reuse and paid
writer while retaining timely conflict proof across a later timeout. Per-point
admission checks precede paid discovery without suppressing owned negative facts.
Widget terminal admission and no-send deadline cleanup retain the predecessor
fixes. The renamed `billing-background-operations.md` remains canonical; removed
predecessor plan/QA files are not restored. Current links and the paid/cabinet
handoff are preserved. Web, migrations and generated files match `ac9fffe` exactly.

- **PASS:** full `npm run check`, exit 0: 1,749 API-fast, **703 PostgreSQL**, 410
  components, 38 boundaries, Ruff check/format, lint, production build/TypeScript,
  docs/architecture and generated freshness. PostgreSQL: 1,858.12 seconds.
  The formerly failing worker case passed within this complete run without
  increasing its budget; the pre-rebase failed run remains historical evidence.
- **FAIL then corrected:** first focused PostgreSQL selection, 32 passed / 1
  failed, exposed all-points-before-financial-proof ordering discarding timely
  conflict evidence on a later timeout. The corrected selection passed **33/33**.
  An additional owned-block/newcomer test passed **1/1** and in the full run:
  access is removed with revision/outbox while the frozen allowance is retained.
- **PASS:** complete runtime diff/range review, four original prompt comparison,
  retained predecessor guards, final docs and whitespace checks. Runtime changes
  versus `ac9fffe` are limited to four intended integration paths.
- **SKIP / NOT_RERUN:** browser E2E; unchanged web/migration/generated files permit
  reuse of prior layout/session evidence, not a new post-rebase browser PASS.
  Actual test-LBX, deployed Kernel, clean lock-pinned install and rollout remain
  **NOT_RUN** under their existing acceptance/enablement owners.

Evidence: `.harness/any765/rebase-715-refresh/{check,focused-postgres,focused-postgres-fixed,owned-negative}.{log,exit}`;
`range-diff.txt` and the integration/runtime diff snapshots in that directory.
The worktree-only test PostgreSQL server is stopped with its volume retained.
No other worktree or real billing/production system was mutated.

### Plan validation and documentation reconciliation

The original 2026-10-30 plan passed **validate-plan: READY WITH GATES**. That was
planning self-review, not runtime acceptance. The approved four-step structure,
authority, scope, calendar/quantity rules and original execution prompts remain.
The documented first-primary/ordinary-refresh distinction clarifies the delivered
selection path; it adds no discovery requirement to every primary refresh.

The 2026-11-02 documentation reconciliation removes superseded run/rebase
narratives, identifies all four delivered steps, consolidates current check
results and separates open acceptance from later Kernel/production work.
Current-state architecture/security/reliability/product references and PR #157
are aligned with the implemented local paid read. No new runtime or wire
behavior is introduced by that documentation change.

Documentation follow-up verification: `npm run docs:check` **PASS**;
`pytest apps/api/tests/test_repository_docs.py` **PASS**, 194 cases; whitespace
check **PASS**. A comparison with `96e3b0c` confirms all four execution prompts,
the goal, accepted purchase/decision/cycle/revision rules and functional DoD are
unchanged. Runtime/API/UI suites were not repeated for documentation-only edits.

## 7. Handoff to Next Step

The Step 10 handoff is delivered in the existing
[billing operations runbook](../../engineering/billing-background-operations.md#any-765-step-4-local-cabinet-read-and-step-10-handoff).
It preserves:

- Exact accepted ACTIVE/unblocked policy and its evidence limits.
- Preparation-only versus authoritative reconciliation distinction.
- New acceptance version, technical-terms digest, legacy behavior and
  SIMULATED restrictions.
- Normalized input/decision rules and primary/newcomer policy.
- Writer entrypoints, transaction ownership, lock order, fences and causal
  observation linkage.
- Calendar classification, frozen anchors, gap recovery without backfill,
  immutable allowance identity/quantity/unit and legacy migration behavior.
- Implicit zero, semantic no-op, later-empty revisions and atomic outbox
  coalescing.
- Deadline/clock/configuration behavior, outage/restart guarantees and
  late-read refusal.
- Supported/refused operator actions and operational diagnosis.
- Automated, actual-LBX and unperformed acceptance evidence.

For **ANY-766**, explicitly identify the remaining coordinated B10 change:
reconcile canonical specs' legacy UTC allowance-period clauses with
Portal-internal calendar evidence, then update both producer/consumer contracts,
fixtures, hashes and compatibility together. Preserve finite UTC
trust/snapshot/grant deadlines, six-hour source trust, the up-to-five-minute
snapshot ceiling and durable usage identity.

Step 10 receives implemented local state and outbox semantics. It still owns
HTTP delivery, captured-revision acknowledgements, Kernel cache/revision floor,
runtime enforcement and actual usage/remaining. Production metering and
natural-renewal/deployment conditions remain visible with their owners.
