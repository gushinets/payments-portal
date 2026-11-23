# ANY-674 — Debian production-image remediation

Ticket: https://linear.app/paveldik/issue/ANY-674 · [PR179](https://github.com/gushinets/payments-portal/pull/179)

## Result and comparable evidence

Python remains 3.12.16, Debian Trixie, uv and application dependencies retained.
The initial Python 3.12.14→3.12.16 change fixed **zero Debian advisories**:
87 unchanged package versions, 218 records /96 IDs on each side.
Verified minimization subsequently removed16 unnecessary packages (87→71),
eliminating apt CVE-2011-3374; its same-database comparison was218/96→207/95.
The refreshed database later identified221 records /101 IDs in the retained image.

Available supported updates then changed base-files13.8+deb13u7→u8,
libc6/libc-bin2.41-12+deb13u4→u5, and openssl/libssl3t64/
openssl-provider-legacy3.5.7-1~deb13u3→3.5.9-1~deb13u1.
The Debian glibc patch fixed14 advisory IDs /28 records.

| Same frozen database, linux/amd64 | Records / unique IDs | High records / IDs |
| --- | --- | --- |
| Retained historical image |221 /101|46 /12|
| Fresh supported rebuild, before additional controls |193 /87|46 /12|
| Selected final image |193 /87|46 /12|

No new advisory ID was introduced. OpenSSL CVE-2026-124709 was reclassified
Medium→High by scanner metadata; this is not a newly introduced vulnerability.
Supported dpkg path filters remove only infocmp/nsenter;71 package records and
726 retained ELF records match before/after, with2 intentional missing-file
verification entries. These component removals do not erase source-package CVEs.
Capabilities drop to zero; production requires PostgreSQL; no scanner exception.

## Immutable identities and reproduction

Trivy0.72.0; database updated2026-11-21T13:02:47.203212637Z, SHA-256
`a11e6268518754ba292fe789eaf77173dc82e77b021d4458ca43f1ab10f6c757`.

| Image | OCI index / Docker image identity | Actual linux/amd64 manifest |
| --- | --- | --- |
| Historical | `sha256:3c894f500266e88c0fd16111c7d1d41decc7667aa0e4970fcfe7beceeb480c9f` | `sha256:465c9bb96f547914be0de9202e039142894adc0b5be90dd62bdf30d7271eb519` |
| Fresh before | `sha256:17274802beeb70e0521d2511f9a272efb9eceb048920b07888063e3ad8f2107d` | `sha256:172443474938ca8481d1c79a5e23e6d526e4fb5d4c86f6d849d1c603c142a6d9` |
| Final | `sha256:a9a6b0df1d1bd7c2209b3c79c72b8c8628fb7b06a6beedf593e42aab01bb2053` | `sha256:1e5c131fd4b90860832254708608589c83a2b6a47758ddbce856f9d2991dc03c` |

Identity correction: historical prose called index identities platform manifests.
The separately verified manifest column above corrects that label; original raw
reports are unchanged. Frozen scans used the same scanner/config/database.

```sh
docker build --pull --no-cache --platform linux/amd64 --target production -f apps/api/Dockerfile -t payment-portal-api:any674-high-after-20261121 .
bash security/trivy/verify-api-runtime.sh payment-portal-api:any674-high-after-20261121
bash security/trivy/verify-api-postgres.sh payment-portal-api:any674-high-after-20261121
npm run check:fast
npm run check
```

Full scanner invocation, pinned scanner/base digests, scan timestamps and report
hashes are preserved in `ANY-674-high-followup-2026-11-21/commands.md`,
`provenance.json` and SHA256SUMS within the [local archive](evidence/ANY-674/README.md).
A future fresh build may obtain newer packages; it does not recreate old images.

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

## Verification, ownership and limits

Runtime source e5df91f4: normal UID999/default CMD, native imports, TLS,
compression/timezone, liveness/readiness and disposable PostgreSQL18.4
Alembic upgrade→downgrade→upgrade passed for retained before/final images.
No runtime installation/download is required. Bookworm/Alpine candidates were
built and rejected; changed distro/scanner coverage alone was not a fix.

At f81cb6d4, [CI45024321223](https://github.com/gushinets/payments-portal/actions/runs/45024321223)
passed all5 jobs and [Security45024321262](https://github.com/gushinets/payments-portal/actions/runs/45024321262)
passed, including runtime/migration/security evidence. Focused reconciliation:
102 cases passed. Separate CI-port repair is tracked as ANY-904; pip work is
attributable to ANY-742. Local canonical checks at3ced88e0 each timed out400s
in API-fast; full downstream stages were unreached locally, not passed.
No runtime rerun is claimed for this documentation-only archive relocation.

All101 IDs have individual applicability/options in the retained comparison CSV;
87 remain scanner-reported. Iosif is the explicitly assigned technical owner
for all87 including12 High. Proposed review checkpoint:2026-12-02, earlier on
maintained fixes or exposure changes. Capture-time raw ledgers saying pending
ownership are superseded by the November21 assignment, reconfirmed November22.
No risk approval, exception, merge, deployment or issue completion is implied.

Complete historical evidence is [retained locally with checksums](evidence/ANY-674/README.md)
by user instruction; external reviewers need to request the archive from its owner.
