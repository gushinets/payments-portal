# ANY-314 - API Image Trivy Baseline

Status: active
Owner: `@gushinets`
Started: 2026-08-17
Linear: https://linear.app/paveldik/issue/ANY-314/ustranit-trivy-baseline-dlya-api-production-base-image

## Objective

Clear the production API image enforcement baseline by installing every
available Debian security update and recording four package-scoped temporary
exceptions for unfixed upstream `perl-base` Critical vulnerabilities.

## Scope and decisions

- Preserve Python 3.12 and the existing Poetry application dependency lock.
- Replace base digest
  `sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf`
  with the current multi-architecture `python:3.12-slim` digest
  `sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a`.
- Apply available Debian stable package upgrades during image construction and
  remove apt indexes from the resulting layer.
- Scope the four unavoidable exceptions to
  `pkg:deb/debian/perl-base`, owner `@gushinets`, and expiry `2026-09-30`.
- Verify the final image runs as `app`, includes the fixed `util-linux`
  baseline, and serves `/health/live` before scanning it in CI.
- Leave the external `TRIVY_ENFORCE` repository variable unchanged. An
  administrator can enable it only after merge and human exception approval.
- No API source, migration, web image, Python dependency, or Poetry lock change
  is part of this remediation.

## Authoritative baseline and upstream status

- GitHub Actions run `31792790500`, artifact
  `trivy-reports-31792790500-1`, scanned
  `payment-portal-api:trivy-a1ff0728fe9e230a99c362f3f2232f916c5d3166`
  with Trivy 0.72.0. The image was Debian 13.5 with image config ID
  `sha256:fb49421057c5016c46c7bac5df74e9fa2f8a69f0dba8125b59650293e2750ae8`.
- That report contained four Critical findings in `perl-base 5.40.1-6` and
  zero fixable High findings:
  `CVE-2026-13221` (`affected`),
  `CVE-2026-42496` (`fix_deferred`),
  `CVE-2026-57433` (`affected`), and
  `CVE-2026-8376` (`affected`). None had a `FixedVersion`.
- On 2026-08-17, the current pinned Python base identifies Python 3.12.14 and
  Debian 13.6 but still contains `perl-base 5.40.1-6`. Its unmodified amd64
  baseline has the same four Critical findings and nine fixable High findings
  in the `util-linux` source-package family.
- Debian's Security Tracker still reports Trixie `5.40.1-6` as vulnerable for
  all four Critical findings and does not provide a complete Trixie fix:
  https://security-tracker.debian.org/tracker/CVE-2026-13221,
  https://security-tracker.debian.org/tracker/CVE-2026-42496,
  https://security-tracker.debian.org/tracker/CVE-2026-57433, and
  https://security-tracker.debian.org/tracker/CVE-2026-8376.
- Dependabot PR #30 changes the API to Python 3.14 and the web image to Node 26
  while still inheriting Debian Trixie. It mixes unrelated major upgrades and
  does not provide the missing `perl-base` fixes, so it is not the ANY-314
  remediation: https://github.com/gushinets/payments-portal/pull/30.

## Progress

- [x] Reproduce the authoritative GitHub and current upstream baselines.
- [x] Apply and test the four approved temporary exceptions.
- [x] Refresh and rebuild the production API image.
- [x] Pass the final-image package, non-root, and liveness verification.
- [x] Confirm raw Trivy has exactly the four approved Critical findings and
  zero fixable High findings.
- [x] Confirm the exception-filtered API report has zero blocking findings.
- [x] Pass backend and repository checks supported by the local environment.
- [ ] Pass the GitHub `Security scans` workflow on the PR's amd64 image.
- [ ] Mirror final evidence and the draft PR URL to ANY-314.

## Implementation evidence

- The pre-change production image built successfully from digest `423ed6ab...`.
  `security/trivy/verify-api-runtime.sh payment-portal-api:any-314-baseline`
  then failed as intended with
  `Expected util-linux >= 2.41.5-0+deb13u1, got: 2.41-5`.
- `docker build --pull --target production --file apps/api/Dockerfile --tag
  payment-portal-api:any-314 .`: passed. Debian upgraded `bsdutils`,
  `libblkid1`, `liblastlog2-2`, `libmount1`, `libsmartcols1`, `libuuid1`,
  `mount`, and `util-linux` to `2.41.5-0+deb13u1`, plus `login` to
  `1:4.16.0-2+really2.41.5-0+deb13u1`.
- The final local arm64 image is 73,307,795 bytes, runs as `app`, uses Python
  3.12.14, and retains `perl-base 5.40.1-6`. Its image config ID is
  `sha256:3c54b195e6eddcaa075152bd2b92557880b551d4f9a38bebeef2307e4e04f432`;
  the BuildKit manifest-list ID is not used as stable evidence because its
  provenance attestation changes between otherwise identical builds.
- `security/trivy/verify-api-runtime.sh payment-portal-api:any-314`: passed with
  the fixed minimum package version, non-root user, and
  `GET /health/live -> {"status":"ok"}`.

## Security evidence

- A fresh Trivy 0.72.0 scan on 2026-08-17 detected Debian 13.6 in the final
  local arm64 image. The raw report has exactly the four approved Critical
  `perl-base` findings and zero fixable High findings.
- The raw report also contains ten High findings without a `FixedVersion`:
  `CVE-2026-41992` in `gzip`, `CVE-2026-54369` in `libacl1`, four package
  occurrences of `CVE-2025-69720` in the `ncurses` family, and
  `CVE-2026-42497`, `CVE-2026-48962`, `CVE-2026-57432`, and `CVE-2026-9538`
  in `perl-base`. Under the checked-in policy, unfixed High findings do not
  block enforcement.
- Raw severity totals are 4 Critical, 10 High, 53 Medium, 59 Low, and 3
  Unknown. The raw report is retained locally at
  `.harness/trivy-any314/api-image-raw.json` and is not committed.
- The same scan with `.trivyignore.yaml` removes the four Critical findings by
  package PURL. `summarize_trivy_report` reports 0 Critical, 0 fixable High, 0
  High/Critical misconfigurations, 0 High/Critical secrets, and therefore 0
  blocking findings. The filtered report is retained locally at
  `.harness/trivy-any314/api-image.json` and is not committed.
- Each temporary exception names the affected API image and Dockerfile, states
  that no fixed Trixie package was available on 2026-08-17, assigns owner
  `@gushinets`, references ANY-314, scopes to
  `pkg:deb/debian/perl-base`, and expires on 2026-09-30.
- The local image is arm64 because it was built on Apple Silicon. The PR
  `Security scans` result for the GitHub runner's amd64 image remains the
  authoritative cross-architecture completion gate.

## Validation

- Exception policy red/green: the new contract failed before the four entries
  were added, then passed; complete `test_trivy_gate.py`: 8 passed.
- Independent review hardening: the exception contract now requires exactly the
  four approved CVEs, exact package PURL, image/Dockerfile, owner, ticket,
  no-fix reason, and expiry. A temporary fifth-CVE mutation failed as expected;
  the approved policy then passed with 8 Trivy gate tests.
- Runtime baseline red/green: the verifier rejected the old image at
  `util-linux 2.41-5`, then passed against the rebuilt image at
  `2.41.5-0+deb13u1`.
- The final verifier also proves that `app` resolves to a nonzero UID and bounds
  each liveness request to a one-second connection timeout and two-second total
  timeout. Its detached container already remains available for logs until the
  cleanup trap removes it.
- Focused API checks:
  `test_trivy_gate.py` plus `test_python_dependency_contracts.py`: 62 passed.
- Complete API checks: 207 passed, 15 skipped. All 15 skips are PostgreSQL-only
  checks because `POSTGRES_USER_TEST`, `POSTGRES_PASSWORD_TEST`,
  `POSTGRES_PORT_TEST`, and `POSTGRES_DB_TEST` are not configured locally.
- `python3 scripts/repo.py architecture check`: passed.
- `python3 scripts/repo.py docs check`: passed.
- `scripts/repo.py generate --check` in the project test image: passed. The host
  attempt could not import SQLAlchemy because the repository Python environment
  is not installed.
- GitHub Actions workflow YAML parsed with PyYAML 6.0.3 in the project test
  image; `git diff --check` passed.
- `npm run check:fast` and `npm run check` were both attempted and could not run
  because `npm` is absent from the local `PATH`. PR CI remains responsible for
  the Node-owned and canonical aggregate checks.
