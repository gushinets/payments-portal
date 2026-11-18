# ANY-674 — Residual-risk decision awaiting human input

Status: **HISTORICAL pending request; technical follow-up completed; no risk approved**

The owner directed additional High-first package removal, minimization and supported-update investigation before any residual acceptance proposal. The 96-ID scope below describes the original unminimized image. It is retained as history, not an active blanket acceptance request for the follow-up image. Current outcomes and the separately pending team ownership criterion are recorded in the [technical handoff](ANY-674-technical-handoff.md). The current 95-ID scope supersedes this historical 96-ID request. Ownership is pending team assignment; it does not block technical handoff. No requester ownership or risk acceptance is recorded.

This record covers exactly the 96 unresolved Debian advisory IDs enumerated below. The two historical zlib IDs absent from the fresh baseline are excluded. Per-ID installed package identity, vendor status, conditions, runtime relevance and existing mitigations remain in [the disposition ledger](evidence/ANY-674/advisory-dispositions.csv).

| Required decision field | Current record |
| --- | --- |
| Accountable owner(s) | UNASSIGNED — responsible human must name an owner for each ID or explicitly enumerated group |
| Human decision | PENDING — accept, decline or defer must be stated by the authorized human |
| Scope | The 96 IDs below; a narrower decision must enumerate its own subset |
| Existing mitigations | Per-ID ledger; non-root app runtime and production no-new-privileges do not establish complete unreachability or a package fix |
| Additional conditions or actions | Awaiting human decision; none invented |
| Review or expiry | Proposed 2026-12-02 only; not an approved exception expiry |
| Approver and approval reference | PENDING — link or explicit human authorization required |

A shared decision may cover an explicitly enumerated group if it names the accountable owner, scoped decision/mitigations, review or expiry date and approval reference. The agent may transcribe that decision but cannot assign accountability or accept risk. Until these fields are supplied for every residual ID, ANY-674 remains pending acceptance. CI success and the corrected package evidence do not resolve this blocker. Enforcement, ignores and exception policy remain unchanged. No merge or deployment is authorized by this record.

## Explicit residual scope

- **acl** (2): `CVE-2026-54369`, `CVE-2026-54370`.
- **apt** (1): `CVE-2011-3374`.
- **attr** (1): `CVE-2026-54371`.
- **bash** (1): `TEMP-0841856-B18BAF`.
- **bzip2** (1): `CVE-2026-42250`.
- **coreutils** (4): `CVE-2017-18018`, `CVE-2025-5278`, `CVE-2026-56391`, `CVE-2026-56392`.
- **dash** (2): `CVE-2026-102473`, `CVE-2026-102474`.
- **diffutils** (1): `CVE-2026-53910`.
- **dpkg** (1): `CVE-2026-91094`.
- **gcc-14** (7): `CVE-2026-102010`, `CVE-2026-114690`, `CVE-2026-114691`, `CVE-2026-115455`, `CVE-2026-115456`, `CVE-2026-125709`, `CVE-2026-95619`.
- **glibc** (24): `CVE-2010-4756`, `CVE-2018-20796`, `CVE-2019-1010022`, `CVE-2019-1010023`, `CVE-2019-1010024`, `CVE-2019-1010025`, `CVE-2019-9192`, `CVE-2026-100290`, `CVE-2026-115819`, `CVE-2026-18374`, `CVE-2026-19499`, `CVE-2026-19542`, `CVE-2026-5435`, `CVE-2026-6238`, `CVE-2026-6368`, `CVE-2026-6791`, `CVE-2026-77117`, `CVE-2026-80489`, `CVE-2026-84243`, `CVE-2026-8674`, `CVE-2026-86805`, `CVE-2026-89092`, `CVE-2026-95818`, `CVE-2026-97399`.
- **ncurses** (2): `CVE-2025-6141`, `CVE-2025-69720`.
- **openssl** (8): `CVE-2026-107493`, `CVE-2026-107496`, `CVE-2026-124709`, `CVE-2026-35190`, `CVE-2026-88822`, `CVE-2026-88823`, `CVE-2026-95691`, `CVE-2026-95692`.
- **pam** (1): `CVE-2026-54411`.
- **perl** (4): `CVE-2011-4116`, `CVE-2026-15534`, `CVE-2026-82560`, `CVE-2026-9538`.
- **shadow** (3): `CVE-2007-5686`, `CVE-2024-56433`, `TEMP-0628843-DBAD28`.
- **sqlite3** (14): `CVE-2021-45346`, `CVE-2025-70873`, `CVE-2026-119371`, `CVE-2026-119372`, `CVE-2026-119373`, `CVE-2026-119374`, `CVE-2026-119375`, `CVE-2026-119376`, `CVE-2026-119377`, `CVE-2026-119378`, `CVE-2026-119379`, `CVE-2026-119591`, `CVE-2026-50812`, `CVE-2026-50813`.
- **systemd** (7): `CVE-2013-4392`, `CVE-2023-31437`, `CVE-2023-31438`, `CVE-2023-31439`, `CVE-2026-15059`, `CVE-2026-16742`, `CVE-2026-40228`.
- **sysvinit** (1): `TEMP-0517018-A83CE6`.
- **tar** (5): `CVE-2005-2541`, `CVE-2026-18477`, `CVE-2026-18508`, `CVE-2026-5704`, `TEMP-0290435-0B57B5`.
- **util-linux** (6): `CVE-2022-0563`, `CVE-2026-3184`, `CVE-2026-76642`, `CVE-2026-78408`, `CVE-2026-78409`, `CVE-2026-78410`.
