# ANY-832 implementation record

**Status** Implemented and verified locally.

**Updated** 2026-11-18.

**Issue** [ANY-832](https://linear.app/paveldik/issue/ANY-832/fix-deferred-pr-164-inventory-completeness-and-calendar-allowance-edge).

**Branch and PR** `ANY-832` against `main`. [PR #168](https://github.com/gushinets/payments-portal/pull/168).

The verification below covers baseline `900e3f2c` plus the local
corrections for REV-9 through REV-12. The merge base for this review is
`aa9d8f99`. Billing authority and acceptance gates are defined by
[ADR 0005](../../architecture/decisions/0005-external-billing-boundary.md).

## Implemented outcome

### Inventory and admission

Inventory combines permanent bindings, observed agreement/tariff relationships
and current point proofs. An object-local refusal leaves the implicated products
incomplete. Authorization, discovery and shared-budget failures affect the
whole scan. A timely scope refusal still counts if canonical apply contends
for the user lock.

A contradiction from any shared subscription reconciliation can be retained
before canonical apply or deferred to the existing customer-inventory job
after local contention. The next collection writes deferred points to immutable
history under the user lock and clears the queue copy in the same transaction.
Final validation checks pending points committed after the collection snapshot
and invalidates the implicated product decisions. These points restrict decisions. Canonical
receipts supply source authority.

Final apply checks each bound subscription's relationship history once under
the user lock. A validated latest authoritative point bounds the SQL query
before duplicate restrictions are compacted. The cutoff excludes only
observations whose reads finished strictly before the resolving read began.
Overlapping reads and legacy restrictions retain their documented behavior.
Auto-selection and audited `select-primary` check the relevant product.
Financial CREATE, admission blocking and `restore-original` require
customer-wide completeness and current source receipts.

The [inventory runbook](../../engineering/billing-background-operations.md#inventory-history-and-admission)
defines the refusal, ordering and retry rules. The
[data model](../../architecture/payment-portal-data-model.md#reconciliation-and-access-tables)
defines the evidence and provenance.

### Calendar allowances

Annual `calendar_month` cycles preserve the activation month, accepted
duration and original phase. A supported first cycle can begin on the first
day of the month before mid-month activation. If LBX has supplied an exact
activation instant, metering requires a fresh authoritative read begun at or
after that instant plus clock skew. Each start field keeps its last trusted
exact value when a later response omits it or has lower precision. The
canonical observation carries the resolved dates forward, including known
absence. A legacy lookup runs before taking the user lock, and apply verifies
that its basis and source fence are still current.

The date-only annual profile from stand 043 can issue an allowance on eligible
active proof. Its dates carry no inferred UTC bounds. Equivalent timestamp
offsets preserve the frozen allowance and identity. The
[calendar runbook](../../engineering/billing-background-operations.md#cycle-and-immutable-allowance-identity)
defines issuance and activation. The
[stand evidence](../../engineering/ANY-832-lbx-annual-calendar-evidence.md)
records the actual first-cycle payload and its limits.

## ANY-766 integration handoff

The branch inherits ANY-766 from `main`. Primary selection and reconciliation
share the paid-state writer, metering policy, immutable allowance identities
and activation receipts. AccessSnapshot V3 remains the Portal authority for
paid grants and approved allowances. Kernel owns used and reserved quantities.
The follow-up uses existing observations and work items. It adds no DDL and
changes no public HTTP or Kernel contract.

## Verification record

The [local PostgreSQL regression suite](../../../apps/api/tests/test_any832_regressions_postgres.py)
contains 14 cases. The latest implementation run verified:

- **REV-9** — less precise and omitted start fields preserve an exact bound,
  including legacy canonical v2 evidence. A local AccessSnapshot V3 check
  confirmed quota appears only after activation and a fresh source read.
- **REV-10** — an independent subscription poll retains its observed
  restriction after two local write refusals. Later inventory honors it when
  the source is omitted and its point read fails. An independent product still selects its primary.
- **REV-11** — final apply reads each bound history once, and SQL prunes
  superseded observations before compaction. Equal and overlapping read
  intervals preserve their implications.
- **REV-12** — legacy activation lookup runs outside the user lock. With
  125,000 synthetic date-only observations, the concurrent operation obtained
  the lock in all three runs. Both repeat reconciliations skipped activation
  history lookup. Changing the basis before apply refused the stale write.

`npm run check:fast` passed on retry with four Vitest workers after a frontend
Sentry test timeout. The run passed 2,408 API tests, 454 web component tests,
38 boundary tests, generated-contract checks, lint, formatting, architecture
and documentation checks. The separate full PostgreSQL partition passed all
1,377 tests on disposable local PostgreSQL 18.6, including the Portal–Kernel
TCP auth/access checkpoint against Kernel `de7c1cd9`. External LBX responses
were simulated. These runs do not certify a production web build, browser or
business-flow E2E, or live-provider acceptance.

The follow-up review passed 69 targeted PostgreSQL checks, including the 14
local regressions, the inventory history and refactoring suites, and a
temporary diagnostic for retry-budget expiry after the first refused write.
The diagnostic confirmed that the pending point was replayed and still
blocked the implicated product on the next collection.

### Earlier integration evidence

The PR #168 repeat-read correction preserves both implicated products when
contradictory discovery is followed by an unavailable repeat GET. REV-6,
REV-7 and REV-8 established, respectively, restriction retention after refused
apply, strict receipt/fence checks in financial admission, and isolation from a
conclusive sibling's local review. The current suites retain those regressions.
[PR #168 review thread](https://github.com/gushinets/payments-portal/pull/168#discussion_r4582990040).

The November 16 rebase combined Portal ANY-832 `b13454ec` with `main`
`ece3590b`. Its earlier focused run passed 293 PostgreSQL cases and 2,361 API
fast tests. Historical cross-repository evidence used Portal `ec10983e` and
Kernel `9c00d812`. Those pins describe the earlier runs.
[Portal PR #167](https://github.com/gushinets/payments-portal/pull/167) ·
[Kernel PR #267](https://github.com/gushinets/anytoolai-platform/pull/267).
