# ANY-674 — Supported updates and High remediation follow-up

Ticket: https://linear.app/paveldik/issue/ANY-674 · [PR179](https://github.com/gushinets/payments-portal/pull/179)

## Current technical ownership — November21 assignment

**Iosif**, Linear user `bb236781-3bbe-4406-a1fc-1b0c2391b133`, is the
explicitly assigned technical CVE review/remediation owner for Payment portal,
including **all87 currently reported IDs and all12 High IDs**. The
[87-ID ownership record](evidence/ANY-674-ownership-2026-11-21/technical-owners.csv)
enumerates the exact scope and links each row to its existing applicability and
next-action assessment. Assignment authority is the requester's explicit
instruction, transcribed in [ANY-674's ownership addendum](https://linear.app/paveldik/issue/ANY-674)
and Linear issue comment `7b036154-99bd-4f4a-b925-50939756af1c`; project comment
`78f56c9a-7595-4ae9-889b-5bd5585ebb20` records the project-wide role.

The role covers Wednesday dependency/image checks, immediate critical-finding
triage, applicability assessment, reports to Mikhail and tracking remediation
tasks. The proposed current-finding review checkpoint is **2026-12-02**, earlier
on a maintained fix or exposure change. This is a review date, not an approved
exception expiry. Package/backport maintenance commitments, substantial changes
and resources still require their separate decisions. No residual risk is
accepted, no exception is approved and no merge/deployment is authorized by this
assignment.

The hashed scan/applicability ledgers below are frozen **pre-assignment** evidence.
Their `owner: pending team assignment` fields describe capture-time state, not
current ownership. This section and the separately enumerated assignment record
supersede those fields administratively without modifying historical scans,
applicability classifications, package facts or their checksums.

## Outcome

The November21 fresh supported Debian rebuild now contains real package fixes:
**14 glibc advisory IDs /28 finding records eliminated by a Debian patch**.
This supersedes the earlier observation of no available upgrades, without
rewriting that historical result. Python remains3.12.16, Debian remains Trixie,
the digest-pinned base and application dependencies are unchanged.

Two vulnerable optional executables, `infocmp` and `nsenter`, are absent from
the final merged filesystem. Their Essential packages and necessary libraries
remain, so Trivy correctly continues reporting their source-package advisories.
This is component removal, not a library patch or scanner-count reduction.
Production settings now reject non-PostgreSQL databases; development/test SQLite
remains supported. API and migration Compose services explicitly drop all Linux
capabilities and retain no-new-privileges. None of these controls is risk acceptance.

## Comparable images and packages

All three retained images were scanned with Trivy0.72.0, linux/amd64, repository
configuration and one frozen database updated2026-11-21T13:02:47.203212637Z.
Exact scan times, database hash, immutable identities and source revisions are in
[provenance](evidence/ANY-674-high-followup-2026-11-21/provenance.json).

| Image | Debian records / unique IDs | High records / IDs |
| --- | --- | --- |
| Retained historical image, rescanned |221 /101|46 /12|
| Fresh supported rebuild before new controls, d1ff9c34 |193 /87|46 /12|
| Selected final image, e5df91f4 application source |193 /87|46 /12|

No new advisory ID appeared. CVE-2026-124709 changed from Medium in the old
database to High in this database; raw High is retained, not downgraded to the
upstream Low classification. The new snapshot therefore has12 High IDs, versus
the previously recorded11. All comparisons above use the same new snapshot.

| Binary packages | Historical version | Fresh before and selected final |
| --- | --- | --- |
| base-files |13.8+deb13u7|13.8+deb13u8|
| libc6, libc-bin |2.41-12+deb13u4|2.41-12+deb13u5|
| libssl3t64, openssl, openssl-provider-legacy |3.5.7-1~deb13u3|3.5.9-1~deb13u1|

Debian confirms all14 removed IDs fixed in glibc2.41-12+deb13u5; the
[complete101-row ledger](evidence/ANY-674-high-followup-2026-11-21/advisory-dispositions.csv)
enumerates them individually. OpenSSL/base-files updates are applied without
claiming additional advisory elimination. The fresh signed repository probe
records no further pending upgrades. Both fresh images have71 packages with
identical complete versions. The historical87→71 package purge, one Low apt
advisory elimination, and earlier zero-patch comparisons remain historical facts.
ANY-742's independently integrated pip removal is not attributed to ANY-674.

Immutable Docker/OCI platform manifest identities:

- Historical: `sha256:3c894f500266e88c0fd16111c7d1d41decc7667aa0e4970fcfe7beceeb480c9f`.
- Fresh before: `sha256:17274802beeb70e0521d2511f9a272efb9eceb048920b07888063e3ad8f2107d`.
- Selected final: `sha256:a9a6b0df1d1bd7c2209b3c79c72b8c8628fb7b06a6beedf593e42aab01bb2053`.

Trivy archive scans identify the OCI **config** digests instead: respectively
`c5c7d71efe6973f1e16cd3d613cc641bc491bce007973094d239a5a0beed3ca7`,
`962508c8baaa674be831c162216c08eddee34153988825e9c284c69c528f8275`,
`be7c041e74ae4a72c8ebfdde9d32b8ec592a4768a88c96c08af1cc2f3b158fc8`.
These are different identity fields linked by retained archives, not interchangeable
digests. Full archives remain locally retained; sanitized inventories/scans are checked in.

## The infocmp/nsenter experiment

Supported exact `dpkg --path-exclude` configuration followed by a same-installed-
version reinstall of ncurses-bin/util-linux removes only the two named executable
paths. No forced dependency removal or metadata deletion is used. Complete ELF
inventory comparison shows exactly two executable removals; every retained ELF
hash/dependency is unchanged, and neither original executable hash survives under
another name. `dpkg --audit` is clean. `dpkg --verify` gains exactly two expected
missing-path entries, documented by the installed filter configuration; preexisting
Python-slim documentation exclusions are unchanged. Package ownership/checksums
remain accurate and available, including their intentional filtered-file entries.

The startup/migration/health checks do not require these utilities. Necessary
ncurses/tinfo, util-linux libraries and their consumers remain verified. Deleting
Essential utility packages or arbitrary libraries was rejected because it breaks
dependency/runtime contracts. The affected code remains in base/build stages and
lower OCI layers: final merged-filesystem absence does not mean secure erasure
from the image archive. Restoring either tool requires a maintained fixed version.

## Every remaining High: blocker, change and agreement

Each ID below links to current official Debian status. Installed binary versions,
individual triggers and evidence are also in the101-row ledger. No remaining
High source package is claimed patched. Four affected components are absent,
four have no known triggering API consumer, and four remain conditional native
library exposure. This classification is narrower than universal unreachability.

| Advisory | Current exposure and implemented action | Concrete blocker / next change / agreement needed |
| --- | --- | --- |
| [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) | ncurses6.5+20250216-2; vulnerable infocmp analysis executable removed, required libraries retained. | Trixie has no fixed package; upstream6.5-20251213 / unstable6.6+20251231-1 fix. Keep exclusion. Restoring tool needs maintained Trixie fix/backport and regression verification; no architecture change needed for current removal. |
| [CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408) | util-linux2.41.5-0+deb13u1; privileged nsenter --join-cgroup executable removed; API/migrate capabilities dropped. | Trixie unfixed, unstable2.42.4-1 fixed. Keep exclusion; restoration needs maintained fixed package. Removing whole Essential package is unsafe. |
| [CVE-2026-119373](https://security-tracker.debian.org/tracker/CVE-2026-119373) | SQLite3.46.1-7+deb13u2 native code retained; crafted SQLite input/features are prerequisites. Production SQLite configuration rejected; nonproduction/native consumers remain. | No fixed Trixie package. Upstream3.54.0 / unstable3.54.1-1 fixed. Need supported security update or maintained ABI/feature-compatible backport; agree maintenance provider, signed update channel and compatibility testing before custom packaging. |
| [CVE-2026-119374](https://security-tracker.debian.org/tracker/CVE-2026-119374) | Same SQLite version; FTS5 compiled in, including affected secure-delete configuration; malicious database/query features remain conditional. Production DB guard narrows exposure only. | Same supported-update/backport blocker; preserve Python SQLite and native dependencies. Agree backport maintenance/testing scope rather than silently remove library. |
| [CVE-2026-119379](https://security-tracker.debian.org/tracker/CVE-2026-119379) | Same SQLite version; affected session APIs remain; absence of apply_v3 does not prove older APIs safe. PostgreSQL production route enforced. | Same vendor fix/backport requirement; agree supported package ownership/channel and compatibility budget if proceeding before Debian. |
| [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369) | libacl1 2.3.2-2+b1 remains required; symlink/path race requires affected ACL caller and relevant privilege/filesystem access. Non-root, no setid/capability files and cap-drop constrain impact, not patch. | Fixed ACL2.4.0 adds acl_*_at ABI; callers must migrate. Debian says not individually backportable; tar naming collision also exists (bug1141146). Need coordinated maintained ACL/coreutils/sed/tar update, compatibility plan and packaging-maintenance agreement; installing a library alone is insufficient. |
| [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642) | libmount1 2.41.5-0+deb13u1 retained; mount/umount executables absent, known consumers read mount tables rather than perform affected mounts. Cap-drop strengthens boundary. | Trixie unfixed; unstable2.42.3-1 fixed. Need supported security update or maintained source-family backport. Agree provider/update provenance and dependent-library tests if custom packaging is required. |
| [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409) | Same libmount version/consumer evidence; upstream v2.42 fast-path description versus Debian Trixie classification remains a discrepancy, not a cleared advisory. | Obtain Debian applicability clarification; otherwise maintained fix as above. Do not infer unaffected status solely from the upstream version description. |
| [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | Same libmount version; affected mount operation not a known API consumer; library remains scanner-reported. | Same supported update/backport requirement and maintenance agreement; removing required library is not justified. |
| [CVE-2026-124709](https://security-tracker.debian.org/tracker/CVE-2026-124709) | OpenSSL3.5.9-1~deb13u1 still affected; QUIC server rejected-stream leak. API Uvicorn/CPython/HTTPX/libpq use HTTP/TCP/TLS, not OpenSSL QUIC server. Separate bundled psycopg OpenSSL remains unchanged. | No fixed Trixie or upstream package in captured status. Track upstream fix, then supported update. Do not enable affected QUIC functionality before a maintained fix/alternative is evaluated. This assessment does not cover the independent Caddy edge. |
| [CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742) | libsystemd0/libudev1 257.13-1~deb13u1 remain; affected homed/homectl/PAM-homed components absent. | No need to remove required sibling libraries to address absent homed functionality. Keep absence guard; enabling homed would require maintained fixed version and separate deployment review. |
| [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) | perl-base5.40.1-6+deb13u1 remains; vulnerable Archive::Tar module absent/import fails. File::Temp is a different remaining finding. | Keep module absent; restore only a maintained fixed module/package. Essential perl-base purge is not justified. |

These are vendor availability, compatibility and maintenance decisions, not a lack
of operator permissions. Routine supported Trixie updates can be applied within
this task. A self-maintained source backport needs an accountable maintainer,
provenance/signing, recurring updates and test budget. A distro/runtime migration
would additionally require an explicit architecture/deployment decision; none is
introduced here. Prior Bookworm/Alpine candidate limitations remain recorded in
the historical report, rather than presenting arbitrary distro churn as a fix.

## Verification and limitations

Application/runtime source: e5df91f4; subsequent ba32f4d0 changes only test-setting
producers and one regression case. Focused boundary tests10 pass; affected
settings/integration producer tests220 pass/2 existing skips. The first hosted CI
failed because test helpers still supplied SQLite while claiming production;
helpers now supply a valid PostgreSQL settings-only URL without masking explicit
invalid overrides. No application dependency, assertion or skip was removed.

At ba32f4d0, hosted [CI44915352941](https://github.com/gushinets/payments-portal/actions/runs/44915352941),
[Security44915353123](https://github.com/gushinets/payments-portal/actions/runs/44915353123)
and metadata checks pass. Both locally retained images pass offline runtime/native
imports/TLS/compression/timezone checks and actual default-CMD non-root startup,
liveness/readiness with disposable PostgreSQL18.4 and Alembic upgrade→downgrade→upgrade.
Final PID1 effective/permitted/bounding capabilities are zero, no-new-privileges1,
seccomp2; own-namespace setns returns EPERM and cgroup.procs cannot be opened for
writing. No cgroup writes or production exploit tests were performed.

Local `npm run check:fast` and broadest `npm run check` were both attempted at
ba32f4d0. They failed from host memory exhaustion: Node/Vitest heap allocation
failure in web components, and Next prerender ENOMEM in the full check. Full
local downstream API/PostgreSQL stages were not reached; this is not a full local
pass. Hosted canonical/PostgreSQL verification is separately successful. Earlier
build-context file locking and a concurrent scanner cache lock were transient
failed attempts; serial retries succeeded. No unrelated web repair is included.

The [reproduction commands](evidence/ANY-674-high-followup-2026-11-21/commands.md)
and hashed raw evidence substantiate the selected image. Repository scanner
enforcement/ignore policy is unchanged. Remaining87 IDs are individually assessed,
not accepted or suppressed. Technical review ownership is now assigned to
**Iosif** for every remaining ID as recorded above. Scoped follow-up
decisions and any applicable authorized risk approvals remain separate from this
assignment; they are not satisfied by naming an owner. No merge, deployment,
Linear completion or residual-risk approval is performed.
