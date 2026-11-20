# ANY-674 — Technical handoff and pending team ownership

Current all101 component-level investigation: [complete applicability report](ANY-674-complete-applicability.md). Earlier snapshots and completion statements below are historical; the latest ledger retains pending team ownership.

Latest verification: [review corrections and refreshed CI](ANY-674-review-corrections.md) reports101 current advisory IDs on identical71 package versions. All current ownership is pending team assignment. The95-ID enumeration below preserves the earlier18November scope; the refreshed current ledger adds6glibc/OpenSSL IDs.

## Technical completion

Supported in-place remediation and verification are complete for runtime source `f7728c18`. The selected final image and controlled before/after scans, exact versions, removal justification, startup/readiness and migration results are recorded in the [minimization report](ANY-674-runtime-minimization.md). Historical results remain preserved. No additional supported Trixie/security/backports candidate was available for retained affected families at investigation time. Sixteen justified removals were implemented and verified; no speculative removals or distribution migration were adopted.

The final image has 207 Debian finding records / 95 advisory IDs, including 43 High records / 11 High IDs. One Low advisory was eliminated by verified package removal; no High patch fix is claimed. Per-ID applicability, mitigations, available remediation options and next actions remain in the [current disposition ledger](evidence/ANY-674-minimization/advisory-dispositions.csv) and [High analysis](evidence/ANY-674-minimization/high-advisory-analysis.csv). Existing local full-check limitations remain disclosed; technical handoff does not turn those historical failures into passes.

## Outstanding development-team action

**Ownership: pending team assignment.** The development team must assign accountable technical remediation/mitigation/review ownership to each explicitly enumerated ID below or a defined group. Proposed review checkpoint: **2026-12-02**, earlier if a maintained fix or exposure change appears. This is a proposed technical review date, not an approved risk-acceptance expiry.

The ticket's residual-ownership acceptance criterion remains **pending**. It does not block completing and handing off the technical work. The requester is not assigned any CVE ownership or risk acceptance. No owner, risk decision, approval reference, security exception or policy change is inferred. Continued investigation/backport evaluation is a technical follow-up, not acceptance of continued risk. Any eventual accepted residual risk requires its own explicit authorized human decision. The issue remains open for the unmet criterion; no merge, deployment or Done transition is authorized.

## Exact current scope by source package

All 95 scanner-reported IDs are included, including the two narrower component-absence assessments. Grouping is for team assignment, not an assertion that every finding has identical applicability or mitigation. Consult each ledger row for its disposition.

- **acl** (2; owner: pending team assignment): `CVE-2026-54369`, `CVE-2026-54370`.
- **attr** (1; owner: pending team assignment): `CVE-2026-54371`.
- **bash** (1; owner: pending team assignment): `TEMP-0841856-B18BAF`.
- **bzip2** (1; owner: pending team assignment): `CVE-2026-42250`.
- **coreutils** (4; owner: pending team assignment): `CVE-2017-18018`, `CVE-2025-5278`, `CVE-2026-56391`, `CVE-2026-56392`.
- **dash** (2; owner: pending team assignment): `CVE-2026-102473`, `CVE-2026-102474`.
- **diffutils** (1; owner: pending team assignment): `CVE-2026-53910`.
- **dpkg** (1; owner: pending team assignment): `CVE-2026-91094`.
- **gcc-14** (7; owner: pending team assignment): `CVE-2026-102010`, `CVE-2026-114690`, `CVE-2026-114691`, `CVE-2026-115455`, `CVE-2026-115456`, `CVE-2026-125709`, `CVE-2026-95619`.
- **glibc** (24; owner: pending team assignment): `CVE-2010-4756`, `CVE-2018-20796`, `CVE-2019-1010022`, `CVE-2019-1010023`, `CVE-2019-1010024`, `CVE-2019-1010025`, `CVE-2019-9192`, `CVE-2026-100290`, `CVE-2026-115819`, `CVE-2026-18374`, `CVE-2026-19499`, `CVE-2026-19542`, `CVE-2026-5435`, `CVE-2026-6238`, `CVE-2026-6368`, `CVE-2026-6791`, `CVE-2026-77117`, `CVE-2026-80489`, `CVE-2026-84243`, `CVE-2026-8674`, `CVE-2026-86805`, `CVE-2026-89092`, `CVE-2026-95818`, `CVE-2026-97399`.
- **ncurses** (2; owner: pending team assignment): `CVE-2025-6141`, `CVE-2025-69720`.
- **openssl** (8; owner: pending team assignment): `CVE-2026-107493`, `CVE-2026-107496`, `CVE-2026-124709`, `CVE-2026-35190`, `CVE-2026-88822`, `CVE-2026-88823`, `CVE-2026-95691`, `CVE-2026-95692`.
- **pam** (1; owner: pending team assignment): `CVE-2026-54411`.
- **perl** (4; owner: pending team assignment): `CVE-2011-4116`, `CVE-2026-15534`, `CVE-2026-82560`, `CVE-2026-9538`.
- **shadow** (3; owner: pending team assignment): `CVE-2007-5686`, `CVE-2024-56433`, `TEMP-0628843-DBAD28`.
- **sqlite3** (14; owner: pending team assignment): `CVE-2021-45346`, `CVE-2025-70873`, `CVE-2026-119371`, `CVE-2026-119372`, `CVE-2026-119373`, `CVE-2026-119374`, `CVE-2026-119375`, `CVE-2026-119376`, `CVE-2026-119377`, `CVE-2026-119378`, `CVE-2026-119379`, `CVE-2026-119591`, `CVE-2026-50812`, `CVE-2026-50813`.
- **systemd** (7; owner: pending team assignment): `CVE-2013-4392`, `CVE-2023-31437`, `CVE-2023-31438`, `CVE-2023-31439`, `CVE-2026-15059`, `CVE-2026-16742`, `CVE-2026-40228`.
- **sysvinit** (1; owner: pending team assignment): `TEMP-0517018-A83CE6`.
- **tar** (5; owner: pending team assignment): `CVE-2005-2541`, `CVE-2026-18477`, `CVE-2026-18508`, `CVE-2026-5704`, `TEMP-0290435-0B57B5`.
- **util-linux** (6; owner: pending team assignment): `CVE-2022-0563`, `CVE-2026-3184`, `CVE-2026-76642`, `CVE-2026-78408`, `CVE-2026-78409`, `CVE-2026-78410`.
