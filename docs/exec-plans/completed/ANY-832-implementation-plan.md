# ANY-832 implementation record

Status: **IMPLEMENTED ON BRANCH; focused verification passed; full-suite verification incomplete.**
Updated: 2026-11-16.
Issue: [ANY-832](https://linear.app/paveldik/issue/ANY-832/fix-deferred-pr-164-inventory-completeness-and-calendar-allowance-edge).
Predecessor: [PR #164](https://github.com/gushinets/payments-portal/pull/164).
Branch: `ANY-832`; PR base: `main`.

This record covers ANY-832, including REV-8 and the PR #168 repeat-read correction,
rebased onto `ece3590b857adb120182949dfe291116ca8ba510` (`main`, merged ANY-766
[PR #167](https://github.com/gushinets/payments-portal/pull/167)). The pre-rebase
head was `b13454ecdb47e3b8c187f6dbc99dfb06d7421cbe`, with base
`6e3d458a572b16a161db72f718cbcc0a5055739a`; those pins describe historical checks.

Earlier verification referenced `07cee6e2` plus then-local corrections and the
original base `2d278f62f0a2f7c4b40fb322618b268580de2301`. These historical pins
remain scoped to the dated results below. This record describes implemented
behavior and verification limits; it does not grant merge approval.
Billing authority remains [ADR 0005](../../architecture/decisions/0005-external-billing-boundary.md)
and its accepted specifications and dated decisions.

## Implemented outcome and scope

ANY-832 preserves unresolved cross-product inventory contradictions, allows
independently proven product decisions and corrects supported calendar allowance
edge cases. Public HTTP/Kernel contracts, permanent bindings, accepted terms,
finite source trust and production enablement gates are unchanged. No new table,
migration, dependency, catalog mirror, background process or durable decision-attempt
subsystem was introduced by ANY-832. ANY-766 was implemented independently and is
now inherited from `main`, including its migrations and backend integration.

### Inventory collection and history

[Composition](../../../apps/api/app/composition/purchase_inventory.py) owns bounded
source I/O and database-clock read intervals. The shared
[fact reducer](../../../apps/api/app/domains/purchases/inventory_facts.py) combines
permanent bindings, agreement ownership, accepted tariff matches and observed
relationships into product implications. Candidate-local failures preserve every
already implicated product as incomplete; authorization/scope, discovery and
shared-budget failures remain global.

[Retained history](../../../apps/api/app/domains/billing/inventory_history.py)
keeps contradictory bound relationships across scans, including when the source
later disappears from listings and its point read fails. Actual read intervals
order facts; an earlier claim fence cannot hide a later contradiction. Ordinary
canonical reads retain restrictions independently before apply, so an expired
work/source lease cannot discard an obtained contradiction. Such a supplemental
write cannot clear history; resolving evidence requires committed canonical apply
or an operator proof accepted by the shared source-claim validator.

The [storage reference](../../architecture/payment-portal-data-model.md#reconciliation-and-access-tables)
defines supplemental v2 provenance and legacy v1 handling. The
[runbook](../../engineering/billing-background-operations.md#inventory-history-and-admission)
defines interval ordering, product applicability and admission rules.

### Validation and application

[Inventory validation](../../../apps/api/app/domains/purchases/inventory.py)
separates common structural checks, product applicability and strict customer-wide
admission. A review or tariff change on A leaves B applicable only when B's decision
is unaffected. Selected-source and participating-source receipts remain exact.
Financial CREATE, admission blocking and `restore-original` additionally check
all used source receipts/fences, even when relationship sets have not changed.
The shared [claim/receipt validator](../../../apps/api/app/domains/billing/reconciliation_validation.py)
is read-only and grants no access by itself.

[Final application](../../../apps/api/app/domains/billing/discovery.py) preflights
all product actions under the user lock before writes. Stale products are deferred
through the existing customer job; applicable products, paid revision and outbox
commit together. A newer enqueue hint remains pending. Lost work ownership rolls
back the entire final apply. Audited `select-primary` retains its command, case,
own-source and target-product checks; refusal leaves the review open.

### Calendar allowances

- Annual `calendar_month` periods start in the activation month, including
  non-January starts, with the accepted duration and original phase preserved.
- A first supported timestamp cycle may begin at the proven first-day month
  boundary before mid-month activation. Arbitrary earlier starts remain invalid.
- Equivalent timestamp offsets use the established frame for the same
  subscription/component/metric. SAME preserves the entire frozen allowance
  row and ID; LATER creates exactly one new allowance for that metric/cycle.
  Equivalent rereads with unchanged semantics and unexpired deadlines do not
  create extra paid revisions or outbox updates; finite trust may renew.
- Date-only inclusive and explicitly zoned timestamp half-open semantics remain
  distinct. Naive/mixed input gains no invented timezone. Changed duration or
  phase omits the affected allowance without rewriting history.

The [cycle runbook](../../engineering/billing-background-operations.md#cycle-and-immutable-allowance-identity)
owns operational semantics. Classification remains in
[paid_cycles.py](../../../apps/api/app/domains/billing/paid_cycles.py), with source
normalization and retained history feeding the existing allowance writer.

## ANY-766 integration handoff

The current branch includes ANY-766 through the `main` revision above. Rebase
resolution preserves both implementations at the overlapping composition,
`billing/discovery.py`, `billing/reconciliation.py` and
`billing/reconciliation_contracts.py` boundaries.

Earlier combined checks used these exact inspected revisions:

- [Portal PR #167](https://github.com/gushinets/payments-portal/pull/167):
  `ec10983ef174fb59ecbf3dcf714a2f75647f8de1`.
- [Kernel PR #267](https://github.com/gushinets/anytoolai-platform/pull/267):
  `9c00d812a5077455a351a352b190cd58c383ea97`.

These historical pins scope the earlier combined results below; they do not
certify the rebased branch or the current paired Kernel revision.

The integrated branch retains:

- ANY-832's read intervals, `established_calendar`, `point_relationship`,
  supplemental history, shared claim/receipt validation, product preflight and
  queue-hint handling. Ordinary read/refused-apply retention and strict
  CREATE/restore receipts remain enforced.
- ANY-766's `MeteringPolicy` at paid-writer calls, v2 canonical and
  primary-selection writers, activation receipts and immutable observation guards.
  New canonical observations use v2; history and receipt readers use the owner's
  `RECONCILIATION_READ_SCHEMAS` vocabulary accepting v1 and v2.
  Supplemental relationship v2 is a separate schema from canonical v2.
- The sole paid-state writer, frozen technical ownership, AccessSnapshot V3,
  P/R separation and recipient-specific delivery. Kernel remains the authority
  for used/reserved quantities; inventory admission does not consume usage.

## Verification record

The latest verification is the 2026-11-16 rebase entry. The older 2026-11-13
record covers REV-6 (ordinary read lost after refused apply), REV-7 (strict
admission accepted a stale source receipt) and REV-8. Earlier REV-3/4/5 and
PLAN-1/2 regressions remain in the affected suites.

### ANY-766 rebase integration — 2026-11-16

The resolved tree combined pre-rebase ANY-832 `b13454ec` with `main` `ece3590b`.
Before the documentation refresh, all 857 tracked files matched the previously
checked temporary combination byte for byte, including the test-fixture repair.
This permits reuse of its **2361 API fast tests** and **293 distinct PostgreSQL
cases**: 230 inventory/history/primary/reconciliation/usage cases, all 37
AccessSnapshot cases, and 26 ANY-766 purchase-terms/technical-source cases.

The additional integration regression is
`test_consumer_filtering_precedes_deadlines_and_policy_change_keeps_paid_revision`.
It passed on unmodified `main`, failed with `KeyError: 702` on the combination,
and passed after registering tariff 702 in `PurchaseTransport.offers`. The repair
preserves ANY-832's explicit multi-offer transport and ANY-766's two-consumer
scenario; it is included in the 37 AccessSnapshot cases above.

After rebase, `npm run test:api:fast` passed **2361 tests** again on the actual
branch. A focused PostgreSQL rerun passed **40 cases**: all 37 AccessSnapshot
cases and the three disputed-repeat-read cases. These 40 are a subset of the
293 above, not additional distinct coverage. Architecture, documentation,
Ruff/format (388 API files) and `git diff --check` also passed. Full
`npm run check` was attempted again and stopped at the missing
`@hey-api/openapi-ts` package; no dependencies were installed.

PostgreSQL checks used an isolated disposable local PostgreSQL **18.6** container
and simulated external HTTP, not live-provider acceptance. Full `npm run check`,
frontend/build/E2E and paired Kernel HTTP acceptance are not certified by those
focused results. Older combined HTTP results remain historical.

### PR #168 failed repeat-read correction — 2026-11-16

The [confirmed review finding](https://github.com/gushinets/payments-portal/pull/168#discussion_r4582990040)
exposed a successful canonical read followed by contradictory agreement ownership
in both discovery lists and an unavailable repeat point GET. The collector now
marks the bound subscription uncertain before that repeat I/O, so failure cannot
leave either implicated product complete. An independent third product remains
eligible for primary selection.

The permanent regression in `test_billing_inventory_refactoring_postgres.py`
failed **1 case with 2 passing controls** before the fix. All three cases pass
afterward and assert both product completeness and actual primary application.

Verification ran against `3b067fe8` plus the correction subsequently committed
as `ee714fab`:

- **134 PostgreSQL cases passed** across inventory refactoring, scoped inventory,
  retained history and operator primary-selection suites. These used the available
  local PostgreSQL **18.6** image and simulated LBX, not the pinned 18.4 image or
  live-provider acceptance.
- **1940 API fast tests passed**; architecture and focused Ruff/format checks passed.
- Full `npm run check` stopped at the missing `@hey-api/openapi-ts` package in this
  worktree. No dependencies were installed; full-suite/frontend PASS is not claimed.

### REV-8 local correction

REV-8 separates source completeness from local review. A conclusively bound
sibling sharing a tariff no longer blocks another product's primary; its own
review remains open and prevents automatic selection.

Regression: **2 failed / 4 passed** before the fix, **6 passed** after it.
**137 PostgreSQL cases**, `check:fast`, `docs:check` and `git diff --check` passed.
Full `check`, web build, E2E and combined ANY-766 acceptance were not rerun.

### Earlier REV-6/REV-7 correction

- **198 distinct PostgreSQL cases passed on the ANY-832 working tree:** nine
  [admission regressions](../../../apps/api/tests/test_billing_inventory_admission_postgres.py)
  and 189 cases across scoped inventory, inventory refactoring/history, recovery
  CLI/review and paid-access inventory-failure suites. The nine new cases first
  reproduced five failures with four passing controls. They cover timely reads
  followed by lease refusal, omitted/unavailable sources, strict CREATE/restore
  refusal and successful independent-product controls. Four lease scenarios were
  rerun after making their timing precondition explicit; they are included in
  198, not additional cases. Application timeouts were unchanged.
- **`npm run check:fast` passed:** 1940 API, 414 web component and 38 boundary
  tests, plus generated contracts, architecture, docs, Ruff/format and web lint.
  The run explicitly used `KERNEL_MOCK_ENABLED=0`.
- **41 distinct combined PostgreSQL cases passed** with the ANY-766 pins above:
  the nine new admission cases, all 30 `test_paid_usage_postgres.py` cases and
  two legacy canonical/supplemental history cases. These exercise v1/v2 readers
  and immutable observations as well as strict admission.
- `git diff --check` passed. Follow-up changes remained unstaged and uncommitted.

### Earlier evidence and remaining limits

Before REV-6/REV-7, related normalization/history/policy unit tests passed
**205 cases**, and the pinned combination passed **110 PostgreSQL cases**.
Combined HTTP acceptance passed **2 tests, 1 deselected** in ANY-766's
`tools/joint_paid_runtime/tests/test_paid_runtime.py`:
`test_real_joint_paid_execution_replay_lifecycle_and_retained_storage` and
`test_review_policy_cutover_preserves_accepted_work_and_recipient_history`.
These used real Portal/Kernel HTTP, authentication and PostgreSQL, with external
LBX/AI and the second backend simulated. They covered equivalent-offset allowance
identity/counters/revisions/outbox, block/restore, execution/replay, future-period
non-activation, retained storage and policy cutover. The deselected test covers
the separate SMTP/browser identity journey.

Those HTTP results predate REV-6/REV-7, REV-8 and the PR #168 correction and do
not certify those changes. The current branch has focused verification only.
Full `npm run check` was attempted on 2026-11-16 and stopped at the missing
`@hey-api/openapi-ts` dependency. Joint HTTP acceptance has not been rerun after
the later corrections. No live-provider or production acceptance is claimed.

For documentation-only edits, use `npm run docs:check` and `git diff --check`.
Existing runtime evidence remains scoped to the implementation and revisions
above; later code or integration changes require checks of their affected paths.
