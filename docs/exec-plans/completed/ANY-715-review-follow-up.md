# ANY-715 review follow-up — 2026-11-09

Issue: https://linear.app/paveldik/issue/ANY-715

## Objective and owner decisions

Pause automatic uncertain-create discovery after the fixed two-hour window,
retain all duplicate-prevention holds, and raise an actionable Sentry event.
Explicit user/operator GET-only recovery of the original remains available.
Treat LBX `block_to_close_days` as informational lifecycle metadata, excluding
it from current-offer admission and material-term comparison. Preserve stored
purchase history and all real owner, effective-price and lifecycle checks.

## Execution

- [x] Persist pause across restart/repair and fence in-flight automatic applies.
- [x] Deliver a privacy-safe, failure-class-grouped Sentry event outside SQL transactions;
  retain notification retry work until the SDK accepts it.
- [x] Remove the lifecycle setting from live admission/fingerprints while old
  accepted records remain readable and retain their original stored digests.
- [x] Document precise authority, operator commands and Sentry alert routing.
- [x] Run focused unit/PostgreSQL, privacy, documentation and architecture checks.

## Boundaries

No financial replay, arbitrary binding, uncertain-hold release, paid grants,
Kernel changes, pushes, live payments or real Sentry test events.
Existing local Widget independence tests and decisions are carried forward.

## Evidence

Implemented locally on `refactor/any715-mvp`, based on `ecf8007`, carrying the
existing uncommitted Widget-independence tests/decisions. No migration is needed:
the existing work row stores the durable `paused` state, and the deadline row
retains notification retries. Notification acceptance never resumes LBX I/O.
Explicit customer recovery of a paused operation is GET-only as well.

Sentry receives only authored guidance and canonical local operation/review
references. The privileged read-only `inspect-operation` command resolves owner
and purchase references locally; they are not transmitted to Sentry. The
failure-class fingerprint contains no entity/correlation IDs.

Verification used `/tmp/any715-implement-nov9` with the same API environment and
its own `payments-e22cdf6d` PostgreSQL container; no shared/application DB was used.

- `pytest -p no:cacheprovider -q` for `test_sentry_reporting.py`,
  `test_billing_recovery_alerts.py`, `test_any709_step1_sources.py` and
  `test_billing_recovery_cli.py`: **120 passed**. A combined restricted-shell
  invocation stalled in CLI dispatch and was terminated; the final same focused
  selection completed in 3.08s under host execution with a diagnostic timeout.
- Initial recovery regression: **28 PostgreSQL passed**. The broader affected
  recovery-fault, proof-clock, Widget-review and trust-expiry selection passed
  **113 PostgreSQL tests**. Those results were reused after the final Sentry
  privacy/lookup adjustments; no unrelated full-suite repeat was performed.
- Final selection: `test_billing_recovery_pause_postgres.py`, independent
  deadline/no-send cases, customer send-lease/paired-proof cases and overdue
  customer local-deadline cases: **22 PostgreSQL passed**. This verifies current
  alert contracts/local lookup, no POST after pause, restart/repair, notification
  retry, late in-flight rejection, explicit recovery and unchanged historical
  `current-terms:v2` accepted snapshots continuing under the v3 comparison.
- Ruff on changed Python files, `python scripts/repo.py docs check`,
  `python scripts/repo.py architecture check`, and `git diff --check`: **PASS**.

Final review also treats a late automatic result revoked by a durable pause as
an acknowledged stop, avoiding a second unrelated worker-error event in Sentry.
Other stale owners/lost acknowledgements remain errors and cannot apply facts.
The three targeted PostgreSQL cases for this pause race, an expired owner's
late response and a lost acknowledgement passed after the adjustment.

The subsequent documentation-only review aligned C3 in SECURITY, the current
data model and the ANY-709 runbook with GET-only recovery after a durable pause.
It also made notification of every new paused case mandatory even inside an
existing Sentry issue, prohibited closing that grouped issue for one recovered
case while others remain unresolved, and updated the index's decision precedence.

## Strong-review race follow-up

`REV-1` reproduced a source read starting just before the fixed deadline and
finishing just after it with a still-valid queue lease. Without the independent
deadline lane running first, both customer and subscription binding succeeded;
the subsequent deadline job skipped notification for the now-bound operation.
`REV-2` reproduced the deadline lane revoking a claim before `subject()` ran,
which escaped as a worker error despite the intentional durable pause.

The shared deadline/pause decision now runs under the existing business locks
and verified automatic claim in customer and financial first-binding writers.
Its pause is committed before returning a refused automatic result. The local
deadline job still owns escalation/notification outside SQL transactions, while
explicit user/operator recovery keeps its existing proof requirements and can
bind the original after the window. The subject handoff acknowledges only a
verified durable pause; other stale owners and lost acknowledgements still fail.

Regression coverage uses event barriers and one coherent database clock. It
checks customer/agreement/subscription reads before the deadline, late reads
with either ordering of the independent deadline job, explicit GET-only recovery,
retained history/holds and notification, plus pause between claim and subject.

Verification used `/tmp/any715-fix-recovery-races-nov9` and its separate
`payments-4e8fa1df` PostgreSQL container, with no shared/application DB:

- `test_billing_recovery_races_postgres.py` and
  `test_billing_recovery_pause_postgres.py`: **21 passed**. The new 11 cases
  reproduce both review races and verify working before-deadline controls.
- Targeted background recovery fault/lease/repair/discovery cases,
  `test_late_proven_unsent_resume_has_one_new_bounded_recovery_window` and
  `test_billing_customer_key_recovery_postgres.py`: **32 passed**. Real lost
  acknowledgements, stale owners, C4 continuation and customer conflict controls
  remain protected.
- `test_billing_background_recovery.py`, `test_billing_recovery_ownership.py`,
  `test_billing_worker_retry.py` and `test_billing_worker.py`: **28 passed**.
  The first run exposed an outdated retry-test delegate that did not recognize
  the existing durable-pause probe; only that test double was updated before
  the successful focused rerun.
- Ruff on the changed Python files, formatting of the new regression module,
  documentation and architecture checks: **PASS**. Earlier Sentry-envelope,
  Widget and commercial-history results are reused for unchanged code; no
  unrelated full-suite rerun was performed.

No live Sentry event, project notification-rule mutation, payment, browser E2E,
full monolithic check or Kernel rollout is claimed. Operator-owned Sentry routing
and the exact inspect/recover steps are in the billing runbook. Source/SDK privacy
was verified through the actual Sentry envelope using an isolated recording
transport. The subsequent owner instruction authorizes one local commit of
these prepared changes, including the documentation clarifications. No push
is part of this follow-up.
