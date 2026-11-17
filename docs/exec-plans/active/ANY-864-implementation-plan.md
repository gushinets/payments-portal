# ANY-864 — Monthly LBX instance-start allowance

Status: local implementation complete; verification recorded below;
live acceptance remains NOT_RUN.
Issue: [ANY-864](https://linear.app/paveldik/issue/ANY-864).
Baseline: `ece3590b857adb120182949dfe291116ca8ba510`; branch `ANY-864`.
Original implementation baseline: `6e3d458a572b16a161db72f718cbcc0a5055739a`.

## Objective and authority

The ordinary worker must issue one accepted SIMULATED Brief Decoder allowance
of 300 analyses for the observed monthly instance-start cycle, retaining its ID
and quantity on same-cycle reads and recovery. Follow root/API instructions,
ADR 0005 and ANY-504's accepted B10 calendar decision. Raw dates never become
guessed UTC bounds; full ownership, terms and eligible subscription proof remain
required. No migration, public wire change, financial operation or production
enablement is part of this fix.

## Decisions and implementation

- Pass the accepted `CommercialPeriod` into LBX calendar normalization. Enable
  the new representation only for `month / 1 / instance_start` with date-only
  current-cycle bounds and a naive, exactly-midnight start. Other profiles and
  nonzero times/offsets retain their existing behavior. Equivalent epoch-midnight
  spellings never establish an anchor.
- Share the bounded start-date interpretation between normalization and
  completeness. In the new path both present calendar starts must be no later
  than the cycle start. Preserve original start/end checks and `_calendar_ordered`;
  do not replace parsed timestamps globally. Keep raw observation fields intact.
- Reuse existing classification, immutable issuance, review resolution, paid
  revision and outbox ownership. Preserve accepted quantities and historical IDs.
- Rebase onto main after ANY-766's merge at `ece3590b`; preserve its activation,
  Snapshot V3, metering and recipient-specific outbox behavior. Keep ANY-832
  separate. Earlier isolated compatibility checks used ANY-832 `01d526b9`,
  Portal ANY-766 `11c524bf` and Kernel `d132aea6`; those results remain historical.

## Verification and progress

- [x] Assess coverage and reproduce both existing failures: calendar completeness
  rejects same-day mixed precision, and the normalizer reports `unresolved`.
  The existing policy/normalization baseline passed 136 tests during planning.
- [x] Add and run failing regressions before changing runtime code: 16 FAIL /
  27 PASS in the new normalization suite; both worker/PostgreSQL cases FAIL
  because the expected allowance/revision is absent. Logs:
  `/tmp/any864-unit-red.log`, `/tmp/any864-postgres-red.log`.
- [x] Implement the bounded representation and explicit order checks. Preserve
  the existing all-date completeness policy: the new order proof applies only
  when interpreting naive midnight starts, not unrelated date-only evidence.
  New and existing normalization/policy suites: 179 PASS after the fix.
- [x] Verify worker-to-PostgreSQL-to-authenticated-API issuance, stable rereads,
  prior empty-allowance review recovery, block/unblock and a proven later cycle.
  The new worker cases and existing reconciliation/rebase/recovery/read suites:
  80 PASS (`/tmp/any864-postgres-focused.log`). The fixture establishes ownership,
  consent and accepted terms through ordinary purchase preparation; it does not
  preselect a primary or write paid flags. API reads make no source requests.
- [x] Run relevant existing suites, canonical checks and inspect the final diff.
  Latest local `npm run check`: PASS (2360 backend fast tests, 1215 PostgreSQL
  tests, frontend checks and production build). Live LBX acceptance and browser
  E2E remain NOT_RUN.
- [x] Record combined-branch evidence or its exact limitation.
  An isolated ANY-832 + ANY-766 + ANY-864 source combination passes 516 unit
  checks and all 96 selected PostgreSQL cases after fixture adaptations described
  below. The local real-HTTP Portal/Kernel monthly scenario also passes.

## Compatibility evidence

Before the rebase, the working branch excluded both then-unmerged PRs.
The historical temporary combination is `/tmp/any864-compat-eu59rfne`; its
`any864-source-manifest.json` records both branch heads and source-file hashes.
The integration retains ANY-832's calendar-month offset/history and inventory
receipt rules alongside ANY-766's MeteringPolicy, reconciliation v2 and consumer
outbox ownership. Conflicting documentation is outside the runtime check.

Signature-only adaptations pass full periods to existing normalizer test calls.
The new worker fixture installs ANY-766's recipient policy before asserting its
outbox, and one existing snapshot fixture registers both tariffs in ANY-832's
multi-tariff transport. The recipient-policy setup is now also applied to this
branch's worker fixture after the rebase. The ANY-832-specific snapshot change
remains temporary. Neither adaptation changes runtime behavior under test.
Logs: `/tmp/any864-compat-unit.log`, `/tmp/any864-compat-postgres.log` and
`/tmp/any864-compat-postgres-corrected.log` (the latter reruns the three fixture-
affected cases, including one previously passing case).

The dedicated joint scenario uses the real Portal API/embedded worker, Kernel
API/worker, service/session authentication and two independent PostgreSQLs.
LBX and AI are explicit local substitutes. Brief Decoder has accepted quantity
300 and the observed P03 dates; its primary and allowance are established by
the ordinary worker. The check covers activation receipts, Snapshot v3,
successful execution, replay, same-cycle identity and usage preservation through
block/restore, a separate later allowance and immutable old usage. Kernel's
new allowance correctly remains `unobserved` until first admission; readback
never invents zero usage. This is local compatibility evidence, not live P03.

The prepared Kernel checkout contains pre-existing local changes. The first
successful joint run records their diff hash in its private `sources.json`;
the final joint run passes against a clean archive of exact head `d132aea6`,
reusing only the prepared dependencies and verifying imports resolve to that
archive (`/tmp/any864-kernel-clean-ihxve0fy`). Result: 1 PASS in 116.80 seconds;
log `/tmp/any864-joint-clean-kernel.log`. No peer source changes are required.

## Rebase onto merged ANY-766 — 2026-11-16

The rebase moves original commit `1dea1b98` onto main `ece3590b`, which contains
the final ANY-766 squash merge. The only textual conflict is in the background
operations guide: retain the ANY-864 monthly-midnight paragraph followed by
main's current wire heading and Snapshot V3/durable delivery documentation.
The LBX calendar/reconciliation implementation is unchanged from `1dea1b98`.

Before adapting the worker fixture, its two PostgreSQL cases reproduce 1 FAIL /
1 PASS: allowance issuance succeeds, but the outbox assertion receives `None`
instead of revision 1 because no consumer policy is registered. The fixture now
installs the same synthetic recipient policy as the existing reconciliation
suite; all original assertions remain. Log:
`/tmp/any864-rebase-oabqg092/fixture-before.log`.
Focused calendar/policy checks pass all 99 cases before this fixture change.
After adaptation, the focused worker/reconciliation/rebase/recovery/read/snapshot/
recipient/delivery selection records 176 PASS / 1 setup ERROR (an existing
rollback fixture's SQL statement timeout during concurrent frontend work).
Both complete worker/reconciliation modules then pass unchanged: 26 PASS.
Logs: `/tmp/any864-rebase-oabqg092/postgres-focused.log` and
`/tmp/any864-rebase-oabqg092/postgres-rerun.log`.

The complete canonical `npm run check` exits 0 with docs, generated drift,
architecture, Ruff, all 2335 backend fast tests, 38 frontend boundary checks,
454 component tests, lint and the production web build passing. The PostgreSQL
partition completes all 1212 collected cases across four isolated processes:
1211 PASS / 1 SKIP, no failures or errors, in 486.9 seconds. The skipped ANY-766
two-consumer TCP checkpoint requires the opt-in `ANY766_KERNEL_ROOT`; it and
browser E2E are NOT_RUN in this rebase verification. Earlier joint evidence
above remains historical. The first canonical attempt records four frontend
5-second timeouts; the successful complete repeat uses the supported
`VITEST_MAX_WORKERS=2` setting without changing assertions or timeouts.
Log: `/tmp/any864-rebase-oabqg092/canonical-bounded.log`; per-process JUnit and
collection records: `.harness/test-runs/deaed22df518429183cdac157f9e8315`.

`git range-diff` confirms that the rebased patch changes only the recipient
fixture setup and documentation relative to the original patch. Both LBX
implementation files and the new calendar unit suite remain byte-identical;
main's policy tests and all Snapshot V3/activation/delivery changes are retained.
The final branch diff still contains only the original eight ANY-864 files.

## Original implementation verification

Prepared dependencies only; verification performs no installation, deployment
or external billing write.
Canonical/pytest subprocesses disable the inherited Kernel mock/connection,
OTLP export and automatic source work. Joint processes explicitly run ordinary
workers against loopback sources. Test resources use synthetic transports or
loopback origins. PostgreSQL URLs are derived privately from this task's local
test server and use fresh unique `_tests` databases. Each fixture owns cleanup.

The canonical `npm run check` stages cover docs, generated drift, architecture,
Ruff, frontend boundaries/components/lint, backend fast tests and the web build.
All of those stages PASS: 38 frontend boundary checks, 414 component tests and
1914 backend fast tests; Ruff and the web build also pass. The test-only Kernel
connection overrides resolve inherited local configuration failures without
changing repository settings. Log: `/tmp/any864-check-full.log`.
The full PostgreSQL partition ran in four processes with independent fresh
databases using a temporary copy of ANY-766's existing dispatcher. The collection
manifests match the complete 997-test selection exactly. Result: 994 PASS /
3 FAIL in 1037.9 seconds. Log: `/tmp/any864-postgres-full-parallel.log`;
JUnit/collection records: `/tmp/any864-pg-398aecccf4ef40d9bb8d1554b0449001`.
The failures were the existing customer recovery `expired_claim` case
(`preflight_cleanup_pending`, with a 25ms cleanup budget) and both inventory
urgent-scheduling cases (attempt count 1 instead of 2). Both complete modules
then PASS serially: 15 tests in 34.70 seconds, unchanged code and assertions
(`/tmp/any864-postgres-serial-rerun.log`). Do not present the parallel run as
clean or infer that these scheduling/cleanup checks are stable under load.
The sequential canonical PostgreSQL invocation was interrupted to switch to
this execution; the single canonical command is not an uninterrupted PASS.
The browser suite is NOT_RUN: no UI changes, and affected behavior is exercised
through authenticated ASGI and real TCP application journeys.

Correctness review traces raw source evidence through bounded normalization,
the existing cycle classifier, immutable issuance, review resolution, revision/
outbox commit and authenticated reads. The change does not alter those owners,
source trust or financial operations, and does not infer UTC bounds.

Use only disposable local test resources and prepared dependencies. Record
PASS/FAIL/BLOCKED/NOT_RUN against the actual source revision. A live P03 run and
test-LBX mutations need separate authorization; the live criterion is one actual
300-analysis allowance from the ordinary worker, with stable reread identity.
Do not replace it with a grant-only or synthetic PASS.
