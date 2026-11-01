# ANY-715 QA execution

Status: LOCAL_QA_PASS; real LBX/webhook acceptance NOT_RUN
Date: 2026-10-30 (Asia/Ulaanbaatar)
Issue: [ANY-715](https://linear.app/paveldik/issue/ANY-715)
Baseline: `ANY-715` at `07556e4`, plus the uncommitted QA tests recorded below.

The original run below retains that baseline and its actual results. The
[2026-11-01 rebase verification](#rebase-verification--2026-11-01) records the
later local HEAD separately; original counts are not relabelled as current.

This report executes the owner-approved QA plan for background reconciliation,
uncertain-create recovery, durable webhook hints and audited operations. The
[completed implementation plan](../exec-plans/completed/ANY-715-implementation-plan.md)
preserves the approved baseline and subsequent decisions; the
[operations runbook](ANY-715-billing-operations.md) records current behavior and
commands under the repository's ADR 0005 authority chain.
All local LBX transitions are **SIMULATED**. Real integration checkpoints remain
separate from automated results.

## Environment and evidence

- Python 3.12 in the repository-root `.venv`; Node 24 and the installed repository
  dependencies. Canonical tests disable unattended billing worker startup.
- Worktree Compose project: `payments-b7e9ed31`. Its PostgreSQL server was stopped
  before QA and started specifically for this run. The already-running
  `payments-cf94dbf9` stack belongs to another worktree and is excluded.
- Shared pytest fixtures create, migrate, reset and drop the disposable `_tests`
  database. No application/production database migration is part of this run.
- LBX credentials are absent in the current worktree environment. Real billing
  mutations, payments and provider webhook configuration are excluded.
- Child test processes clear development Kernel/LBX connection settings and
  disable external telemetry. Synthetic transports explicitly supply source
  responses. Root `.env` and private runtime settings are not edited.
- Local detailed evidence is under `.harness/any715-qa-20261030/`. It is ignored
  runtime output, not a tracked source of credentials or provider payloads.

## Added acceptance coverage

[Same-tariff isolation tests](../../apps/api/tests/test_billing_qa_isolation_postgres.py)
add 12 PostgreSQL cases using real purchase/binding Application paths, the
production worker, real local persistence and simulated LBX HTTP responses.

Both product roles are exercised for `proposal_ai` and `brief_decoder`, with
separate accepted purchases, agreements and subscriptions under one customer.
The tests compare the untouched product's entire subscription, scope and work
rows, and its observation identities before and after targeted actions.

- Two lifecycle cases cover waiting, active, financial block, administrative
  block, ended and refused terminal revival.
- Ten failure cases cover a subscription-specific HTTP timeout, HTTP 404,
  missing total, effective-price mismatch and foreign agreement. Each case also
  expires only that product's support without source I/O and retries after the
  source recovers. Known conflicts stay blocked; incomplete reads can recover
  only through complete new proof.
- All cases retain accepted/legal evidence, permanent operation identities and
  holds. They assert no background business POST, primary selection, paid state,
  allowance, access revision or invalidation-outbox write.

[Webhook event acceptance tests](../../apps/api/tests/test_billing_qa_webhook_events_postgres.py)
add six cases, one for each supported event. Each uses the production HTTP
receiver and PostgreSQL to prove `queued` for the canonical subscription and
`ignored` for an unknown subscription, durable redacted receipts and exactly one
coalesced generation before the response. Receipt alone performs no source read,
changes no subscription facts and produces no paid-access writes. These cases
were added after the resumed full PostgreSQL partition had collected its tests;
they run as a separate selection after that partition releases the test database.

An initial test-only configuration allowed one GET attempt, which was consumed
by authenticating a newly created source client. Two mismatch cases therefore
correctly produced incomplete ownership instead of the intended owned conflict.
The QA fixture now uses the normal bounded GET policy and explicitly rejects
customer-read failures in these subscription-specific scenarios. This was a
test setup correction; application behavior was not changed.

## P0 scenario ledger

Each entry gives the exercised path and its acceptance assertions. Final run
status is **PASS / SIMULATED** for every P0/P1 entry. `scenario-evidence.json`
maps all 16 entries to actual passed testcase identities and their result XML.

1. **Browser-independent enrollment.**
   `test_billing_worker_atomic_link_enrollment_and_concurrent_sweeps`,
   `test_billing_worker_two_products_link_hint_reconcile_and_restart` and
   `test_billing_worker_embedded_lifespan_smoke_and_reserved_local_progress`
   exercise atomic linking/enrollment and embedded processing without browser
   calls. Repeated enrollment preserves future schedules and generation.
   This is server integration evidence, not a live browser-to-LBX session.

2. **Lifecycle and ownership proof.**
   `test_billing_subscription_reconciliation_lifecycle_history_and_minimum_reads`
   verifies the four point reads and waiting/active/block/end facts. The new
   `test_billing_qa_product_lifecycle_isolation` repeats transitions for each
   product and rejects terminal revival without changing the other product.

3. **Accepted historical terms.**
   The reconciliation lifecycle test changes current catalog prices while
   retaining effective accepted terms. Fast commercial/effective-drift tests and
   `test_billing_subscription_reconciliation_known_review_and_effective_mismatch`
   cover actual service/quantity/period/currency/total contradictions, including
   a known contradiction alongside a missing field. A later ordinary match
   leaves known review open.

4. **Finite source trust.**
   `test_billing_subscription_reconciliation_incomplete_outage_and_negative`,
   `test_billing_subscription_reconciliation_total_budget_and_404` and the new
   failure/expiry cases check six-hour support from read start, unchanged support
   on incomplete reads, negative supersession and fresh-proof-only recovery.

5. **LBX outage and local deadlines.**
   `test_billing_worker_local_expiry_is_provider_free_idempotent_and_refresh_wins`,
   reserved-lane tests and `test_billing_background_recovery_independent_deadline_and_no_send`
   verify provider-free expiry/escalation, idempotency and a concurrent refresh.
   Health tests distinguish source failure from failed local supervision.

6. **Lost CREATE response.**
   `test_billing_background_recovery_zero_one_multiple_and_delayed_visibility`,
   original-candidate refusals and lost-claim/late-I/O tests cover zero, unique,
   ambiguous, foreign and delayed candidates. Recovery GETs preserve the original
   operation and hold; only a uniquely proven original object can bind.

7. **Fixed active two-hour recovery window.**
   Independent deadline/no-send, resumed-unsent exact-deadline and legacy-null
   window tests distinguish UNKNOWN from PENDING/PROVEN_NOT_SENT. GETs and
   restarts cannot extend the active window. Existing Step 7 tests retain the
   explicit-user-only rule for another authorized no-send attempt.

8. **Restart, competing owners and late results.**
   Worker PostgreSQL tests cover concurrent claims, a hint during execution,
   expired live handlers, lost claim acknowledgement, timeout/cancellation,
   restart and delayed DB apply. Queue generations and subscription fences
   prevent stale apply/completion and preserve later hints.

9. **Product and owner isolation.**
   The 12 new cases compare both product roles, including timeout/404,
   missing/mismatching proof, local expiry and recovery. Existing background
   recovery and webhook cases cover original-candidate ownership and correlation
   refusal. `test_owned_inventory_paginates_without_sources_and_never_discloses_other_users`
   supplies a second actual Portal user and verifies owned inventory/deep-link
   isolation. Shared customer failures remain distinct from product-local faults.

10. **Resource ownership and local contention.**
    Worker HTTP/cleanup/DB tests verify reserved normal/urgent/local capacity and
    retained ownership after cancellation. Background `billing_busy` tests keep
    operation identity and CREATE authority unchanged. Seven worker-refusal
    regressions distinguish committed retry/quarantine progress from expired or
    lost ownership, failed commit and lost commit acknowledgement.

## P1 scenario ledger

1. **Backfill and repair.**
   Three-batch enrollment/restart, malformed-history quarantine and recovery
   repair tests preserve existing schedules, completed no-send work and live
   customer-send leases. Repair does not introduce a background CREATE.

2. **Customer inventory.**
   Background recovery fault tests cover all affected product scopes, atomic
   stale-batch refusal, incomplete/foreign/swapped/capped/unstable evidence and
   proof before excluding another product on the same tariff.

3. **Webhook transport and durable processing.**
   Fast webhook tests cover disabled 404, authentication-before-body/DB,
   duplicate/exact credentials, media type, declared/streamed 64 KiB limit,
   malformed fields and all six event types. PostgreSQL cases verify receipt
   plus work before acknowledgement, ignored foreign correlation, rollback,
   duplicates/reordering, delayed visibility, crash/reclaim, covered generations
   and polling convergence with delivery disabled. The six new event cases
   explicitly verify both queued/ignored outcomes through HTTP for every event.

4. **Privileged operator commands.**
   Recovery CLI suites exercise read-only/redacted inspect, shared recover and
   reconcile, both audited resolutions, stale evidence/fences, foreign or
   ambiguous candidates, competing workers, related deadline cases, audit
   rollback and identical-request replay. Ended facts remain ended and held;
   unsupported force-release/rebind/mark-paid commands are refused.

5. **Calendar, migrations and UI regression.**
   Reconciliation tests preserve date/timestamp precision and reject invalid or
   contradictory periods. Worker migration coverage upgrades populated work
   from `20261029_0003` to `20261028_0005`, verifies identity constraints and
   checks the supported downgrade. Browser purchase/Widget acceptance runs are
   recorded separately with their actual backend substitution boundary.

6. **Diagnostics and privacy.**
   Health, proof/progress metrics, CLI inspection, webhook receipt and safe-error
   assertions verify bounded diagnostics and exclusion of secrets/raw payloads.
   Failed source proof is not reported as newly verified trust. These are
   controlled automated assertions, not an audit of production logging.

## Verification

Focused PostgreSQL acceptance: **PASS, 12 cases** in 49.61 seconds.
Evidence: `isolation-final.log` and `isolation-final.xml` in the evidence directory.

Real local API smoke with LBX unconfigured: **PASS**. A temporary Uvicorn
process returned live/ready 200, billing `not_configured` with zero occupied or
pending slots, disabled webhook 404 before parsing an invalid body, and
Prometheus worker metrics from the actual `/metrics` route. Legal seeding was
disabled; readiness performed only its database availability read. The process
completed graceful shutdown with exit 0. Evidence: `runtime-smoke.json` and
`runtime-smoke.log`. This confirms unconfigured-mode runtime behavior, not a
configured LBX worker or real provider delivery.

Canonical check stages completed before interruption: documentation, generation
freshness, architecture, Python format/lint, **38 web boundary tests** including
TypeScript checks, **385 component tests**, web lint, **1,667 fast API tests**
with zero failures/skips, and the production web build. Evidence: `check.log`
and `api-fast.xml`. The original `npm run check` invocation was interrupted
during its PostgreSQL stage and has no successful final exit status. That
unfinished stage is resumed with the same source and environment through
`npm run test:api:postgres`; completed stages are not repeated.

Resumed PostgreSQL partition: **509 passed, 2 failed** out of 511 cases in
1,428.50 seconds. Both failures were the existing
`test_competing_first_publishers_are_serialized_and_deterministic` variants in
the historical commercial-mapping suite: PostgreSQL `55P03` became the expected
`mapping_storage_busy` refusal after the test helper's 200 ms lock budget. All
ANY-715 reconciliation, recovery, worker, webhook and operator cases passed.
The raw partition remains recorded as FAIL in `postgres.log` / `api-postgres.xml`.

Both legacy cases passed unchanged in an isolated reproduction (5.65 seconds),
confirming a timing-sensitive success-path fixture. The test helper now accepts
an explicit lock budget; only the successful competing-publisher scenario uses
two seconds. Other cases retain 200 ms, including the explicit bounded busy/
deadline-refusal test. Business assertions, future deadlines and application
locking/configuration are unchanged. The entire affected file then passed
**28/28** in 52.58 seconds, followed by two further **2/2** race runs in 5.15 and
5.16 seconds. Evidence: `legacy-repro.xml`, `legacy-final.xml` and
`legacy-race-repeat-{1,2}.xml` with their logs. This is a test reliability
correction, not a change to a billing or publication policy.

Additional six-event webhook selection: **6/6 PASS** in 17.82 seconds. Evidence:
`webhook-events.xml`, `webhook-events.log` and source/metadata records. Across
the completed partition and corrective selections, all **517 distinct PostgreSQL
cases** have a final passing result. There was no new all-green monolithic
`npm run check` or full PostgreSQL invocation after the test-only correction;
completed unaffected stages were reused and the affected file was rerun.

Desktop/mobile browser regression: **PASS, 14 cases**, zero unexpected, flaky or
skipped results in 70.31 seconds. Command:
`npm run test:e2e -- any709-purchase.spec.ts --workers=2`.
This uses the local production web build with all API and Widget SDK responses
substituted in Playwright. It covers purchase acceptance/preparation, Continue/
Manage, cabinet selection, Widget open/refresh/reload, slow preparation, UNKNOWN
without catalog, SDK/readiness failure and cross-tab logout. Existing assertions
check no horizontal overflow and no serious/critical Axe violations on the
selected screens. Fourteen screenshots are retained under `screenshots/`;
desktop/mobile `cabinet-payment.png` samples were visually inspected. This is
not real Widget/payment or browser-to-API-to-LBX acceptance. The unrelated full
browser suite was not run. Evidence: `browser.log`, `browser-results.json` and
`browser-metadata.json`. The owned web process was stopped after the run.

Local review: **PASS** over the QA-only changes relative to `07556e4`, using
`review-full`. The new tests leave real Application, Integration and persistence
decisions intact, mock only source/browser edges, compare untouched product
facts/work/history and assert the absence of Step 9 writes. The legacy timeout
change preserves the busy/refusal path and every publication-result assertion.
No confirmed application defect was found in these exercised scenarios. This
is not an independent semantic review of every pre-existing branch change.
API lint/format, architecture and documentation checks are recorded separately;
the source manifest confirms no production application diff.

Test-server cleanup: **PASS**. The owned `payments-b7e9ed31-postgres-1` server
was stopped through the canonical worktree command after all database checks
finished. The first attempt was not executed because automatic approval review
could not complete (`model is at capacity`); the same authorized command was
successfully retried through approval, with exit 0. The neighboring worktree's
stack was not stopped. API/web smoke processes had already been stopped.

The first canonical attempt stopped at two harness tests because the QA command
supplied `KERNEL_MOCK_ENABLED=false`, while repository orchestration accepts only
`0`/`1`. The corrected run supplies `0`; the original log/XML are retained as
`check-environment-failure.log` and `api-environment-failure.xml`. An initial
runtime smoke used `/api/metrics`; the source-owned `/metrics` route was then
verified in the successful run. Neither correction changed application code.

The user reported an interruption while the corrected canonical run and browser
run were active. Both processes had stopped; completed fast/build/runtime/focused
results were retained. The unfinished PostgreSQL partition and complete selected
browser file were restarted. Interrupted browser artifacts are retained with an
`interrupted` name. No PASS is claimed for either interrupted invocation.

To reproduce locally, start the worktree test server with
`.venv/bin/python scripts/repo.py test-db up`, use the plan's harness recipe for
focused selections, and run the canonical commands with the ordinary repository
environment. When clearing the development mock in a child process, set
`KERNEL_BASE_URL=` and `KERNEL_SERVICE_TOKEN=` together and use
`KERNEL_MOCK_ENABLED=0`. PostgreSQL test invocations must run sequentially; shared
fixtures own the physical database lifecycle. Stop only the server started by
this QA run with `.venv/bin/python scripts/repo.py test-db stop`.

## Rebase verification — 2026-11-01

Application code baseline: `4c81e2cc8fa6d10812904b8bd7c774c20861c2f4`, based on ANY-709
`6288733a59897590a6813b532b281e358763c730`, plus the existing local QA tests and
documentation closeout. The prior `07556e4` evidence above remains historical.

The rebase preserves the narrow original-customer-key recovery from ANY-709
through shared customer proof/admission. Updated source expectations distinguish
queued work kinds and the two guarded inventory reads before a subscription
send. No extra CREATE permission, paid-access producer or trust extension was
introduced. Review of the combined result found the compatibility fixes necessary
to preserve the accepted behavior, not new product scope.

Canonical verification used the repository check harness with child-process
`KERNEL_MOCK_ENABLED=0`, `KERNEL_BASE_URL=` and `KERNEL_SERVICE_TOKEN=`; the
private worktree configuration was unchanged. Completed stages passed:

- **1,677 fast API tests**, **384 component tests** and **38 web boundary tests**,
  including TypeScript checks.
- Python lint/format, web lint, production build, architecture, documentation
  and generated-contract freshness.

The full `npm run check` invocation then returned **564 PostgreSQL PASS / 4 FAIL**
out of 568; its final status remains **FAIL**. Evidence:
`.harness/any715-rebase-check-final.log`. Two failures selected recovery work
without its work-kind filter after deadline jobs were introduced; two assumed
one inventory pass where current guarded preparation performs two. Corrections
were confined to those test fixtures/phase expectations and retained strict
conflict, send-count, key-restoration and review assertions.

After those test-only corrections, the complete two affected modules passed
**39/39** using `npm run test:api:postgres` with the selection
`billing_customer_conflicts_postgres or billing_customer_key_recovery_postgres`.
Evidence: `.harness/any715-rebase-customer-retest-final.log`. This combines with
the unaffected 564 passes to give final passing coverage for **all 568 distinct
PostgreSQL cases**. The complete canonical invocation was not repeated and is
not recorded as an all-green monolithic PASS. An earlier corrective command
failed collection before execution; it contributes no passing evidence.

All provider evidence in these runs is **SIMULATED**. Browser E2E was not
repeated after rebase; the 14 earlier substituted browser cases retain their
original baseline. Configured real LBX/webhook and application/production
migration checkpoints remain unchanged. Only the owned disposable test database
was used; the worktree test PostgreSQL server was stopped after verification.

## Documentation cleanup verification — 2026-11-01

The documentation-only follow-up restores the approved `661f019` plan verbatim
inside an explicitly historical snapshot, records dated approved amendments
separately and condenses repeated intermediate delivery logs. Current-state
README/architecture/product/reliability guidance now acknowledges the implemented
worker; the runbook remains the source for current operational commands.

Verification: repository documentation check **PASS**; all five focused
runbook/parser/settings/route contract tests **PASS**; six repository
documentation-invariant tests **PASS**. Both test selections used
`repo.api_test_environment` / `repo.api_pytest_command` for `api-fast` with the
canonical check environment. A byte comparison against
`git show 661f019:docs/exec-plans/active/ANY-715-implementation-plan.md` verifies
the archived original is unchanged. Hash comparison confirms no existing
application, test, generated or deployment/configuration file changed in this
follow-up. No new PostgreSQL, browser or full canonical run was needed for these
documentation edits; the dated application verification above is reused.

## Remaining integration checkpoints

- **CONFIGURED_TEST_LBX_READ_VERIFIED: NOT_RUN / LBX_NOT_CONFIGURED.** Configure
  the authorized test connection and read an existing owned subscription using
  the runbook's bounded reconciliation path. No new payment is needed.
- **REAL WEBHOOK ENABLEMENT: NOT_RUN.** Required mode remains
  **DISABLED/POLLING-ONLY**. Verify real credential-header delivery, correlation,
  event-to-GET visibility and restart/polling convergence before enablement.
- **Application/production migration: NOT_RUN.** Only disposable test migration
  is authorized by this QA execution.
- **Natural provider renewal, paid-access derivation and Kernel enforcement:
  DEFERRED** to the owning ANY-504 steps. Simulated lifecycle/calendar changes do
  not establish these outcomes.

Local automated completion and real integration acceptance must be reported
separately. This report does not authorize production enablement or human merge.
