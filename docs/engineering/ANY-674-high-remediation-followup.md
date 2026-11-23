# ANY-674 — Production image maintenance handoff

Ticket: https://linear.app/paveldik/issue/ANY-674

## Delivered changes

Refresh the digest-pinned Python3.12/Trixie image, apply supported Debian updates,
remove unnecessary production tools, and retain uv and application dependencies.
Preserve non-root startup, native imports, TLS, timezone support and Alembic.
Production settings require PostgreSQL. API/migration services drop capabilities
and retain no-new-privileges. Runtime inspection and disposable PostgreSQL checks
verify the built image rather than assuming a successful apt command fixes it.
Scanner policy, severity and scoped exceptions are unchanged.

## Results and evidence

Supported package patches eliminated14 advisory IDs /28 records in the retained
same-database comparison (101→87 IDs). Earlier Python-only and component-removal
comparisons remain separate; no claim that all vulnerabilities are fixed.

Full per-advisory analysis, package inventories, immutable image identities and
historical build/runtime/migration evidence are retained outside this branch.
The local archive contains155 original files from source f81cb6d4, preserved on
`codex/any-674-evidence-archive-20261123`. Archive SHA-256:
`d44ab5451da33bda874c228d0370713396bb55e2b5946423aab7653009628b37`.
Obtain the archive from the technical owner; it is not uploaded by user instruction.
The [superseded draft PR179](https://github.com/gushinets/payments-portal/pull/179)
retains original review context. This branch contains no audit dataset or old
PR history. Creating it does not remove previously published GitHub copies.

## Agreed follow-up

[Mikhail's November23 decision](https://linear.app/paveldik/issue/ANY-674#comment-7545d4a8)
covers all87 remaining findings, including12 High: Iosif owns weekly Wednesday
checks and reports, with immediate escalation for critical findings or changed
API applicability. Wait for official Debian Trixie fixes rather than undertake
own-package fixes now, preserve production restrictions and visible findings.
SQLite/ACL are reviewed again on2026-12-02; apply supported fixes and rescan when
available, otherwise reassess and propose the next review. No scanner exception,
architecture migration, merge or deployment is authorized by that decision.
The decision was [mapped to the existing P1](https://github.com/gushinets/payments-portal/pull/179#discussion_r4665190243);
reviewer acceptance remains for a human reviewer.

## Verification provenance

Earlier f81cb6d4 [CI](https://github.com/gushinets/payments-portal/actions/runs/45024321223)
and [Security](https://github.com/gushinets/payments-portal/actions/runs/45024321262)
passed, including runtime, readiness, PostgreSQL migrations and browser checks.
Historical local canonical attempts had memory failures/timeouts and are not
reported as full passes. New-branch results are recorded in its PR; old-head
results are characterization only. Runtime changes are copied exactly from the
reviewed successor6e650f46, not reimplemented during the PR transfer.

ANY-742 owns the separately integrated pip work. ANY-904 owns the CI-port repair
retained here; ANY-831 scanner integration and strict redaction are preserved.
