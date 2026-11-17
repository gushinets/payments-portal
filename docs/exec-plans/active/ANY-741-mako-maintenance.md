# ANY-741 Mako dependency maintenance

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
- [ ] Repeat focused tests; run API lock, fast and canonical checks and applicable PostgreSQL checks.
- [ ] Build production API image, verify runtime/version, obtain fresh sanitized filesystem/image scans.
- [ ] Review final diff/current main, publish focused PR and record remaining limitations.

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
- Full API suite, canonical checks and fresh Trivy scans are still running.
- No local vulnerability reproduction was performed. Ordinary Windows path tests
  do not independently prove the vulnerability-specific fix; that claim relies on
  the cited upstream fix and test evidence. No production exploit is demonstrated.
