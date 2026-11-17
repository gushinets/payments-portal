# ANY-741 Mako dependency maintenance

Status: implementation and evidence complete; human PR review remains.

## Scope and baseline

Base: `2e6d3adc63bd3d633709f6a5168fc14fb7141cdc` (fresh origin/main).
Python 3.12.10, uv 0.12.7; Alembic 1.18.5 requires unconstrained Mako,
currently locked at 1.4.1. No application Mako imports or TemplateLookup callers
were found. Alembic's `util.pyfiles.template_to_file` constructs a filename-based
Mako Template. The migration tree has no project `script.py.mako`.

This is package maintenance with ordinary behavior characterization. Local
vulnerability reproduction and crafted traversal inputs are excluded from scope.
Production uses Linux; package presence does not demonstrate reachable exposure.

## Steps

- [x] Inspect issue, dependencies, upstream release information and existing tests.
- [x] Characterize ordinary native Windows templates and disposable Alembic revision generation.
- [x] Use uv 0.12.7 to upgrade only Mako to 1.4.3 and inspect the lock diff.
- [x] Repeat focused tests; run API lock, fast and canonical checks and applicable PostgreSQL checks.
- [x] Build production API image, verify runtime/version, obtain fresh sanitized filesystem/image scans.
- [x] Review final diff/current main, publish focused PR and record remaining limitations.

## Release selection

[Upstream advisory](https://github.com/advisories/GHSA-5639-2j2p-m4mx)
identifies the Windows drive-letter URI issue and fix in 1.4.2.
[Changelog](https://docs.makotemplates.org/en/latest/changelog.html)
documents 1.4.3's correction to Windows test-suite execution, with native ntpath
coverage upstream. [PyPI 1.4.3](https://pypi.org/project/Mako/1.4.3/)
supports Python >=3.10. Choose this small patched release over the initial 1.4.2
fix; Alembic and MarkupSafe constraints remain compatible. Upstream evidence is
not an independent local verification of vulnerability-specific behavior.

## Evidence

- Before update: lock check passed; four ordinary compatibility cases passed on
  native Windows with Mako 1.4.1. Initial restricted-process temporary-directory
  permission errors were resolved by running checks with an isolated test directory.
- After update: lock check, Ruff check/format and 62 focused dependency/template
  cases passed. Only the Mako package version/artifact entries changed in uv.lock;
  no manifest adjustment or other dependency update was needed.
- Nine existing Alembic/PostgreSQL compatibility checks passed against the
  worktree-isolated disposable PostgreSQL server. An initial attempt used incorrect
  default test credentials; the successful run used harness-generated credentials.
- Local production image `payment-portal-api:any-741-mako` built successfully;
  installed Mako is 1.4.3, ordinary Alembic generation inside Linux passed, and
  unchanged `security/trivy/verify-api-runtime.sh` passed (non-root and liveness).
- Image identity: `sha256:0d63ec140692c95515e0eee889a491082b5b98eac805624b183a1f2394597390`.
  Build inputs are baseline plus the targeted lock update; remaining source changes
  are tests and this evidence file and are not copied into the production target.
- PyPI JSON confirms Python >=3.10 and both 1.4.3 artifacts are non-yanked.
- Local `npm run test:api:fast`: 2265 passed, 43 skipped, one unrelated preflight
  queue-budget timing failure; that test passed when rerun alone. Subsequent
  `npm run check:fast` passed in full, including 2266 API tests and 43 skips.
  Full `npm run check` exited 1 at the unrelated Next.js `SecurityFatalError`
  notice during web build, after another 2266 API passes and 43 skips. Its later
  PostgreSQL/browser stages were not reached; isolated local PostgreSQL evidence
  and complete CI production/browser results cover those separately. No full
  local PASS is claimed; no frontend upgrade or suppression was made.
- Fresh local Trivy 0.72.0 API-filesystem and production-image vulnerability
  reports inventory Mako 1.4.3 and contain neither advisory ID. Sanitizer removed
  zero secret values. API-filesystem report SHA256:
  `22a8ccb89695a80f9010042e08eedc653a6acf4535b4ebf978f0aaddd0b057e2`;
  API-image report SHA256:
  `4e5d170e90c242959a7eaed8ff6c4ee7a8826287856150de8c4d9cbf9adb6458`.
  The broader local filesystem scan timed out in Dockerfile analysis; use the
  completed full CI filesystem scan below, not that incomplete local result.
- [Security CI 44079927528](https://github.com/gushinets/payments-portal/actions/runs/44079927528)
  passed on source `9272cb2e08ef90aff82d06fe005a0c8de82be150`.
  Downloaded sanitized artifact `14326258428` and verified its ZIP SHA256 against
  GitHub metadata: `bef5cf86f96a153249cdb10a32ca7d593cde1529710b3d449f1d4b21b7c8063f`.
  Full filesystem and final API-image reports contain Mako 1.4.3 and neither
  `CVE-2026-102991` nor `GHSA-5639-2j2p-m4mx`. CI image identity:
  `payment-portal-api@sha256:65bdafb3d45813d4e3021e673d621c1c5d37217849feda600b67df8153bf813d`.
  Existing runtime verification passed in CI too. Report absence concerns the
  target advisory only; it does not claim the repository has no other findings.
- CI code quality passed: fast/coverage API runs each 2308 passed, one skipped;
  frontend 454 passed, plus lint, typecheck and build.
- [CI 44079927567](https://github.com/gushinets/payments-portal/actions/runs/44079927567)
  passed completely on `9272cb2e`: production PostgreSQL workers total 1209 passed,
  one skipped; production images/API smoke passed; browser 248 passed, two skipped,
  React runtime four passed; Linux/Windows harness checks passed. Metadata passed.
  Evidence-only follow-up does not change tested application, lock or test sources.
- Independent read-only review found no actionable issues; final PR diff whitespace
  check passed. No peer or production/security policy change.
- No local vulnerability reproduction was performed. Ordinary Windows path tests
  do not independently prove the vulnerability-specific fix; that claim relies on
  the cited upstream fix and test evidence. No production exploit is demonstrated.

## Handoff

[ANY-741 - Patch Mako path traversal in API dependencies](https://github.com/gushinets/payments-portal/pull/178).
Final pre-submission fetch still resolves origin/main to `2e6d3adc`; no overlapping
changes to reconcile. Disposable local PostgreSQL was stopped using the canonical
worktree-local command; existing services and other worktrees were preserved.
Merge, deployment and issue completion require separate human instruction.
