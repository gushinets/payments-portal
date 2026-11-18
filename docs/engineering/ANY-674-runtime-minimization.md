# ANY-674 — Runtime minimization follow-up

This follow-up preserves the [original comparison](ANY-674-debian-image-evidence.md): 87 unchanged Debian packages, 218 finding records / 96 advisory IDs, zero attributable Debian fixes or removals, and Python 3.12.14 → 3.12.16. The earlier residual request is historical, not approved. This investigation implements feasible removal before requesting any residual decision.

## Selected image and measurable outcome

Runtime source: `f7728c18be8ebcb2f6cba4e647e532af61261c8b`; unchanged baseline source: `6dc518432a2bad5c8a48e6c646b7113e196f26b0`. Successful fetch confirmed origin/main `fb4d66bb0f9f24dbd18257366926697afaa46fe3`. No relevant overlapping main change required reconciliation.

Both use Linux/amd64, Python 3.12.16, uv 0.12.7, the same 55 application distributions, and official Trixie base `python:3.12-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b`. This follow-up does not update a Debian package version or change the distribution.

| Measurement | Fresh unchanged baseline | Selected minimized runtime |
| --- | --- | --- |
| Immutable image identity | `sha256:99bb2325e4360a4d5720b4a4c3ea6120c92cac5b8004df46af36d2fcd61eabef` | `sha256:3c894f500266e88c0fd16111c7d1d41decc7667aa0e4970fcfe7beceeb480c9f` |
| Installed Debian packages | 87 | 71 |
| OS finding records / unique advisory IDs | 218 / 96 | 207 / 95 |
| High / Medium / Low / Unknown records | 47 / 92 / 65 / 14 | 43 / 91 / 59 / 14 |
| Unique High advisory IDs | 11 | 11 |

All 71 retained Debian versions are unchanged. Sixteen packages and 160 owned regular files/symlinks are absent from the merged final filesystem. Eleven finding records disappear through verified package removal; only **CVE-2011-3374 (Low, apt)** is wholly eliminated from the runtime advisory set. No package-patch fixes, newly introduced findings, or severity/status reclassifications occurred. Four removed High records belong to advisories still present on other util-linux binaries; they are not four fixed advisories.

[Comparison](evidence/ANY-674-minimization/comparison.json), [complete package versions](evidence/ANY-674-minimization/package-comparison.csv), [full selected scan](evidence/ANY-674-minimization/final-scan.json), [all dispositions](evidence/ANY-674-minimization/advisory-dispositions.csv) and [validation](evidence/ANY-674-minimization/validation.json) provide machine-readable evidence. The 98 disposition rows retain all 71 historical IDs and 27 original fresh-baseline additions: two historical zlib IDs were fixed before that baseline, one apt ID is now removed, 95 remain scanner-reported. Two reported High IDs have narrower component-absence assessments below; these are not new fixes.

## Why these removals are justified

The final stage creates the app identity and writable runtime directory before removing `apt`, `libapt-pkg7.0`, `sqv`, `debian-archive-keyring`, `adduser`, `passwd`, `mount`, `libbsd0`, `libhogweed6t64`, `libnettle8t64`, `liblz4-1`, `libxxhash0`, `libseccomp2`, `libsemanage2`, `libsemanage-common`, and `libsepol2`.

These are build/package/account/mount tools and supporting libraries with no remaining installed dependency or verified native consumer after this coherent removal. [Per-package flags, versions and reverse dependencies](evidence/ANY-674-minimization/removal-analysis.csv), removal simulations and [file verification](evidence/ANY-674-minimization/removed-files-verification-final.json) substantiate the choice. Every package must explicitly report Essential=no and Protected=no; missing metadata or either flag aborts immediately. Ordinary `dpkg --purge` enforces dependencies without force options, followed by an empty `dpkg --audit`. dpkg and its package database remain accurate. APT's own self-removal simulation warning is retained; no dpkg essential/protected override is used.

Essential/protected shells, login, util-linux and ncurses-bin remain. Removing libc, libacl, libsystemd/libudev or native libstdc++ was rejected by dependency closure or actual ELF consumers. Python curses/readline need ncurses libraries; Python SQLite and util-linux need libsqlite3. Development/build stages retain package tools. The separately scanned build-stage identity `sha256:6f3cb3a514b90ffbc93bc0e517f47290320b6cd316dce8a262e5b2c7dbf3999b` still has 218 records / 96 IDs. Purge whiteouts do not erase underlying base-layer bytes; the claim concerns the merged runtime filesystem, not eradication from image archives. Runtime package installation is no longer supported; updates require image rebuilds.

## Every High advisory

[Detailed High analysis](evidence/ANY-674-minimization/high-advisory-analysis.csv) records exact installed binary/source versions, official Debian status, vulnerable functionality, prerequisites, attempted options, exposure and actionable next steps for all 11 IDs. Official signed Trixie, security and an ephemeral backports policy probe offer no newer fixed candidate for these installed families; no repository changes are shipped.

| Source / advisory | Outcome and next action |
| --- | --- |
| util-linux: CVE-2026-76642, CVE-2026-78409, CVE-2026-78410 | Mount executables removed; source-wide findings remain on required binaries/libraries. Mitigated, not patched. Seek maintained Trixie fixes corresponding to upstream 2.42.3. |
| util-linux: CVE-2026-78408 | nsenter remains in protected util-linux; prerequisites and namespace entry behavior recorded. Seek maintained 2.42.4-equivalent fix. |
| acl: CVE-2026-54369 | Required libacl remains; resolver rejects removal. Maintained Debian update needed; upstream 2.4.0 introduces ABI considerations. |
| ncurses: CVE-2025-69720 | infocmp remains in Essential ncurses-bin; native curses/readline need libraries. Maintained backport of upstream 6.5-20251213 fix needed. |
| sqlite3: CVE-2026-119373, CVE-2026-119374, CVE-2026-119379 | Required SQLite remains with relevant FTS5/session features. PostgreSQL persistence reduces typical use but does not establish unreachability. Seek maintained Trixie backport of upstream 3.54.0 fixes (Debian fixed-source baseline 3.54.1-1). |
| systemd: CVE-2026-16742 | Vulnerable systemd-homed/homectl components absent before and after; libsystemd/libudev source-wide records remain. Supported component non-applicability, not a new package fix. |
| perl: CVE-2026-9538 | Vulnerable Archive::Tar module absent before and after; Essential perl-base remains. Supported component non-applicability, not a new package fix. |

Authoritative status is linked per row to the [Debian tracker](https://security-tracker.debian.org/tracker/). The [systemd advisory](https://github.com/systemd/systemd/security/advisories/GHSA-jm29-p7hh-vjhv) identifies the homed component. Existing non-root execution and no exposed mount/terminal interface are mitigations, not proof that every retained vulnerable path is unreachable. No owner, approval or acceptance is invented. Technical review checkpoint: **2026-12-02**; accountable owner remains **unassigned**. Remaining lower-severity source families and required-dependency reasons are individually retained in the disposition CSV. No ignores or enforcement changes are added.

## Meaningful alternatives actually tested

| Candidate | Immutable image | Result / decision |
| --- | --- | --- |
| First Trixie removal prototype | `sha256:a3d6c7efea6758ffaa3d84dc7171722fe563ab95d01a1b79b115042cf1909931` | Same 207 / 95; replaced by corrected fail-closed implementation after regression reproduced a guard defect. |
| Python 3.12 Bookworm, analogous removal | `sha256:64905c7adcf06f0aab881edc59732b17b7e6409b9018c9b532d4cc71acaf1bdc` | 98 packages, 344 records / 151 IDs, including 2 Critical and 96 High records. Readiness/imports/migrations pass, but existing util-linux minimum contract fails. Rejected older release/ABI change with worse reported exposure. Source-wide Critical zlib/minizip record is not a claim of exploitable application code. |
| Python 3.12 Alpine 3.24 | `sha256:dce0155e24ff98677750c086f6dd11dfa203d5118c21e7856240e553a26b2557` | 40 APK packages, zero reported OS findings; imports, UID999 default startup, readiness and Alembic pass. **Zero scan is not established remediation.** Installed SQLite 3.53.4-r0 predates the three 3.54.0 fixes, relevant features remain enabled, official APKBUILD has no backport, and Alpine secdb lacks these entries. Rejected as evidence of High fixes; musl/package/runtime migration would require a scoped compatibility and maintenance decision. |

Alpine source evidence: [official APKBUILD](https://github.com/alpinelinux/aports/blob/3.24-stable/main/sqlite/APKBUILD), [SQLite 3.53.4 source identity](https://sqlite.org/releaselog/3_53_4.html), [Alpine security database](https://secdb.alpinelinux.org/v3.24/main.json). SQLite source identity and enabled features are captured in checked-in probes. Candidate Dockerfiles, base digests, complete inventories and all OS finding projections are retained in the evidence directory. Neither alternative is shipped. Unstable packages, arbitrary binaries, an unmaintained patch, forced removal and metadata deletion were not adopted.

## Reproduction and provenance

Build from the stated source using the repository's production target (PowerShell example):

```powershell
docker build --pull --no-cache --platform linux/amd64 --target production -f apps/api/Dockerfile -t payment-portal-api:any-674-min-final .
docker image inspect payment-portal-api:any-674-min-final
docker run --rm --entrypoint dpkg-query payment-portal-api:any-674-min-final -W '-f=${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\n'
```

Each actual image was saved to an archive and scanned offline with Trivy 0.72.0 pinned as `aquasec/trivy@sha256:cffe3f5161a47a6823fbd23d985795b3ed72a4c806da4c4df16266c02accdd6f`, `linux/amd64`, repository `trivy.yaml` and `.trivyignore.yaml`, scanners `vuln,secret`, `--skip-db-update --skip-java-db-update --offline-scan --format json --timeout 15m`. Mount the archive/cache and repository read-only as appropriate and use `image --input /evidence/final.tar --config /src/trivy.yaml --ignorefile /src/.trivyignore.yaml` under `--network none`. The reused DB snapshot SHA256 is `b4b9f44be196aac7bf3c359abdcacfaa97a7ccaf56297d04745b7dae554eae86`, UpdatedAt `2026-11-18T07:15:21.579242117Z`. No database drift between comparisons.

Private raw archives, full sanitized reports, build logs and cache remain under `.harness/any-674-minimize/`. Checked-in `scan-projections.json` retains every OS finding for all six images, report hashes, scan times and other-language counts; the selected final report is published in full. Baseline OS signatures exactly match the original retained report. Whole-image Python counts differ from earlier history due the separately integrated Mako fix; no such fix is attributed to this minimization. Image metadata distinguishes immutable descriptor identity from config digest. `SHA256SUMS` covers every published evidence file except itself; LF is enforced only for this evidence directory.

## Verification attributed to source

- Baseline existing runtime verifier passed; the new absence guard failed as expected because apt remained.
- Final `f7728c18` real-image verifier passed non-root, network-disabled imports, ELF links, TLS CA trust, compression, timezone, SQLite and liveness. Pre-existing unsupported optional Tk links were characterized on the baseline and excluded from the required-native-library probe.
- Default production CMD, disposable PostgreSQL readiness and Alembic upgrade/current passed on baseline, prototype, selected final and both alternatives. No app startup package installation/download was needed.
- 25 focused PostgreSQL migration tests passed on `49970528`; application/migration tree is identical at `f7728c18` (`15e178587f0dd0bc3c7694e9da61408cfea3845b`). Final-image migration was independently rerun successfully.
- Existing 99 deployment/dependency contracts passed. Actual-Dockerfile removal guard regression reproduced **6 failures / 4 passes** before correction; all **10 passed** afterward. Tests stub external commands and never purge host packages.
- `npm run check:fast` on `f7728c18`: PASS, 2308 API tests passed / 43 skipped, 454 frontend tests and 38 boundary tests passed.
- `npm run check` on `f7728c18`: FAIL, one unchanged `test_kernel_manifest_client.py::test_complete_http_body_cleanup_retains_slot_after_cancellation_or_deadline[cancel]` timeout; 2307 passed / 43 skipped. Subsequent local web build, PostgreSQL and browser stages were unreached. Isolated rerun passed (1 test); no unrelated repair. An earlier source499 canonical run was explicitly interrupted to fix the reviewed guard defect; it is not counted as passing.
- [CI run 44349245318](https://github.com/gushinets/payments-portal/actions/runs/44349245318) passed on `f7728c18`, including production image/PostgreSQL/migration/API smoke, browser, code-quality and both harness jobs. [Security run 44349245635](https://github.com/gushinets/payments-portal/actions/runs/44349245635) passed with existing report-only policy unchanged.

No merge, deployment, Linear status change or residual-risk approval is part of this work. Next steps concern maintained fixes for the specific retained High families, accountable technical ownership and only then scoped residual decisions where remediation remains infeasible.
