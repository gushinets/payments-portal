# ANY-674 — Debian production API image remediation

## Objective and scope
Apply available supported Debian security updates to the final Python 3.12 API production image and provide reproducible before/after evidence for https://linear.app/paveldik/issue/ANY-674.
Keep uv, application dependencies, Debian release, non-root runtime, TLS, timezone, migrations and deployment contracts intact. Pip remediation belongs to ANY-742; no ignores, enforcement changes, deployment or risk approval.

## Baseline and coverage
Fetched origin/main successfully: aa9d8f996cba91feaaaad6a9937eef0c590ae4fa. Isolated branch codex/any-674-debian-image.
Existing Dockerfile already refreshes indexes and upgrades packages. Existing deployment-contract and Python dependency-contract tests cover production target, main-only dependencies, non-root liveness verifier and migration/startup separation. The production smoke and PostgreSQL migration tests supply runtime characterization; package evidence must come from the final image.

## Execution
- [x] Read ticket and repository operational guidance; inspect shared state and fetch main.
- [x] Build unchanged production target with --pull --no-cache, linux/amd64; retain immutable ID, package inventory, runtime/migration baseline and sanitized Trivy report.
- [x] Verify PR116 integration and supported Python 3.12 same-release candidate; inspect current Debian candidate versions before choosing the smallest remediation.
- [x] Build candidate and compare inventories and scans using one pinned scanner/database snapshot. Explain every historical advisory and new Debian finding without equating disappearance with a fix.
- [x] Verify normal non-root startup/readiness with disposable PostgreSQL, offline imports, runtime libraries and Alembic entrypoints; run focused image/deployment/migration contracts.
- [x] Run npm run check:fast and broadest supported npm run check, attributing limitations to revisions.
- [x] Review diff and current origin/main overlap; publish focused PR with immutable evidence.
- [ ] Development team: assign residual remediation/review owners and record applicable scoped decisions; ownership is pending team assignment. This ticket acceptance criterion remains pending separately from completed technical handoff; no risk acceptance is inferred.

## Evidence and decisions
Evidence is retained under .harness/any-674 during execution. Checked-in remediation report will include commands, identities, hashes, package/advisory comparison and dated residual review requests. Missing owner assignments remain explicit human decisions.

## Progress and discoveries
Runtime source 15363f4d is built and characterized. Fresh baseline and candidate contain identical Debian versions and 218 records / 96 IDs; supported repositories offer zero pending upgrades. Python base advances 3.12.14 to 3.12.16 on unchanged Trixie. All 71 historical IDs and 27 newly reported IDs have a disposition; two historical zlib IDs are already fixed before the fresh baseline. Runtime/readiness/Alembic and 25 focused migration tests pass; 99 image/deployment/dependency contracts pass. Canonical checks were run and failed outside the Dockerfile change; full local PostgreSQL characterization completed with 953 passed, 226 failed, 25 errors and 6 skipped (host limitations and proof/timing failures, not repaired here). Draft PR179 is open. Human residual owner assignment and risk decisions remain outstanding, proposed review date 2026-12-02. See docs/engineering/ANY-674-debian-image-evidence.md. ANY-742 is Planned at inspection; no active worktree for it. No pip-specific changes are included.

## Handoff
Draft PR179; image remediation/evidence prepared. Human residual-owner assignment, acceptance and handling of failed broad local checks remain pending. Earlier independent evidence review corrections completed. Subsequent human review identified the unresolved residual-decision acceptance blocker and the version-column defect addressed below.

## Review follow-up
At reviewed head `7d805e02`, reproduced the 73/87 incomplete Debian version rows and regenerated all 348 version fields from retained dpkg inventories; evidence hashes refreshed. P1 remains an acceptance blocker pending a real human decision; the explicit 96-ID scope and required fields are in docs/engineering/ANY-674-residual-risk-decision.md. No runtime, lock or policy change or new image claim.

## High-first remediation follow-up

Status: technical investigation and feasible minimization completed; historical comparisons above remain unchanged. Residual acceptance is not the next step.

Starting source: `6dc518432a2bad5c8a48e6c646b7113e196f26b0`; freshly fetched origin/main `fb4d66bb0f9f24dbd18257366926697afaa46fe3`. Continue the existing PR179 branch. ANY-829 confirmed its builds/scans are finished; preserve its retained images/cache.

### Coverage and candidate design
Existing runtime verifier covers app user, util-linux version and liveness; production CI covers default startup, PostgreSQL readiness and Alembic. Existing dependency/deployment contracts preserve uv and no-dev dependencies. Missing guarantee: final runtime must not retain the selected build/account/mount tools after supported package removal. Extend actual-image verification and show the old image fails that new guard before implementing production removal. Keep dpkg metadata, essential/protected packages and native runtime dependencies.

- [x] Group all 47 High records into 11 advisory IDs; inspect full versions, essential/protected flags, reverse dependencies and native links.
- [x] Refresh official vendor status and supported backport options for every High; probe vulnerable components and prerequisites rather than infer from imports alone.
- [x] Build unchanged current production source with fresh layers; retain separate immutable baseline and inventories/scans using the original DB copy.
- [x] Test a concrete non-forced, dependency-checked removal candidate. Reject essential/protected removal or broken native dependencies. Account creation precedes removal; development/build stages retain their tools.
- [x] Verify selected removals at package and owned-file level, complete native ELF links, retained TLS/compression/timezone/SQLite/curses behavior, default non-root startup/readiness and migration contracts.
- [x] Record remaining severities, meaningful alternatives and precise per-High next steps; preserve source-wide scanner findings where functionality remains or assessment is narrower than the advisory.
- [x] Run focused and canonical checks; inspect complete diff/current main; independently review and update existing PR179 without merge/deploy/status change.

New evidence will be a separately labeled follow-up, not a rewrite of the original zero-Debian-fix comparison. Pip remains ANY-742 scope. Broad distro/layout migrations or maintained source patches require a scoped decision before adoption.

## Completed minimization follow-up

Technical investigation and implementation complete at runtime source `f7728c18`; see [runtime minimization evidence](../../engineering/ANY-674-runtime-minimization.md). All follow-up investigation/build/removal/runtime/analysis/check/review steps above were executed. Sixteen verified nonessential packages removed; 218/96 becomes 207/95 records/IDs, with one Low advisory eliminated and no High ID falsely claimed fixed. Eleven High IDs individually analyzed; Bookworm and Alpine alternatives tested and rejected with concrete evidence. Historical results remain intact. `check:fast` and source CI pass; local full check has one unchanged cancellation timeout, with later stages unreached and isolated rerun passing. Supported Trixie/backports has no fixed candidates for retained High families. Unknown accountable owners remain explicit; the earlier blanket acceptance request is superseded by technical analysis and specific next actions. No acceptance, merge, deployment or issue-state change.

## Technical handoff separation

Technical work is complete and handed off with supported-update/removal analysis, before/after scans, startup/readiness and migrations. The [handoff](../../engineering/ANY-674-technical-handoff.md) enumerates all 95 current residual IDs for development-team assignment, with per-ID applicability/options in the evidence ledgers and proposed 2026-12-02 review. Ownership is **pending team assignment**, does not block technical completion and is not assigned to the requester. The ticket ownership criterion stays unchecked. No risk approval, exception, merge, deployment or Done transition.

## Review correction — fail-closed verification

Starting PR head `c0fc008f` already incorporates current main `dac00ead`; fast-forwarded the existing local branch without rewriting or dropping that merge. Reviewed two introduced verification defects: native traversal/ldd failures were masked by a grep pipeline, and Dockerfile audit exit status was discarded by command substitution inside test.

- [x] Add regressions against actual production RUN and inner verifier shell; reproduce four failures / three passes before fixes.
- [x] Require successful standalone audit assignment before checking empty output; inspect traversal and each ldd result separately from missing-library text. Preserve the optional pre-existing Tk exclusion.
- [x] Complete deployment-contract tests:60 passed; shell syntax, ruff lint and formatting pass.
- [x] Record actual-image CI and canonical status for runtime correction `df09c29c` in the [review correction report](../../engineering/ANY-674-review-corrections.md): CI/Security/all analysis checks pass; local fast passed, full in progress at evidence publication with final outcome reported in PR handoff. Docker became available and the worktree test server was started.

Residual ownership remains **pending team assignment**; existing applicability/options/review dates and historical before/after comparisons remain unchanged. No risk decision, exception, merge or deployment.

## Vendor-status review follow-up

- [x] Preserve reviewed `d85861c4` main merges; successful fetch confirms main `49ed895d`.
- [x] Independently confirm CVE-2026-126765 on Debian source-package tracker and GNU libc advisory; update dated ledger/vendor evidence and checksums without changing captured UNKNOWN severity or package/remediation counts.
- [x] Keep all101 current owners pending team assignment, with ownership acceptance criterion separately pending; no inferred owner or acceptance.

Runtime/build/test source is unchanged. Reuse passing reviewed-head CI44736916316 and Security44736916516, and prior runtime verification. Validate documentation, ledger scope, unchanged non-target rows, severity/ownership invariants and all evidence checksums for this documentation-only correction. No image rebuild or repeated complete partitions needed.

## Complete component-level investigation of all101 advisories

Status: reopened technical investigation. Earlier completion statements covered updates/minimization and initial dispositions, not complete component-level applicability. Current user scope requires all101IDs assessed individually before technical completion is claimed again; no residual-risk discussion or approval is part of this work.

Baseline: existing PR179 head8cda1229; fetched origin/main49ed895d. Preserve historical218/96→207/95 comparison and refreshed221/101 snapshot. Existing coverage includes60deployment contracts,17shell guard cases, actual-image offline/runtime verifier, CI readiness/Alembic/PostgreSQL. Gaps: vendor-to-binary/function mapping, final-image proof for all component-absence claims, and per-advisory prerequisites.

- [x] Research authoritative current Debian/upstream status and affected component for every101ID; separate required sibling library from vulnerable utility/feature.
- [x] Attempt supported Docker Desktop recovery without clearing shared data; record local engine limitation. Use isolated CI to capture actual unchanged/final image, package/feature/file/symbol evidence and signed supported candidates.
- [x] Apply any justified supported update/removal to disposable candidates; prove actual remaining files/dependencies and startup/TLS/timezone/import/migration behavior.
- [x] Produce a101-row evidence-backed applicability ledger with explicit confidence, exposure prerequisites, remediation attempts and concrete unresolved technical questions; keep raw scanner counts/severity and pendingteamownership.
- [x] Build/scan actual final target with comparable scanner/database, run focused and canonical verification, independently review and prepare the existing PR update. Local full PostgreSQL stage blocked; exact-image PostgreSQL cycle/readiness passed in hosted verification. Final-head CI must be checked at handoff.

Parallel read-only research splits glibc/GCC35, native-library families30 and utilities/system services36. Root owns image/build changes and integration; no shared production-file edits by researchers. Docker initially stopped with a socket-forwarder handshake error; supported Desktop restart attempted, no reset/prune/removal of shared resources.

### All101 follow-up outcome

See the [complete applicability report](../../engineering/ANY-674-complete-applicability.md) and [101-row ledger](../../engineering/evidence/ANY-674-applicability-2026-11-21/advisory-analysis.csv). Scope is97 CVE IDs plus4 TEMP IDs. All are mapped to installed packages, actual affected components, triggers, current vendor status, supported options and limits. Current classes:14 component absent,1 other architecture,4 trigger disabled,20 scoped known-consumer trigger unused,62 component present/conditional. These are not scanner suppressions or package fixes.

- Implemented dpkg-statoverride removal of three unnecessary setid modes; final privileged files3→0, capability files0. Added a fail-closed runtime guard and demonstrated two pre-fix failing regression cases.
- Fresh signed Trixie/security/updates/backports probe:0 upgrades and no installed-package backports candidates. All26 removal simulations preserved;24 dependency/Essential/Protected blocked,2 require native libraries despite no dpkg reverse-dependency block. No further package purge justified.
- Controlled same-DB Trivy0.72 comparison on a46ce633:71 identical package versions,221 records/101IDs on each side, unchanged severities. Historical16 removals/one Low advisory elimination remain separately preserved. No new Debian patch or advisory elimination claimed.
- Passing a46ce633 CI/Security, focused69 cases before control-helper addition, and local canonical fast (2559 passed/51 skipped API,454 web). Full local check reached missing worktree PostgreSQL after web build; it is not a full pass. Later focused70-case result and exact scanned-image PostgreSQL follow-up are recorded in the final report.
- Sonar CLI-path findings fixed by fixed paths in dc21de42. First exact-image PostgreSQL probe completed upgrade/downgrade/upgrade but failed host-port discovery on an internal network;87ed64f3 checks health inside the container and moves report output only after success. Await actual CI before marking verification complete.

No risk acceptance requested or recorded. Ownership criterion remains pending team assignment, review proposed2026-12-02. Do not merge, deploy or close the ticket.

Final runtime evidence: Security44838297198 at1b33a906 passed the same scanned image UID999/default-CMD startup, PostgreSQL18.4 upgrade/downgrade/upgrade, liveness/readiness and offline/native guards. Controlled final71 packages/221records/101IDs; setid3→0; no package/advisory patch claim. Focused71 tests and documentation checks passed. Latest Sonar open-issue query0. The final test/documentation-only commit requires its own CI handoff status; no application/Dockerfile/dependency change after tested runtime source.

### Wheel-only build follow-up

Sonar reported two source-build hook warnings in the archived control recipe. The actual canonical Dockerfile now uses supported uv `--no-build` for production and development dependency synchronization (7ed98b8a); package locks/versions are unchanged. No artifact rename, scanner ignore, risk approval or enforcement change was adopted. The fresh Security44839563431 image pair passed with the same71 Debian versions and all application distribution versions as1b33a906. Actual final image startup/readiness and PostgreSQL migration round trip passed. The checked-in current control recipe is the actual newly tested recipe; historical1b33 results, raw hashes and immutable Git/CI links are preserved in historical-pair-1b33.json. Both production and development dependency stages build on linux/amd64; future missing compatible wheels deliberately fail rather than execute source build hooks. CI44839563588 covers canonical fast/coverage, production/PostgreSQL and the development/browser path; final status is recorded at handoff.
