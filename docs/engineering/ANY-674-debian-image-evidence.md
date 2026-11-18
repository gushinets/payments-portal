# ANY-674 — Production API Debian update evidence

Issue: https://linear.app/paveldik/issue/ANY-674

## Outcome

The production target builds successfully with all currently available supported Debian updates. Refresh the digest-pinned base to `python:3.12-slim-trixie`, retaining Debian 13.7 and Python 3.12 (3.12.14 → 3.12.16). No application lock, uv version, repository suite, runtime user, startup/migration contract, scanner policy or ignore is changed. No packages are removed.

**There is no additional Debian package or advisory fix attributable to this PR versus a fresh unchanged build.** The existing `apt-get update && apt-get upgrade` already applies every available update. The unchanged build upgrades 29 packages; the refreshed base needs only the zlib update. Both final inventories are identical, and subsequent fresh-index simulations show `0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded`.

The historical zlib findings CVE-2026-27171 and CVE-2026-85091 are already fixed before the fresh baseline by `zlib1g 1:1.3.dfsg+really1.3.1-1+deb13u1`. Debian's current tracker records this exact Trixie fixed version for both. This is an installed-version/source-status disposition, not a severity or metadata disappearance. Both reports retain full OS package metadata, including zlib. The other 69 historical IDs remain; 27 additional Debian IDs are reported since the ticket snapshot.

## Revisions and immutable identities

Fetch succeeded before work and isolated branch creation. Baseline: `aa9d8f996cba91feaaaad6a9937eef0c590ae4fa`. Candidate source: `15363f4ddafb79e50fa73fe0e7517b1b3a745310`; the build used identical Dockerfile/application/lock bytes immediately before that commit. Platform: `linux/amd64` for both. Images and exported archives remain locally retained under task-specific names; no image was deployed or pushed to a registry.

| Identity | Before | After |
|---|---|---|
| Base index digest | `2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a` | `5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b` |
| Base amd64 manifest | `876416ecde9aca2bcc90e1fb0c7a9500bbf749f5788b70f82d4c5a5c2357f8b4` | `05a994d2344eb364cc186910f4fc8786a38215f39f00d0acc25bff33a08f4177` |
| Final immutable image index / local image ID | `sha256:3f431c464e210baa72ee0fc8b986bfecc61fefde71d4a9974a21ac26d204567e` | `sha256:e6a7c4f922e09a27556e8acf44e92eb4b35cb26c005d8ee6e8aa7cf73d4e8b3e` |
| Image config digest | `098ad98732762649076dc96e13d9f98bdb10a5861863f7d2479187590ee22698` | `293bd9cdb27b12c8fca275c2423bd337171bed78621f6a58b9ec4598a396f0d7` |
| Sanitized scan SHA-256 | `feb946960909ba6f341dfe3b7448670bccde43a437557d177235c9ba2e74e732` | `9329eac96ca09a9ea264fe901bd4b5161b4350bad0060b78f6e7c457bd9e19d3` |

Build logs and image/index metadata are in [the evidence directory](evidence/ANY-674/). All digests without a prefix in this table use SHA-256. The candidate official-image manifest identifies docker-library/python revision `3d7e95597e56a415d9e4abc0f15877e005d2cb2e`, built 2026-11-05. [Python official image](https://hub.docker.com/_/python) and [Trixie support lifecycle](https://www.debian.org/releases/trixie/) establish the supported source/release; registry metadata and running images verify the actual selection. There is no distribution migration.

PR [116](https://github.com/gushinets/payments-portal/pull/116) is closed, unmerged. Its latest changes concern uv 0.12.23 and Node 26, not Debian packages. The current API still uses uv 0.12.7. Those unrelated updates are not reused. ANY-742 was Planned with no matching active worktree at inspection. The selected base and evidence are reusable by that task; pip stays 25.0.1 with its six findings, and this PR makes no pip-remediation claim.

## Package and finding comparison

[Package comparison](evidence/ANY-674/package-comparison.csv) records every installed binary/source version, including unaffected packages. [Before inventory](evidence/ANY-674/before-packages.txt) and [after inventory](evidence/ANY-674/after-packages.txt) come from `dpkg-query` in the final production target. The apt-policy logs retain repository suites, installed/candidate versions and zero-pending-upgrade results.

| Final-image Debian result | Before | After |
|---|---:|---:|
| Finding records | 218 | 218 |
| Unique advisory IDs | 96 | 96 |
| High records | 47 | 47 |
| Medium records | 92 | 92 |
| Low records | 65 | 65 |
| Unknown records | 14 | 14 |
| Fixed-version values offered by scanner | 0 | 0 |

Fixed by this change: **0**. Removed through package removal: **0**. Newly introduced by this change: **0**. All 226 OS + Python finding signatures match on ecosystem, package, advisory, installed/fixed version, severity and status; image layer identities are expected to differ. The eight non-Debian records are retained in the full reports and excluded from the Debian counts: six pip records, Mako and OpenTelemetry. Their ownership is outside this change. No metadata-only deletion, severity change or ignore explains the comparison.

## Scanner provenance and reproducibility

Both actual final production images were exported with `docker save` and scanned offline, avoiding Docker-socket access. Scanner: Trivy 0.72.0, immutable container `aquasec/trivy@sha256:cffe3f5161a47a6823fbd23d985795b3ed72a4c806da4c4df16266c02accdd6f`. One database snapshot was downloaded and reused without updates. Schema 2; UpdatedAt `2026-11-18T07:15:21.579242117Z`; DownloadedAt `2026-11-18T11:27:33.461222143Z`; NextUpdate `2026-11-19T07:15:21.579241907Z`; database-file SHA-256 `b4b9f44be196aac7bf3c359abdcacfaa97a7ccaf56297d04745b7dae554eae86`.

Scans: before `2026-11-18T11:30:04.467653838Z`; after `2026-11-18T11:32:22.204298455Z`. Configuration and ignore file are unchanged and copied into evidence. Scanners: `vuln,secret`, all severities, no `ignore-unfixed`, timeout 15m. Both reports were processed with the repository's `redact_trivy_report` function (zero secret records). A first attempt to run the directory-wide redactor on a mixed metadata directory failed on non-report JSON; only the two actual reports were then passed to its existing redaction function. Neither raw secret values nor source-match fields are published.

Build from each stated source revision in its own worktree (PowerShell):

```powershell
docker build --pull --no-cache --platform linux/amd64 --target production --file apps/api/Dockerfile --tag payment-portal-api:any-674-before .
# At candidate source, change the tag to payment-portal-api:any-674-after.
docker save --output .harness/any-674/before-image.tar payment-portal-api:any-674-before
# Repeat for after; retain both archives and immutable IDs.
```

The target/file/context match the repository Security workflow and production Compose API build. `--pull --no-cache` forces fresh package-update layers. Build reproduction at a later date can yield newer package versions; the checked-in inventories, immutable IDs, logs and scan hashes are the observed evidence, not a claim of bit-for-bit future builds.

Scan each archive using the same retained database (set `$side` to `before` or `after`; download DB once before offline scans):

```powershell
$ev = "$PWD/.harness/any-674"
$scanner = 'aquasec/trivy@sha256:cffe3f5161a47a6823fbd23d985795b3ed72a4c806da4c4df16266c02accdd6f'
docker run --rm -v "${ev}:/evidence" $scanner image --cache-dir /evidence/trivy-cache --download-db-only
docker run --rm --network none -v "${ev}:/evidence" -v "${PWD}:/src:ro" $scanner image --input "/evidence/$side-image.tar" --cache-dir /evidence/trivy-cache --skip-db-update --skip-java-db-update --offline-scan --config /src/trivy.yaml --ignorefile /src/.trivyignore.yaml --scanners vuln,secret --format json --output "/evidence/$side-raw.json" --timeout 15m --quiet
```

The DB file is retained locally, not committed (large mutable upstream artifact). Future scans must verify its hash or rescan **both** retained images against the same refreshed DB; later DB results cannot be substituted for one side of this comparison. Full sanitized reports and the selected Debian tracker snapshot are checked in for independent inspection.

## Residual decision for human review

[Per-advisory dispositions](evidence/ANY-674/advisory-dispositions.csv) contain all 71 historical IDs and 27 new IDs, source/binary identity, before/after records, exact advisory condition, current Debian scope/status, other-release fix status, authoritative advisory links, runtime relevance, existing mitigation, owner/approval status and date. [Selected authoritative tracker data](evidence/ANY-674/debian-tracker-selected.json) was fetched 2026-11-18 from [Debian tracker JSON](https://security-tracker.debian.org/tracker/data/json). All 96 residual IDs have Trixie `open` status. Fixes in sid/forky are not claimed as supported Trixie fixes. Debian `no DSA` notes are vendor triage, not Portal risk approval.

Existing mitigations include non-root UID 999, production Compose `no-new-privileges:true`, no public OS shell/login service, PostgreSQL production persistence and no required runtime installation. Libraries used by Python/TLS/compression remain installed; unnecessary-package removal was not proven safe and is not used to lower counts. Local-only advisory scope is not equivalent to unreachability after an application compromise. The CSV explicitly preserves reachability uncertainty and does not certify that every vulnerable function is unused.

**Decision requested:** assign an accountable review owner for each residual row and decide whether continued use is acceptable while supported fixes are unavailable, or commission a separately scoped alternative. Owners are currently **UNASSIGNED — human assignment required**; ticket assignee is not silently treated as risk owner. Proposed review/expiry for every residual is **2026-12-02**, or earlier upon a new supported fix, changed exposure or deployment decision. This date is a review deadline, not an approved exception. No residual acceptance, ignore, severity downgrade or enforcement change is made. The ticket's residual-owner/approval criterion remains pending human action.

## Runtime and verification

Both images pass `security/trivy/verify-api-runtime.sh` using native Git Bash, normal `app` UID 999, patched util-linux floor and canonical liveness. Both also pass normal default-CMD startup and `/api/health/ready` against separate disposable PostgreSQL databases; their unchanged Alembic entrypoint upgrades a fresh database to `20261113_0013` and `current` confirms head. Offline (`--network none`) imports pass for ssl, sqlite3, zlib, bz2, lzma, ctypes, zoneinfo, psycopg, alembic, FastAPI and Uvicorn; TLS trust roots and `Europe/Moscow` resolve. No runtime downloads/installations occur. The first local supplemental import list incorrectly assumed optional `cryptography` was installed; removing that assumption from the evidence script allowed both unchanged locked runtimes to pass. No dependency was added to satisfy the probe.

The supplemental smoke follows the existing CI production-gate sequence: start worktree PostgreSQL with `python scripts/repo.py test-db up`; create disposable per-side databases; invoke `python -m alembic -c apps/api/alembic.ini upgrade head` in each image; start its normal CMD with explicit production contour/DB/origin configuration; query readiness; remove only the smoke containers/databases. Logs are in evidence. It uses synthetic configuration, no real billing services or provider journey. Browser/provider acceptance is not applicable to the base-only change.

Focused image/deployment/dependency contracts: **99 passed** on candidate bytes. Initial direct invocation used the Windows WSL `bash.exe` and failed 21 shell fixtures (78 passed); selecting `D:/Git/bin` in PATH yielded 99/99. No source fix was needed. Existing characterization covers the unchanged contract; no implementation-mirroring regression test was added for a digest substitution.

Canonical and PostgreSQL check outcomes are recorded below after completion. No merge, deployment, issue completion or residual-risk approval is authorized by this evidence.

### Canonical outcomes on runtime source 15363f4d

- `npm run check:fast`: **FAILED**, API 2 failed / 2292 passed / 43 skipped / 1210 deselected. Failures: `test_uvicorn_serves_application_with_production_proxy_flags` (host Uvicorn did not become ready) and `test_queue_time_consumes_same_budget_before_any_source_starts` (queue/admission timing assertion). Earlier docs, generation, architecture, API lint/format, 38 web boundary checks, 454 frontend components and web lint passed. Isolated unchanged-code rerun of both affected files: **14 passed**. This does not erase the canonical failure.
- `npm run check`: **FAILED** at frontend components, 5 failed / 449 passed. Failures were account registration with legal/pt-BR metadata, AuthForm Enter from email/password and consent validation, and verified HeaderAccount modal login. Four failures reported 5-second timeouts and one callback assertion. Docs, generation, architecture, API lint/format and web boundaries passed. Subsequent web lint, API suite, web build, PostgreSQL and optional browser stage were **unreached in this invocation**. No unrelated fix is included and no aggregate green status is claimed.
- Focused PostgreSQL migration files: **25 passed** (including populated-data preservation and migration transitions). The first attempted `repo.py test api-postgres FILE...` invocation was rejected by its CLI before running tests; the successful focused run used `repo.api_test_environment` with pytest's file selection.
- Independent full `npm run test:api:postgres`: final result pending. A separate diagnostic database reproduced `PurchaseRefused("purchase_history_unproven")` in the unchanged financial-proof timestamp fence. Read-only clock measurements bound database time 0.19–0.75 seconds ahead of host time, supporting a clock-related environment concern; they do not establish the cause of every full-suite failure. No VM clock, timing policy, fixture or service was changed.
- `npm run docs:check` with the locked worktree environment in PATH: **PASS**. A standalone initial invocation selected system Python and lacked `pydantic_settings`; using the already prepared worktree environment corrected tool selection without dependency changes.

Build-log excerpts are whitespace-normalized for a clean Git diff; raw logs remain locally retained. Scan JSON is the repository-redacted output, with hashes computed after redaction. Dockerfile Git blob and SHA-256 identities are recorded in [dockerfile identities](evidence/ANY-674/dockerfile-identities.json). [Verification ledger](evidence/ANY-674/verification.json) separates revision-attributed outcomes.

### Independent CI evidence

[Security scan run 44298399457](https://github.com/gushinets/payments-portal/actions/runs/44298399457) **passed** for PR head `5d4de2b885855c595411b4a1d09ebd8f68d2d2dd`, checkout merge ref `93fae05899604a5f006f27935686afe89b71b247`. Its sanitized artifact `14423888679` was downloaded and SHA-256 verified against GitHub metadata: `dbf5bd9c653fa3185af2ef095321f29cf56b812e12d9147c0f236bf421543064`. The CI final API image is `sha256:03eade2dc7f9f1483049cdde4511980e804baa49cf5bd1886ff6d24afff5ac57`; its Debian finding signatures exactly match the local candidate: 218 records / 96 IDs. This is separate corroborating evidence, not a replacement for either retained local comparison image. Artifact expiry is 2026-12-02; its local downloaded copy is retained. See [CI security summary](evidence/ANY-674/ci-security-summary.json). Broader CI remains separately tracked; a successful report-only security workflow is not residual-risk approval.
