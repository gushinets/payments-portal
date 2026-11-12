# ANY-832 implementation plan

Status: **IN PROGRESS** — steps 1–4 complete; step 5 pending.
Issue: [ANY-832](https://linear.app/paveldik/issue/ANY-832/fix-deferred-pr-164-inventory-completeness-and-calendar-allowance-edge)
Predecessor: [PR #164](https://github.com/gushinets/payments-portal/pull/164)
Execution branch: `ANY-832`.

## Goal and boundaries

Prevent primary selection when inventory is incomplete for any implicated
product. Support coherent annual calendar cycles outside January, including
first allowance issuance through the full normalizer. Preserve established
allowances across equivalent timestamp encodings.

Follow the [root guide](../../../AGENTS.md),
[API guide](../../../apps/api/AGENTS.md),
[coding conventions](../../engineering/CODING_CONVENTIONS.md) and billing
authority in [ADR 0005](../../architecture/decisions/0005-external-billing-boundary.md).

Keep public APIs, Kernel contracts, persisted calendar formats and issued
allowances unchanged. No migration or Kernel implementation is required.
Preserve accepted purchase terms, permanent bindings, finite source trust,
leases/fences, authoritative negatives and production-enablement gates.
No live provider writes or production enablement are part of this plan.

## Implementation steps

### 1. Include every implicated product in inventory completeness

- [x] Add failing PostgreSQL regressions before changing the collector.
- [x] In [purchase_inventory.py](../../../apps/api/app/composition/purchase_inventory.py),
  calculate implicated products as the union of permanent subscription binding,
  agreement ownership and matching accepted tariffs.
- [x] Accumulate discovery and point relationships before early exits. Failed
  reads and list/point contradictions leave every implicated product incomplete,
  even when initial and final listings agree.
- [x] Use the same relationship rule for final discovery verification. Preserve
  unrelated-product independence, original recovery, consistent ended/closed
  controls and stricter customer-wide financial CREATE admission. Shared
  authentication, scope, deadline and cleanup failures remain customer-wide.

**Acceptance:** automatic and audited primary selection reject unresolved
candidates for every implicated product; healthy unrelated products remain
selectable. Cover failed subscription/agreement GETs, cross-product ownership
and tariffs, list/point disagreements, conflicts and terminal controls in the
scoped-inventory and paid-access review-regression suites.

### 2. Support annual calendar cycles outside January

- [x] Add failing date-only and explicitly zoned annual regressions.
- [x] In [paid_cycles.py](../../../apps/api/app/domains/billing/paid_cycles.py),
  remove only the January requirement for `year / calendar_month`.
- [x] Preserve the first day of the activation month, accepted period length,
  calendar arithmetic and frozen original anchor. Reject changed phase, including
  October activation followed by a January annual start.

**Acceptance:** coherent non-January cycles classify as FIRST, equivalent repeats
as SAME with unchanged key/allowance ID, and the next full period as LATER.
Cover November/January, leap years, multi-year lengths and invalid lengths/phases
in policy and PostgreSQL allowance-history tests. Preserve monthly behavior,
inclusive date-only ends, half-open timestamp ends and precision safeguards.

### 3. Preserve the established calendar frame across equivalent rereads

- [x] Add a failing PostgreSQL regression through the real normalizer, persisted
  allowance history and shared source apply.
- [x] Add `established_calendar: CalendarEvidence | None = None` to
  `ReconciliationSubject`. During `claim_reconciliation`, after provenance checks,
  load the first issued calendar for the exact subscription, service component
  and metric using the ordered allowance-history query.
- [x] Pass that immutable context to
  [calendar.py](../../../apps/api/app/integrations/lbx/calendar.py). For
  `calendar_month` with a proven historical offset, convert explicitly zoned
  activation into that offset before deriving month start. Compute the anchor;
  do not substitute the historical anchor.
- [x] Normalize before saving `SubscriptionProof`; retain original source
  strings. Keep the shared HTTP/worker/inventory/operator path database-free in
  Integration and preserve current-history and fencing checks during apply.
- [x] Retain initial behavior without suitable history, including unbound
  candidates, purchases without technical terms and legacy rows. Do not infer
  timezones for naive or mixed-precision input.

**Acceptance:** equivalent `+03:00`/`Z` rereads preserve the complete frozen
allowance row, ID, key and quantity. With unchanged semantics and unexpired
deadlines, effective paid state, revision and outbox remain unchanged; source
trust renewal is allowed. Use fresh sessions and cover positive/negative offsets,
month crossings, a valid next cycle, genuine changes and unrelated history.

### 4. Preserve bound point-read product relationships — REV-1

- [x] Add PostgreSQL regressions with distinct accepted tariffs for A and B:
  A's canonical subscription/agreement IDs remain bound, but its point read
  returns B's tariff. Cover unchanged old-tariff listings and omission from both
  listings through real acceptance, reconciliation and primary writes.
- [x] In [reconciliation_contracts.py](../../../apps/api/app/domains/billing/reconciliation_contracts.py),
  retain point agreement/tariff relationships in a small provider-neutral
  structure. Populate it at the validated Integration boundary for every timely
  successful point read, including MISMATCH/INCOMPLETE results. Failed or absent
  reads supply none. Keep point-URL resource selection without self-ID comparison.
- [x] Carry the optional relationship through shared read/apply, serialization,
  stored observation comparison, operator `reuse` and original recovery.
  Preserve compatibility with observations lacking it; absence proves no
  candidate irrelevant.
- [x] In [purchase_inventory.py](../../../apps/api/app/composition/purchase_inventory.py),
  accumulate permanent, accepted, discovery and all point implications before
  fast paths or mismatch/omission handling. Later observations cannot erase
  earlier implications or contradictions, including after a terminal read.
- [x] Preserve committed negatives, leases/fences, unrelated-product independence
  and customer-wide financial admission. Relationships do not authorize rebind,
  adoption, accepted-term changes or another financial CREATE. Add no catalog
  mirror or extra provider reread to recover already obtained facts.

**Acceptance:** B remains incomplete; automatic primary stays unset;
`require_clear(..., primary=True)` refuses selection; attempted audited selection
leaves its review open. Proven A conflicts remain durable; unrelated C remains
selectable. Preserve consistent ended/closed controls.

**Checks:** extend [scoped inventory](../../../apps/api/tests/test_billing_scoped_inventory_postgres.py)
and [paid-access review regressions](../../../apps/api/tests/test_paid_access_review_regressions_postgres.py).
Cover successful point followed by unavailable tariff policy, operator reuse,
serialization and absent optional relationships. Use existing source/operator
fixtures; do not mock the collector or writer.

### 5. Admit the first supported calendar timestamp cycle end to end — REV-2

For `year / calendar_month`, activation `2026-11-11T12:34:56+03:00` and cycle
`[2026-11-01T00:00:00+03:00, 2027-11-01T00:00:00+03:00)`,
`_calendar_complete()` rejects the cycle because its start precedes activation.
The classifier supports it, but the full normalizer returns `cycle=None`.

- [ ] Reproduce the failure through simulated LBX HTTP, the actual parser,
  `normalize_subscription()`, shared source apply and PostgreSQL allowance
  issuance. Accept an annual offer through the real local acceptance path;
  do not edit a monthly accepted snapshot or inject prepared `CalendarEvidence`.
- [ ] In [LBX reconciliation](../../../apps/api/app/integrations/lbx/reconciliation.py),
  make start containment respect `calendar_month`: the first period may start
  at the proven first-day boundary of the activation month before activation.
  Use the same explicit frame as
  [calendar normalization](../../../apps/api/app/integrations/lbx/calendar.py),
  including established history. Reject arbitrary earlier starts.
- [ ] Keep [cycle classification](../../../apps/api/app/domains/billing/paid_cycles.py)
  responsible for accepted duration, phase, frozen anchor, SAME/LATER and no
  backfill. Preserve ordering, finite ends, instance-based anchors and
  naive/mixed-precision safeguards. Cover both monthly and annual
  `calendar_month`; do not infer a provider timezone.
- [ ] Commit the first allowance, reopen sessions, claim and reread SAME, then
  apply a coherent next annual cycle. SAME preserves the full frozen row,
  ID/key/quantity and, without other semantic changes or expired deadlines,
  effective state/revision/outbox. Trust renewal is allowed. LATER creates
  exactly one allowance and retains the original frame. Keep clocks consistent
  with cycles, source-read deadlines and leases.
- [ ] Cover positive/negative offsets, exact-boundary activation, date-only
  input, monthly behavior and an instance-based cycle starting before activation.
  Wrong boundaries, duration or phase must omit the metric allowance without
  rewriting history. Retain step 3's equivalent-offset controls.

**Acceptance:** supported annual timestamp input produces the first allowance
through the full normalizer and shared writer; SAME/LATER satisfy the guarantees
above. Naive activation combined with date-only bounds remains unresolved and
must not acquire UTC bounds.

**Checks:** extend [subscription normalization](../../../apps/api/tests/test_billing_subscription_reconciliation.py),
[paid reconciliation](../../../apps/api/tests/test_paid_access_reconciliation_postgres.py)
and, where needed, [policy tests](../../../apps/api/tests/test_paid_access_policy.py).
Reuse history tests for arithmetic/immutability; add the missing input-to-writer
path rather than duplicating the full matrix.

## Remaining verification and completion

- [ ] Establish the step 5 regression before the fix, then run its focused
  normalization/policy and PostgreSQL suites.
- [ ] Recheck automatic/audited primary selection, first issuance, SAME/LATER,
  unrelated-product independence, finite trust, immutable history and fencing.
- [ ] Run `npm run check:fast`, `npm run docs:check` and `git diff --check` after
  step 5. Reuse valid results when code, environment and coverage still match.
- [ ] Inspect the final diff and new files for unrelated changes.

Use only the isolated worktree test PostgreSQL through the repository harness;
pytest owns its disposable database. A full PostgreSQL rerun and `npm run check`
are not required for this scoped correction. No live acceptance is required.

## Review notes — steps 1–4

- **Inventory:** regressions reproduced incorrect automatic and audited primary
  selection when a point read implicated another product despite unchanged or
  omitted discovery rows. Tests now assert persisted primary state, an open
  operator review, durable conflicts and unrelated-product independence in
  [scoped inventory](../../../apps/api/tests/test_billing_scoped_inventory_postgres.py)
  and [paid-access review regressions](../../../apps/api/tests/test_paid_access_review_regressions_postgres.py).
- **Annual cycles:** [policy regressions](../../../apps/api/tests/test_paid_access_policy.py)
  cover non-January FIRST/SAME/LATER, accepted duration and phase rejection.
  Full-normalizer first timestamp-cycle issuance remains step 5.
- **Calendar frame:** [shared-writer regressions](../../../apps/api/tests/test_paid_access_reconciliation_postgres.py)
  reread equivalent raw offsets after a committed allowance through fresh
  sessions. They check the frozen allowance row and unchanged effective state,
  revision and outbox, plus genuine-change and unrelated-history controls.

**Verified on 2026-11-12, local `ANY-832` changes:** `npm run check:fast` passed
(1911 API fast tests); 127 PostgreSQL tests passed across scoped inventory,
paid-access review regressions and
[primary-selection rebase](../../../apps/api/tests/test_paid_access_rebase_postgres.py).
The PostgreSQL checks used an isolated local server and simulated source HTTP.

**Limits:** the full PostgreSQL suite, `npm run check` and live-provider/Kernel
acceptance were not run. These results do not close step 5 or establish production
readiness.
