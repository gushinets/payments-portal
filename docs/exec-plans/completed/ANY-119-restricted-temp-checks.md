# ANY-119 — Restricted System Temp Directories

Status: completed
Owner: repository maintainers
Started: 2026-07-14
Completed: 2026-07-14
Linear: https://linear.app/paveldik/issue/ANY-119/make-canonical-checks-resilient-to-restricted-system-temp-directories

## Objective

Make canonical checks use writable, worktree-isolated temporary storage when
the operating system's default temporary directory is unavailable.

## Baseline and reproduction

- Initial prompt: implement Linear ANY-119 from current `origin/main` in an
  isolated worktree, reproduce the failure, validate broadly, and open a draft
  PR without merging it.
- Baseline commit: `3e184b0c8646e22fdbb1616818a89f9c592481f0`.
- Initial isolated worktree: `C:\tmp\payments-portal-any-119`, branch
  `codex/any-119-temp-checks`, harness ID `e8a36aba`.
- `npm run check:fast` on unchanged code reproduced `PermissionError: [WinError
  5]` while pytest scanned the default `pytest-of-gushinets` directory: 28
  passed, 2 skipped, and 4 setup errors.
- The worktree was relocated to the ignored, writable
  `.harness/worktrees/any-119` directory after the managed sandbox allowed
  source edits in `C:\tmp` but denied subprocess-created harness files. The
  final harness ID is `7e082adb`.

## Decisions and assumptions

- Set `TEMP`, `TMP`, and `TMPDIR` for every canonical-check subprocess so the
  behavior is explicit on Windows and Linux.
- Store temporary state in `.harness/tmp`; `.harness` is ignored and each Git
  worktree has a distinct repository root, preventing cross-worktree collision.
- Preserve the caller environment by copying it before applying the three
  scoped overrides.
- Keep direct subsystem commands unchanged because ANY-119 scopes canonical
  repository checks.
- No product, payment, legal, generated, database, or production-runtime
  behavior changes.

## Implementation

- Added `canonical_check_environment()` to create the worktree temp directory
  and return the scoped child-process environment.
- Passed that environment to web boundaries, web lint, API pytest, web build,
  PostgreSQL pytest, and Playwright runs launched by `cmd_check`.
- Added tests for caller-environment preservation, all three platform temp
  variables, distinct worktree roots, directory creation, and propagation to
  every fast-check subprocess.

## Commands and results

- `git fetch origin main --prune`: passed; `origin/main` remained at the
  baseline commit.
- `python scripts/repo.py doctor`: passed in the final worktree; harness ID
  `7e082adb` and all preferred ports were available.
- Baseline `npm run check:fast`: reproduced the reported Windows temp failure.
- Final `npm run check:fast`: passed without caller temp overrides; web boundary
  tests 4 passed, lint passed, API tests 34 passed and 2 PostgreSQL-dependent
  tests skipped.
- `npm run check`: passed without opt-in integration variables; the same fast
  checks and production web build passed, while PostgreSQL and browser suites
  were explicitly skipped by the harness.
- `python scripts/repo.py harness-smoke`: passed and derived distinct current
  (`7e082adb`) and second-worktree (`99b1df56`) runtime identities, databases,
  and port sets.
- `python scripts/repo.py pr-title "ANY-119 - Make canonical checks resilient
  to restricted system temp directories"`: passed.
- `npm run repo:up`: passed after Docker permission approval; the isolated API,
  web, PostgreSQL, and observability services became healthy.
- Fully opted-in `npm run check`: fast checks passed, then the existing
  concurrent webhook PostgreSQL test failed because the second 200 response
  completed in about 21 seconds after its 10-second future timeout. A focused
  rerun reproduced the same timing. A separate disposable test database did not
  change that result.
- `test_alembic_postgres.py`: attempted against both the application database
  and a separate worktree-scoped test database; the process hung without an
  active PostgreSQL test connection and was stopped after inspection.
- `npm run test:e2e`: 22 desktop/mobile Chromium journeys passed.
- Loki query for API `error|exception`: no entries across 281 processed log
  lines after the browser run.
- Prometheus request-rate query: query succeeded but returned an empty vector.
- `git diff --check`: passed. Diff review found only harness code, harness tests,
  and this execution record; no generated, legal, secret, or production files.
- Main-checkout recovery: recreated its ignored Python venv, installed the
  repository requirements with Pydantic 2.11.7, and confirmed
  `npm run generate:check` plus a clean `git status`.

## Skipped checks and limitations

- The canonical PostgreSQL completion path did not pass locally because of the
  pre-existing concurrent webhook timeout and the independent Alembic process
  hang described above. Neither failure touches the changed temp harness code.
- Linux was not available locally. Linux compatibility is covered structurally
  by setting `TMPDIR` and by path-based unit coverage, while Windows exercised
  the original failure end to end.
- Trace lookup was not performed because the completed browser suite did not
  expose a trace ID through the command output. The Loki error scan was clean;
  the Prometheus query returned no sample.

## Human input and interventions

- No product, scope, or implementation choice required human clarification.
- Managed-environment approval was required for: fetching remote Git metadata;
  registering, relocating, and removing agent-created worktrees; creating local
  dependency junctions; downloading pinned Python dependencies; accessing
  Docker Desktop; inspecting and stopping only the hung test process trees; and
  restoring the main checkout's ignored Python venv.
- GitHub CLI authentication was stale at baseline. Git push and draft PR
  creation therefore use the repository Git credential path and connected
  GitHub app respectively.
- Coordinator intervention #1 was recorded with timestamp
  `2026-07-14T10:34:12Z`:

  ```text
  Coordinator intervention #1 (2026-07-14T10:34:12Z): this task has shown no observable transcript, process, or worktree progress for about 30 minutes after the dependency/environment investigation. Please report the current blocking condition, if any, then continue independently toward the requested draft PR. This is a status/resume request only; it provides no implementation guidance and does not change the issue scope. Record this intervention verbatim in the trial evidence, including whether it was necessary and what repository or runtime improvement could prevent the stall.
  ```

  The intervention was not necessary for an implementation decision and did
  not change scope. Work was progressing through long dependency installation,
  Docker build, and integration-test commands, including two processes that
  later required explicit hang diagnosis and termination. At the time this
  evidence follow-up was received, there was no remaining blocker: draft PR #9
  was already open. The intervention was useful for exposing a visibility gap
  and ensuring that the gap itself was recorded.
- Coordinator interventions #2-#4 were manual user messages containing only
  `continue`. None provided implementation guidance or changed issue scope:

  - Intervention #2 at `2026-07-14T12:16:12Z` resumed a turn interrupted while
    `npm run check:fast` was active. The original process handle was no longer
    available after resumption, so the check was rerun. There was no code
    blocker; the effect was limited to repeating validation and continuing from
    the existing worktree. A durable exec-session handle and automatic
    post-interruption status checkpoint would remove the need for this manual
    resumption.
  - Intervention #3 at `2026-07-14T14:13:02Z` resumed a turn interrupted after
    final diff inspection and commit preparation, before branch publication.
    There was no implementation or runtime blocker. The effect was to continue
    with push and draft PR creation using the already-reviewed commit. Persisting
    the current delivery phase and automatically resuming the next safe action
    would remove the need for this message.
  - Intervention #4 at `2026-07-14T14:38:03Z` resumed a turn interrupted after
    draft PR creation and before worktree-stack teardown and final verification.
    There was no change-specific blocker. The effect was to finish cleanup,
    remove the abandoned temporary worktree remnants, and verify synchronized
    branch and main-checkout state. A durable completion checklist with
    automatic continuation after turn interruption would remove the need for
    manual resumption.

  Each message was exactly:

  ```text
  continue
  ```
- Coordinator intervention #5 at `2026-07-14T14:45:28Z` reported independent
  review results and requested evidence corrections only. It provided no
  implementation guidance and caused only this trial-evidence update; the code
  and issue scope remained unchanged.

## Missing repository fixtures, commands, documentation, and guardrails

- Python indirect dependencies are not fully pinned. A fresh install selected
  Pydantic 2.13.4 and made committed OpenAPI output stale; Pydantic 2.11.7
  matches the fixture. This should be fixed separately rather than expanding
  ANY-119.
- There is no documented safe dependency-cache reuse command for fresh
  worktrees. A cross-drive `node_modules` junction broke ESLint configuration
  resolution.
- Forced worktree cleanup can traverse a shared dependency junction. It emptied
  the main checkout's ignored venv and required restoration; the harness lacks
  a guardrail against dependency junctions inside removable worktrees.
- The PostgreSQL workflow does not document creating a separate integration-test
  database when the application stack is running against its primary worktree
  database.
- The harness has no timeout or cleanup command for a hung standalone pytest
  process.
- Chromium emitted an untracked root `debug.log`; it is not ignored and had to
  be inspected and removed manually.
- The observability helper requires a known trace ID and offers no recent-trace
  discovery command.
- Long-running setup, Docker, and test commands need a durable heartbeat that is
  visible to coordinators even when the active transcript or process session is
  not observable. The harness should also persist the current command, start
  time, worktree, and last output timestamp and apply bounded command timeouts
  with a documented cleanup path.
- Turn interruption should preserve active process handles and a machine-readable
  delivery checkpoint so safe validation, publication, and cleanup steps can
  resume automatically without a manual `continue` message.

## Implementation/self-review findings and responses

- Finding: a helper-only unit test would not detect failure to pass the scoped
  environment into pytest. Response: added a `cmd_check` orchestration test that
  asserts every fast-check subprocess receives the same scoped environment.
- Finding: worktree isolation must be demonstrated independently of port
  isolation. Response: the unit test creates two repository roots and asserts
  distinct `.harness/tmp` paths; harness smoke separately verifies runtime IDs.
- Finding: browser validation left a suspicious untracked `debug.log`.
  Response: inspected it as Chromium raster diagnostics, removed it, and kept it
  out of the diff.
- Finding: no code path needs to mutate the parent environment. Response: the
  helper copies its input and the test asserts the caller's original `TEMP`
  remains unchanged.
- Final review found no unresolved change-specific defect.

## Coordinator independent review

Coordinator intervention #5 reported no change-specific code defect. The
coordinator independently recorded the following evidence:

- `npm run check:fast` passed with the inaccessible system `TEMP` forced: 34
  passed and 2 skipped.
- Code quality passed.
- Production gate passed.
- PR-title validation passed.
- Windows and Linux harness-smoke jobs passed.
- The browser CI job was still pending at review time.

The review changed only this evidence record. No implementation response was
required, and draft PR #9 remained unmerged.
