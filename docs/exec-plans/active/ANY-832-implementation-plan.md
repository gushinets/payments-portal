# ANY-832 implementation plan

Status: **COMPLETE** — steps 1–3 complete; owner-approved scoped step 3 verification passed.
Created: 2026-11-11
Issue: [ANY-832](https://linear.app/paveldik/issue/ANY-832/fix-deferred-pr-164-inventory-completeness-and-calendar-allowance-edge)
Predecessor: [PR #164](https://github.com/gushinets/payments-portal/pull/164), reviewed at `b2ef280048ac634a60c18e820fbf702beddba19c`.
Execution branch: `ANY-832`.

## Outcome and execution context

Fix all three deferred findings: incomplete cross-product inventory must prevent
primary selection for every implicated product; coherent annual calendar cycles
must work outside January; equivalent timestamp encodings must preserve an
established allowance.

Follow the [root agent guide](../../../AGENTS.md),
[API agent guide](../../../apps/api/AGENTS.md),
[coding conventions](../../engineering/CODING_CONVENTIONS.md) and
[delivery workflow](../../engineering/AGENT_WORKFLOW.md). Billing authority is
[ADR 0005](../../architecture/decisions/0005-external-billing-boundary.md), then
the accepted designs and narrow amendment linked there. Consult the
[Kernel integration map](../../integrations/platform-kernel.md) for peer impact;
this correction requires no Kernel implementation or wire-contract change.

The plan was saved on branch `ANY-832` at `2d278f6`. At that planning
baseline, the affected inventory, reconciliation, allowance and calendar
implementation files were unchanged from the reviewed predecessor. Preserve
any subsequent user changes.

Public APIs, Kernel contracts, persisted calendar formats and immutable issued
allowances remain unchanged. No schema migration is required. Preserve finite
source trust, existing leases/fences, authoritative negative facts, accepted
purchase terms and the existing production-enablement gates.

## Implementation steps

### 1. Include every implicated product in inventory completeness

- [x] Add a failing regression for each cross-product failure and contradiction
  below before changing the collector.
- [x] In [purchase_inventory.py](../../../apps/api/app/composition/purchase_inventory.py),
  use one calculation of implicated products: the union of the permanent
  subscription binding, agreement ownership and matching accepted tariffs.
- [x] Accumulate implications from both discovery and subscription point
  evidence before failure/mismatch branches can return or continue. New evidence
  may expand the affected set; it must not discard an earlier implication.
- [x] A failed subscription or agreement read leaves the candidate incomplete
  for every implicated product. A list/point disagreement leaves the products
  on both sides incomplete, even if the initial and final listings agree.
- [x] Use the same relationship calculation for final per-product discovery
  verification. Preserve genuinely unrelated-product independence, original
  purchase recovery, ended-subscription/closed-agreement handling and the stricter
  customer-wide financial CREATE admission. Shared authentication, scope,
  deadline and cleanup failures retain their existing customer-wide boundary.

**Completion:** neither `first_primary()` nor audited primary selection can pass
for an implicated product with an unresolved candidate or contradiction.
Healthy unrelated products remain independently selectable.

**PostgreSQL regressions:** agreement owner A with tariff B; subscription GET
failure; agreement GET failure; list/point agreement and tariff disagreements;
unchanged final listings; a completely proven conflicting candidate; a genuinely
unrelated failure; closed-agreement and ended-subscription controls. Exercise
automatic first-primary and operator `require_clear(..., primary=True)` paths.
Extend the existing scoped-inventory and paid-access review-regression suites.

Review sources: [list/point disagreement](https://github.com/gushinets/payments-portal/pull/164#discussion_r4520586867)
and [agreement-owner/tariff failure](https://github.com/gushinets/payments-portal/pull/164#discussion_r4520603025).

### 2. Support annual calendar cycles outside January

- [x] Add failing date-only and explicitly zoned annual regressions before the
  classifier change.
- [x] In [paid_cycles.py](../../../apps/api/app/domains/billing/paid_cycles.py),
  remove only the January requirement for `year / calendar_month`.
- [x] Retain the first day of the activation month, accepted period length,
  existing calendar arithmetic and frozen original anchor. Do not change offer
  admission or month-boundary normalization, infer a new phase from each cycle,
  or replace calendar arithmetic with a fixed number of days.
- [x] Treat an October activation followed by a January annual start as
  contradictory evidence. That synthetic review example does not establish a
  January billing rule.

**Completion:** a coherent non-January annual period is classified as FIRST,
its equivalent repeat as SAME with the same cycle key/allowance ID, and the next
full annual period as LATER.

**Regressions:** date-only and explicitly zoned boundaries; November and January
starts; first, same and later cycles; leap-year and multi-year lengths; incorrect
length and changed-phase rejection. Preserve monthly behavior, inclusive
date-only ends, half-open timestamp ends and unresolved-precision safeguards.
Use the policy tests and PostgreSQL allowance-history tests for persisted identity.

Live LBX subscription 46, agreement 47, tariff 30 established the relevant phase:
activation on 2026-11-11 produced `2026-11-01` through `2027-10-31`, reproduced
in two reads. The source subscription was balance-blocked; this is calendar
evidence, not a paid-grant or live quota acceptance result.

Review source: [annual calendar anchor](https://github.com/gushinets/payments-portal/pull/164#discussion_r4520595113).

### 3. Preserve the established calendar frame across equivalent rereads

- [x] Add a failing PostgreSQL regression through the real normalizer,
  persisted allowance history and source-apply path before the fix. Do not
  bypass normalization with a manually corrected `CalendarEvidence`.
- [x] Extend the internal `ReconciliationSubject` with
  `established_calendar: CalendarEvidence | None = None`.
- [x] During the short `claim_reconciliation` transaction, after checking
  permanent provenance, obtain the first issued calendar for this exact
  subscription, accepted service component and metric using the existing
  ordered allowance-history query. Purchases without technical terms or a
  supported historical calendar provide no established frame. Unbound
  `SubscriptionCandidateSubject` reads retain their no-history behavior.
- [x] Pass the immutable context through the shared reconciliation read to
  [calendar.py](../../../apps/api/app/integrations/lbx/calendar.py). For
  `calendar_month` with a proven explicit historical offset, convert the raw
  explicitly zoned activation into that offset before deriving the month start.
  Compute the new anchor; do not simply substitute the historical anchor.
- [x] Normalize before constructing and saving `SubscriptionProof`; retain the
  original source strings in its raw calendar evidence. HTTP, worker, inventory
  and operator reads continue through the shared path. Integration remains
  database-free; Domain must not import Integration.
- [x] Without suitable history, retain initial normalization. Legacy rows
  without calendar evidence, naive timestamps and mixed precision must not
  acquire an inferred timezone. Keep current-history classification and
  provenance/fencing checks when applying the result.

**Completion:** the same instants represented as `+03:00` and `Z` retain the
allowance ID, quantity, cycle key and complete frozen tuple. Actual changes to
the derived anchor or cycle bounds remain ambiguous.

**PostgreSQL regressions:** issue the first allowance, commit, claim and reread
equivalent raw LBX responses using fresh sessions, then apply through the shared
writer. Cover positive and negative offsets, month-boundary crossings, unchanged
spelling, a valid next cycle and genuine calendar changes. Check isolation from
another subscription's history and preserve no-history, legacy and unresolved
precision behavior. With no other semantic changes or elapsed access deadline,
the equivalent repeat must leave the effective paid state, access revision and
invalidation outbox unchanged; a new source observation/trust renewal is allowed.

Review source: [offset-only reread](https://github.com/gushinets/payments-portal/pull/164#discussion_r4520603815).

## Verification and completion

- [x] Assess existing coverage, record each regression's expected failure on
  unchanged behavior, then implement the smallest coherent correction.
- [x] Run focused affected suites during implementation. Start only the isolated
  worktree test PostgreSQL through the repository harness when persistence tests
  require it; pytest owns the disposable test-database lifecycle.
- [x] Run the owner-approved step 3 checks: affected PostgreSQL scenarios,
  `npm run check:fast` (including the API fast target) and `npm run docs:check`.
  On 2026-11-11 the owner explicitly limited this step to these checks instead
  of the originally planned full `test:api:postgres` / `npm run check` runs.
  Record actual results; scoped persistence checks do not count as a full-suite
  PostgreSQL PASS.
- [x] Inspect the final diff, apply the relevant review checklists and record
  completion evidence here. Confirm no unrelated behavior, generated contracts,
  dependencies or immutable history changed.

The issue is complete when all three regressions are fixed and verification
confirms product independence, complete relevant primary-selection evidence and
immutable allowance identity through effective source apply. Commit, push,
publication and deployment remain separately authorized actions.

### Planning validation and evidence limits

The agreed plan was reviewed with `validate-plan` against the implementation and
repository instructions. Read-only in-memory feasibility checks passed 47
assertions covering equivalent offset encodings, month-boundary crossings,
actual anchor/boundary changes, subsequent monthly cycles, non-January annual
cycles and unresolved precision. These are planning evidence, not implementation
regressions or PostgreSQL transaction/concurrency acceptance.

The exact live payload for subscription 46 combines a naive activation timestamp
with date-only cycle bounds. It remains unresolved after this narrow annual fix;
supporting that precision combination is outside this task. An offset-format
switch by live LBX has not been observed; item 3 addresses a reproduced defect
on explicitly zoned input already supported by the code. No further LBX writes
are needed to implement or locally verify this plan.

### Step 1 execution evidence — 2026-11-11

Scope: step 1 only, on `ANY-832`; steps 2–3 remain unstarted. The pre-existing
plan and documentation-index change were preserved. No API/Kernel contract,
schema, calendar behavior, generated file or dependency changed.

- Coverage assessment found owner-first product attribution, lost point-side
  implications on early exits, and the same precedence in final discovery
  comparison. Existing purported independence fixtures shared an accepted
  tariff; genuinely unrelated controls now use an unmatched candidate tariff.
- Before correction, the initial PostgreSQL regression batch produced
  **12 failed / 16 passed**: unresolved GETs and list/point contradictions
  incorrectly left an implicated product complete; automatic and audited
  operator selection could pass. The batch also exposed omitted cross-product
  candidate evidence in the conflict and terminal controls.
- Additional baseline runs loaded the unchanged `HEAD` collector in memory
  without replacing workspace files: **4/4** bound-candidate regressions and
  **3/3** original-recovery regressions failed as expected. Each run used a
  separate disposable database on the worktree-local PostgreSQL server.
  Two further regressions reproduced failed bound reads omitted from discovery;
  all **6** bound-candidate cases passed after moving original relationship
  implications ahead of discovery.
- One relationship calculation now unions permanent binding, agreement owner
  and accepted-tariff matches. Candidate evidence accumulates across discovery,
  point reads and proven original relationships before early exits; final
  per-product listing comparison uses that same calculation. Contradictions
  stay incomplete even when both listings agree or a later terminal fact is
  known. Successful original proof supplies its proven accepted relationships;
  unresolved original proof adds one bounded subscription GET to scope the
  uncertainty. Recovery remains GET-only and does not bind from inventory.
- Focused verification: the two affected suites initially passed **88 tests**;
  after the remaining bound/original-path corrections, all **15** focused
  inventory regressions passed, including persisted discovery and the real
  automatic primary writer. Existing independence fixtures now accept distinct
  tariffs through the real pin/bind paths and simulated HTTP transport: all
  **7** automatic/operator independence cases passed with their assertions
  preserved. All **20** point-failure/automatic/operator cases also passed with
  distinct agreement-owner and target-product tariffs. Final verification
  results and the full-run limitation are recorded below.
- Review: traced complete/incomplete conclusions through `first_primary()` and
  operator `require_clear(..., primary=True)`; preserved customer-wide financial
  admission, scope/authentication/deadline/cleanup failures, committed negatives,
  original operation history, and source/queue leases and fences.
- Runtime evidence is local PostgreSQL plus simulated LBX transports; no live
  provider or browser acceptance is claimed. No UI implementation or wire
  format changed.

Final verification:

- **PASS:** all **97** tests in the final affected suites: **61** scoped
  inventory and **36** paid-access review regressions, within the full
  PostgreSQL run. The **6** primary-scope cases and **16** paid-access rebase
  cases also passed, retaining the original independence assertions.
- **PASS:** the canonical `npm run check` stages for docs, generated artifacts,
  architecture, API Ruff check/format, web boundary tests (**38**), web component
  tests (**414**), web ESLint, API fast tests (**1871**) and the production web
  build. API fast/PostgreSQL targets ran through the same repository harness
  used by `npm run test:api:fast` and `npm run test:api:postgres`.
- **FAILED full-run check:** PostgreSQL finished **1021 passed / 1 failed**.
  `test_customer_recovery_never_turns_failed_reads_or_terminal_evidence_into_create[discovery_down]`
  in `test_billing_customer_recovery_loop_postgres.py` raised
  `PreflightCleanupPending` while closing source clients under its existing
  **25 ms** cleanup budget (`composition/sources.py:97`). This customer-only
  path and its test were unchanged; it does not execute purchase inventory.
  An isolated repeat of the entire module on the same code passed **10/10**.
  The full canonical command exited **1**, so no full-check PASS is claimed.
  No timeout or assertion was weakened to address this outside-scope failure.
- **PASS:** final `npm run docs:check` and `git diff --check`. No unrelated,
  generated, dependency, schema or calendar source change entered the diff.
- Verification used the existing root `.venv`, with local Kernel mock/origin/
  token variables disabled or cleared only in the command environment;
  inherited local mock settings initially caused five unrelated configuration
  failures. No saved environment settings changed. Local test processes needed
  execution outside the restricted sandbox; only completed reruns count above.
- **SKIPPED:** browser E2E and live-provider acceptance; this step changes
  backend inventory decisions and has no UI or provider-enablement scope.
  pytest removed both disposable task databases; the isolated worktree test
  PostgreSQL server was stopped after verification.

### Step 2 execution evidence — 2026-11-11

Scope: step 2 only, on `ANY-832`; step 3 remains unstarted. The working tree
was clean at entry. The only production-code change removes the January-only
condition in `classify_cycle()`. First-day validation, accepted period length,
frozen-anchor arithmetic, normalization and allowance persistence are unchanged.

- Coverage assessment: existing policy tests covered monthly normalization,
  instance-anchored leap years and equivalent timestamps; allowance-history
  tests covered frozen IDs/UTC bounds and no backfill. They did not exercise
  annual `calendar_month` periods outside January.
- Before correction, the new annual policy batch produced **9 failed / 15
  passed**: coherent November date-only and explicitly zoned cycles were
  classified as `AMBIGUOUS`. January and contradictory-evidence controls passed.
  The PostgreSQL history batch produced **6 failed / 2 passed**: November cycles
  could not issue an allowance, while January controls retained their identity.
- Added coverage includes November/January starts, positive/negative explicit
  offsets, FIRST/SAME/LATER, leap years and accepted two-year lengths. Negative
  controls cover an October-to-January phase contradiction, non-first-day
  anchors, incorrect lengths, rewritten historical anchors, inclusive date-only
  versus half-open timestamp ends, and unresolved/naive/mixed precision.
- PostgreSQL checks commit and reopen sessions, compare the entire first
  allowance row, preserve its ID/key/quantity/calendar/terms/UTC bounds despite
  a changed skew setting, reject re-anchoring, and create exactly one subsequent
  annual allowance with the original anchor and quantity.
- Review traced normalization to classification and persisted history through
  `materialize_allowance()`. No public/Kernel contract, schema, generated file,
  dependency, offer-admission rule or source-trust/fencing behavior changed.
  Peer impact: **None**; local Kernel source `0f950355e3f282c6d5f036542f71e1f2b4295827`
  was inspected for allowance identity/usage persistence; this correction does
  not change its consumed tuple or quota ownership. No peer files changed.

Verification:

- **PASS:** policy and mapping-calendar suites, **95 tests**; allowance-history
  and shared paid-reconciliation PostgreSQL suites, **37 tests**.
- **PASS:** focused Ruff check/format, `npm run docs:check` and `git diff --check`.
- **PASS:** canonical check stages for documentation, generated freshness,
  architecture, API Ruff check/format, web boundary tests (**38**), web component
  tests (**414**), web ESLint, API fast tests (**1898**) and production web build.
  The API fast target is the same harness target used by `npm run test:api:fast`.
- **INTERRUPTED:** the broad PostgreSQL stage of `npm run check` was stopped
  gracefully at the user's request to limit this correction to necessary tests.
  It ended with **538 passed / 1 failed**; the remaining tests were not completed.
  No full-check or full-PostgreSQL PASS is claimed. The affected PostgreSQL
  suites had already passed separately (**37/37**).
- **Outside-scope failure:**
  `test_customer_recovery_never_turns_failed_reads_or_terminal_evidence_into_create[receipt_wait]`
  in `test_billing_customer_recovery_loop_postgres.py` raised
  `PreflightCleanupPending` at `composition/sources.py:97` while closing clients
  under its existing **25 ms** cleanup budget. This unchanged customer-only
  path does not call `classify_cycle()`. No timeout/assertion was weakened, no
  outside-scope code was changed, and no further broad PostgreSQL run was made.
- **PASS:** final documentation/diff checks and cleanup. pytest removed the
  disposable test database after interruption (absence verified); the isolated
  worktree PostgreSQL server was stopped. Final diff contains only the classifier,
  its policy/history regressions and this step's execution evidence.

Browser/provider acceptance is not applicable to this local classifier
correction; no live LBX or Kernel requests, provider writes, paid quota acceptance
or production enablement are claimed. The live naive-activation/date-only
precision limitation recorded in the planning evidence remains unchanged.

### Step 3 execution evidence — 2026-11-11

Scope: step 3 only, on `ANY-832`; the working tree was clean at entry.
No other implementation step, public/Kernel contract, persisted calendar format,
schema, generated artifact, dependency or production-enablement gate changed.

- Coverage assessment: policy and allowance-history tests already compared
  equivalent normalized instants, but did not reread raw LBX activation through
  the real normalizer after a committed calendar-month allowance. Recomputing
  month start in the response's new offset changed the original anchor.
- Before correction, six new PostgreSQL cases produced **4 failed / 2 passed**.
  Both positive and negative offsets, including UTC month-boundary crossings,
  lost the effective allowance and advanced access revision/outbox on an
  equivalent `Z` reread. Unchanged spelling and an original UTC frame passed.
  No manually corrected `CalendarEvidence` bypassed source normalization.
- After permanent provenance checks, the short claim loads the first issued
  calendar using the existing subscription/component/metric-ordered history
  query. The frozen subject carries that typed immutable evidence after the
  transaction closes. Purchases without technical terms and legacy rows without
  calendar evidence supply no frame; unbound candidates retain initial behavior.
- Integration converts only an explicitly zoned calendar-month activation into
  the historical anchor's proven explicit offset, then derives its month start.
  It does not substitute the historical anchor. Normalized proof is saved
  alongside the unchanged raw source strings. Integration remains database-free;
  apply still checks current history, permanent provenance and lease fences.
- The six main cases pass with fresh claim/apply sessions, full allowance-row
  equality, unchanged quantity/key/ID, full outbox-row equality and unchanged
  effective semantic state/revision. New observations and finite trust renewal
  remain allowed. A valid next cycle issues exactly one new allowance while
  retaining the first frame and original row.
- Controls cover changed activation month and cycle boundaries, naive activation,
  mixed precision, unrelated subscription/component/metric history, legacy UTC
  rows, no technical terms, date/unresolved/missing historical offset, unbound
  candidates and unchanged instance-based anchors. Invalid calendar evidence
  still omits the metric allowance without rewriting immutable history.
- Focused verification: **169 policy/normalization tests passed** before adding
  the two unbound-candidate cases; all final policy cases also passed in the
  canonical fast suite. The three affected PostgreSQL suites initially passed
  **69/72**. Two controls were corrected to assert the existing absent-cycle
  behavior for naive activation; the legacy fixture was corrected to store SQL
  NULL rather than JSON null. The unchanged production correction then passed
  **11/11** focused repeats, covering those three controls and all six main
  cases with full outbox assertions. Together these runs verify all **72**
  distinct affected PostgreSQL scenarios; no full-PostgreSQL PASS is claimed.
- **PASS:** `npm run check:fast`: documentation, generated freshness,
  architecture, API Ruff check/format, web boundaries (**38**), web components
  (**414**), web ESLint and API fast tests (**1906**). No dependencies were
  installed. Existing local Kernel mock/origin/token settings were disabled or
  cleared in command environments only; no saved settings changed.
- **SKIPPED by explicit owner choice:** the full PostgreSQL suite and
  `npm run check`; verification was limited to affected PostgreSQL scenarios
  and `check:fast`, following the same scope preference recorded for step 2.
- Review: applied correctness and payment/security checklists; traced HTTP,
  worker, inventory and operator consumers through shared reconciliation and
  immutable allowance classification. Peer impact: **None**; local Kernel source
  `0f950355e3f282c6d5f036542f71e1f2b4295827` was inspected for allowance/usage
  ownership. This correction preserves its consumed identity/quantity contract;
  no peer files changed.
- Runtime evidence is disposable local PostgreSQL with simulated source
  transports. Browser E2E and live-provider acceptance are **SKIPPED**: this step
  changes internal calendar normalization and has no UI or source-enablement
  scope. No live LBX request or write was needed.
- **PASS:** final `npm run docs:check`, focused Ruff check/format and
  `git diff --check`. pytest removed its disposable database (absence verified)
  and the isolated worktree PostgreSQL server was stopped. No commit, push,
  publication or deployment was performed.
