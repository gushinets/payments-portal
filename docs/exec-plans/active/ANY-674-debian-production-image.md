# ANY-674 — Debian production API image remediation

## Objective and scope
Apply available supported Debian security updates to the final Python 3.12 API production image and provide reproducible before/after evidence for https://linear.app/paveldik/issue/ANY-674.
Keep uv, application dependencies, Debian release, non-root runtime, TLS, timezone, migrations and deployment contracts intact. Pip remediation belongs to ANY-742; no ignores, enforcement changes, deployment or risk approval.

## Baseline and coverage
Fetched origin/main successfully: aa9d8f996cba91feaaaad6a9937eef0c590ae4fa. Isolated branch codex/any-674-debian-image.
Existing Dockerfile already refreshes indexes and upgrades packages. Existing deployment-contract and Python dependency-contract tests cover production target, main-only dependencies, non-root liveness verifier and migration/startup separation. The production smoke and PostgreSQL migration tests supply runtime characterization; package evidence must come from the final image.

## Execution
- [x] Read ticket and repository operational guidance; inspect shared state and fetch main.
- [ ] Build unchanged production target with --pull --no-cache, linux/amd64; retain immutable ID, package inventory, runtime/migration baseline and sanitized Trivy report.
- [ ] Verify PR116 integration and supported Python 3.12 same-release candidate; inspect current Debian candidate versions before choosing the smallest remediation.
- [ ] Build candidate and compare inventories and scans using one pinned scanner/database snapshot. Explain every historical advisory and new Debian finding without equating disappearance with a fix.
- [ ] Verify normal non-root startup/readiness with disposable PostgreSQL, offline imports, runtime libraries and Alembic entrypoints; run focused image/deployment/migration contracts.
- [ ] Run npm run check:fast and broadest supported npm run check, attributing limitations to revisions.
- [ ] Review diff and current origin/main overlap; publish focused PR with immutable evidence and human residual-risk decisions.

## Evidence and decisions
Evidence is retained under .harness/any-674 during execution. Checked-in remediation report will include commands, identities, hashes, package/advisory comparison and dated residual review requests. Missing owner assignments remain explicit human decisions.

## Progress and discoveries
Initial implementation pending fresh baseline build. ANY-742 is Planned at inspection; no active worktree for it. No pip-specific changes are included.
