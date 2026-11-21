# ANY-674 — Complete final-image applicability investigation

**Historical snapshot:** the subsequent [High remediation follow-up](ANY-674-high-remediation-followup.md)
records supported glibc fixes (101→87 current IDs), executable removal and fresh
verification. This report and its original raw evidence retain their historical scope.

Ticket: https://linear.app/paveldik/issue/ANY-674 · [existing PR179](https://github.com/gushinets/payments-portal/pull/179)

## Result

Every identifier in the current scanner scope has an individual component, trigger, installed-version, vendor-status, image-evidence and next-action entry in the [101-row ledger](evidence/ANY-674-applicability-2026-11-21/advisory-analysis.csv). The scope contains **97 CVE IDs and four Debian TEMP IDs**, across20 source packages. It is not101 independent exploitable API flaws, and the investigation does not establish that the remaining code is universally unreachable.

Supported Debian updates were checked again against signed Trixie, Trixie security/updates and official backports indexes. The disposable build-base probe reports **zero pending upgrades**; policy tables contain no newer backports version for the installed packages. No repository, dependency-lock or Debian-release migration was introduced. Python3.12.16, uv and the application dependencies remain unchanged in this follow-up.

A further supported hardening change removes the SUID/SGID mode from `/usr/bin/su`, `/usr/bin/newgrp` and `/usr/sbin/unix_chkpwd` through **dpkg-statoverride**. This is recorded in the package manager, retains the owned files and dependency closure, and leaves zero privileged executables or file capabilities in the inspected runtime. It removes the shipped setid privilege-transition prerequisite relevant to the two loader advisories; it does **not** patch glibc or remove their scanner findings. A runtime guard rejects reintroduced privileged files and traversal failures.

The controlled follow-up has **71 identical complete binary/source package versions and221 finding records /101 unique IDs on both sides**:43 High,108 Medium,61 Low,9 Unknown records. No package patch or advisory elimination is attributed to this follow-up. The earlier justified16-package removal and218/96→207/95 comparison remain preserved in the [historical minimization report](ANY-674-runtime-minimization.md). The increase from95 to101 IDs belongs to a later scanner snapshot, not newly introduced packages.

## What applicability means

| Evidence-based assessment | IDs | Meaning and limit |
| --- | ---: | --- |
| Affected component absent |14| The specific executable, module or extension is absent from the final image; sibling libraries/source-package scanner entries remain. |
| Different architecture |1| The advisory concerns Power8; this tested image is linux/amd64. |
| Trigger disabled in shipped configuration |4| PAM userdb not configured; unknown-login logging disabled; or shipped setid transition removed. Root/operator reconfiguration invalidates this boundary. |
| Known API consumers do not use the trigger |20| Audited native wheel sources, TLS consumers or mount-table readers do not invoke the affected operation. Libraries remain available to other local/native callers. |
| Component present; conditional exposure remains |62| Code/utility remains and requires the per-ID input, feature or privilege prerequisite. This is not a claim of non-applicability. |

All101 raw IDs, captured severities and221 records remain visible. No ignore, severity downgrade, enforcement change or scanner suppression was added. Component/configuration assessments are separate from package remediation counts.

The14 component-absence IDs are `CVE-2026-42250`, `CVE-2026-54371`, `CVE-2026-54370`, `CVE-2026-91094`, `CVE-2013-4392`, `CVE-2026-15059`, `CVE-2026-16742`, `CVE-2026-40228`, `CVE-2022-0563`, `CVE-2024-56433`, `CVE-2026-89092`, `CVE-2026-82560`, `CVE-2026-9538` and `CVE-2025-70873`. Their ledger rows identify the actual missing component and retained sibling. These absences mostly predate this follow-up and are not14 new removals.

The architecture-specific ID is `CVE-2026-97399`. Configuration/privilege assessments cover `CVE-2026-54411`, `CVE-2007-5686`, `CVE-2026-95818` and `CVE-2026-86805`.

## High findings first

There are11 unique High IDs represented by43 binary-package finding records. Repeated util-linux binary records are not independent advisories.

| High advisory | Actual component and triggering prerequisite | Outcome and next technical step |
| --- | --- | --- |
| CVE-2026-16742 | systemd-homed group modification by a homed-managed local account | homed/homectl and its PAM component absent; retain component-absence check. Installed systemd libraries are not a homed service. |
| CVE-2026-9538 | Perl Archive::Tar processing an untrusted oversized tar entry | Archive::Tar absent and import fails for that precise missing module. File::Temp is present and assessed separately. |
| CVE-2026-76642 | privileged libmount helper failure followed by ownership/idmap hooks | mount/umount absent; retained libmount consumers inspect mount tables. Hooks remain in the library. Seek maintained Trixie fix; recheck any new mount caller. |
| CVE-2026-78409 | libmount detached-tree/subdirectory resolution of attacker-controlled paths | Same absence of current mount invoker. Exact Trixie source differs from the newer restricted-user fast path; Debian still lists it vulnerable, so no package-safe claim. |
| CVE-2026-78410 | privileged bind source replacement followed by ownership/mode hooks | Same current-consumer boundary; no supported fixed Trixie candidate. Do not restore privileged mount helpers without reassessment. |
| CVE-2026-78408 | privileged nsenter --join-cgroup against attacker-controlled target | nsenter remains in Essential util-linux; non-root API does not run this operation. Operator/root execution remains relevant. Maintained fixed util-linux is the next package remedy. |
| CVE-2026-54369 | privileged pathname ACL operation raced through attacker-controlled path components | libacl APIs and coreutils/sed/tar consumers remain. Removing libacl breaks declared dependencies. A maintained library fix and affected-caller migration are needed; avoid privileged operations on untrusted paths. |
| CVE-2025-69720 | infocmp analysis of crafted terminal capabilities | infocmp/libtic remain in Essential ncurses-bin. Maintained fix needed; ordinary API startup does not parse supplied terminal descriptions. No forced removal or binary stripping adopted. |
| CVE-2026-119373 | FTS5 detail=none, negative rowids and crafted prefix MATCH | FTS5 is enabled in actual SQLite3.46.1. PostgreSQL production default does not remove SQLite code. Maintained SQLite fix/backport needed; do not process untrusted SQL/database files. |
| CVE-2026-119374 | corrupt FTS5 index plus secure-delete operation | FTS5 remains enabled. Same maintained-package route; no blanket feature-absence assertion. |
| CVE-2026-119379 | malformed session changeset through shared apply routines | SESSION and older apply APIs are present. Missing apply_v3 alone does not exclude shared vulnerable code. Maintained package/backport or separately scoped compatible rebuild required. |

Per-ID authoritative Debian/upstream links, development fixed versions where available, triggering details and option evaluations are in the ledger. A fixed unstable/development version is not treated as a supported Trixie binary. No exploit was run against production.

## Remaining severities and native consumers

The same investigation covers all Medium, Low and Unknown records. Actual image evidence includes gconv modules, libc/resolver exports, retained commands, SQLite compile options/modules/session symbols, PAM/login configuration, Perl imports, ELF dependency/symbol metadata and file ownership. UTF-8 locale is not used to claim that iconv implementations vanished. Missing journald/journalctl does not exclude journal parsing: retained `lslogins` imports the reader APIs. Retained `rmt`, `sulogin`, `su` and Perl File::Temp are explicitly accounted for.

The only three direct libstdc++ consumers are the protobuf upb extension, greenlet and its shipped C++ test extension. Their actual ELF hashes match the official locked wheels; matching source archives/build files were inspected for affected inline/template operations. This is stronger than looking for undefined symbols, but is not a reproduction of every compiler-header input. The [native-consumer analysis](evidence/ANY-674-applicability-2026-11-21/glibc-gcc-consumers.json) states that limit and the per-ID next actions.

System OpenSSL is3.5.7, while the unchanged psycopg binary wheel bundles its own **OpenSSL3.5.4**. An apt update does not update that private copy. Known CPython/HTTPX and libpq consumers use ordinary TCP TLS rather than QUIC/DTLS/DANE/CMS/SuiteB-server or arbitrary AES-GCM-SIV paths. For the existing-stack CA parsing advisory, both identified OpenSSL source versions pass a NULL stack through the normal CA-file loader. These are scoped consumer assessments, not claims that either installed library is patched. A wheel dependency update or runtime-layout change requires separate compatibility work; none was silently introduced here.

## Further removal and update options tested

The [exact final-image removal simulations](evidence/ANY-674-applicability-2026-11-21/api-removal-options.json) cover26 candidates with their Essential/Protected flags, direct dependencies and command results. No simulation executes removal or uses force options.

- 24 candidates are blocked by Essential/Protected status or declared reverse dependencies: shells, core utilities, dpkg/tar/Perl, ncurses-bin, util-linux, PAM/login configuration and required native libraries. Libraries such as libacl/libattr/libbz2/systemd/udev/SQLite/OpenSSL cannot be removed independently while preserving that closure.
- libstdc++ and libncursesw pass dpkg simulation because Python wheels/interpreter extensions are not represented as Debian reverse dependencies. Actual ELF/native consumers require them: greenlet/protobuf and Python curses/panel. A successful package-manager simulation is therefore insufficient evidence for removal.
- Earlier apt/account/mount-tool removals remain verified; the build stage still retains its update tools and is scanned separately. No build-stage finding is claimed removed from the build merely because it is absent at runtime.
- A maintained newer base must improve actual packages without changing Debian release. This pinned Python3.12 Trixie base plus fresh upgrades already resolves to the current supported candidates. Historical Bookworm/Alpine alternatives remain in the minimization report: Bookworm worsened the measured set; Alpine's zero Debian findings did not measure equivalent risk and changed ABI/distribution.
- Selectively deleting library files, gconv modules, scanner databases, essential executables or mixing unstable packages would break package integrity or operational contracts. A smaller/distroless layout or maintained custom SQLite build could remove additional surface, but requires a separately designed runtime/package/ABI maintenance approach. Neither is presented as an exhausted impossibility or adopted incidentally.

The supported [uv --no-build option](https://docs.astral.sh/uv/reference/cli/#uv-sync--no-build) now applies to both production and development dependency stages. Sonar identified possible source-build hook execution in the newly archived control recipe. The canonical Dockerfile was hardened and the actual current-platform images rebuilt; installed application and Debian package versions are identical to the prior image. All70 registry dependencies have locked wheels; successful linux/amd64 production/development builds are the compatibility evidence, not wheel enumeration alone. Future dependencies without a compatible wheel fail the build and require a deliberate packaging decision. No lock/version upgrade, pip change, scanner exception or artifact rename was used. The checked-in control recipe now comes from this new tested run, while the [earlier1b33 pair](evidence/ANY-674-applicability-2026-11-21/historical-pair-1b33.json) preserves its original IDs/counts/hashes and immutable Git/CI references to every original raw file.

The three setid overrides were selected because they reduce unnecessary privilege without deleting package contents. No further supported patch or dependency-preserving package purge was demonstrated by these checks.

## Reproducible image comparison

The [provenance](evidence/ANY-674-applicability-2026-11-21/provenance.json), [database metadata](evidence/ANY-674-applicability-2026-11-21/database-metadata.json), raw sanitized scans, component inventories and SHA256SUMS are checked in. The source snapshot is `7ed98b8a8f17f5e32f48cb1db18bffeb914bd380`, based on fetched main `49ed895d3925e097ef7e46908c87a6cb75f0fb26`. Later documentation/probe corrections do not change this snapshot's Dockerfile or application dependencies.

| Controlled linux/amd64 production target | Immutable image ID | Packages | Debian records / IDs | Setid files |
| --- | --- | ---: | ---: | ---: |
| Control: exact recipe with only three privilege overrides removed | sha256:a6afedb696033512bc8aa03ea1cd3be374ede1c88df1f29aea0a95f218a5fdbb |71|221 /101|3|
| Selected hardened runtime | sha256:1a61e9210326aec9cb92bcce8ce4b3d32f8bf8d77d790ecbf898608384d50328 |71|221 /101|0|

Base: `python:3.12-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b`. Trivy0.72.0 used identical configuration, platform and DB file for both scans, with offline/no-update flags. DB SHA256 is `1c7f2883070385e7540c75c0bb31bbb6840edc05c76785a3075ff49933028d56`, updated2026-11-20T18:59:53Z. All finding projections are identical; nothing disappeared or was severity-reclassified in this pair.

```sh
docker build --pull --no-cache --platform linux/amd64 --target production -f apps/api/Dockerfile -t any674-final .
security/trivy/verify-api-runtime.sh any674-final
sh security/trivy/verify-api-postgres.sh any674-final
mkdir -p .harness/any674-comparison
python security/trivy/inspect-api-updates.py --baseline-dockerfile
docker build --platform linux/amd64 --target production -f .harness/any674-comparison/control.Dockerfile -t any674-control .
# Use one explicit cache for both scans; the workflow records its metadata and hash.
trivy image --cache-dir .harness/any674-db --download-db-only
trivy image --cache-dir .harness/any674-db --skip-db-update --skip-java-db-update --offline-scan --config trivy.yaml --ignorefile .trivyignore.yaml --scanners vuln,secret --format json --output .harness/any674-comparison/control-image.json any674-control
trivy image --cache-dir .harness/any674-db --skip-db-update --skip-java-db-update --offline-scan --config trivy.yaml --ignorefile .trivyignore.yaml --scanners vuln,secret --format json --output .harness/any674-comparison/final-image.json any674-final
```

The control build reuses the freshly rebuilt common base/dependency prefix from the no-cache final build; only the three asserted override lines differ. No update layer is inherited from an older production build. CI artifacts preserve reports for14 days; their ZIP hashes and IDs are recorded. Full image tarballs were not published because automated approval rejected that content transfer. CI daemon image retention is ephemeral; checked-in inventories, scans and immutable identities persist. Rebuilding later can change IDs/timestamps and package candidates; verify again rather than assuming bit reproducibility.

## Verification and remaining work

- Focused tests cover component collection failures, ELF parsing, removal simulations, control-recipe invariants and the fail-closed privileged-file/runtime guard. The two new privileged-file cases failed before hardening and passed afterwards.
- Local `npm run check:fast` at exact runtime source `7ed98b8a`: passed; JUnit2611 cases,2560 passed,51 skipped;454 web component tests passed. Earlier helper-transition evidence remains historical and is not used as the latest exact-revision pass.
- Local `npm run check`: exit1 after web build because the worktree PostgreSQL service was unavailable. PostgreSQL stages were not reached locally. Earlier interrupted canonical attempts remain interrupted, not successful.
- [CI44832843100](https://github.com/gushinets/payments-portal/actions/runs/44832843100) at `a46ce633`: all five jobs passed, including fast checks/coverage, web build/typecheck, PostgreSQL tests/migration cycles, production Compose build/default-CMD readiness and browser evidence. [Security44832843186](https://github.com/gushinets/payments-portal/actions/runs/44832843186) passed actual scanned-image imports, TLS CA validation, compression/timezone/SQLite/native-link checks, non-root startup/liveness, package probes and the one-DB comparison. PostgreSQL evidence in this run used a separate same-source production-gate build; exact scanned-image PostgreSQL verification is recorded in the follow-up below.
- The intermediate source `cd21c2be` Security job failed when redaction received a root JSON list; `f56c0419` fixed its object schema and reran successfully. Sonar subsequently flagged arbitrary CLI evidence paths in `a46ce633`; `dc21de42` restricts them to fixed repository/evidence paths. Neither is concealed as a passing intermediate revision.

### Exact scanned-image follow-up

[Security44839563431](https://github.com/gushinets/payments-portal/actions/runs/44839563431), source `7ed98b8a`, passed. The [PostgreSQL runtime evidence](evidence/ANY-674-applicability-2026-11-21/api-postgres-runtime.json) names the **same immutable final image as the scan** and verifies UID999, unmodified default CMD, liveness/readiness and `upgrade head / downgrade base / upgrade head` against disposable PostgreSQL18.4. The internal network prevents external runtime downloads. The retained one-DB control/final comparison above comes from this run; the prior a46ce633 pair remains separately retained in its CI artifact/private evidence.

The build-base scan remains separately visible:232 Debian records /102 IDs,47 High,109 Medium,67 Low,9 Unknown records. Runtime removal does not eliminate build-stage exposure. The failed7ef15ec0 probe completed migrations but failed host-port discovery;87ed64f3 moved HTTP checks inside the isolated API container and stages JSON only after success. 1b33a906 also generates ephemeral DB credentials and uses a fixed-path output handle; the current Sonar open-issue query returned zero, without exceptions or suppressions.

The downloaded wheel-only-source PostgreSQL artifact14680502029 reports1218 passed /1 skipped /0 failures or errors, with ZIP SHA256 `bd543c8229ec8c679a3127a8af315736402672fc2a1c4558a8610083b6b670c0`. The [verification summary](evidence/ANY-674-applicability-2026-11-21/verification-summary.json) separates exact-revision local fast, blocked local full, focused and hosted results. Final-head CI status is recorded in the PR handoff. The current local focused suite passed71 tests, including the external-path CLI regression (pre-correction accepted/wrote the supplied destination; corrected CLI exits2 and creates no file).

All101 IDs have a documented technical disposition;62 remain component-present conditional findings, with explicit limits and options rather than invented fixes. Maintained Debian/backport fixes should be applied when published, and new native consumers/configuration must reopen the relevant assessments. Proposed review: **2026-12-02**, earlier on fixes or exposure changes. Technical review ownership remains **pending team assignment**; that ticket criterion is still pending and does not assign the requester. No acceptance decision is requested or recorded by this work. No merge, deployment or issue completion was performed.
