# ANY-674 — Production image maintenance

Ticket: https://linear.app/paveldik/issue/ANY-674

## Implementation

Refresh the digest-pinned Python 3.12/Trixie image, apply supported Debian updates,
remove unnecessary production tools, and retain uv and application dependencies.
Preserve non-root startup, native imports, TLS, timezone support and Alembic.
Production settings require PostgreSQL. API/migration services drop capabilities
and retain no-new-privileges. Runtime inspection and disposable PostgreSQL checks
verify the built image. Scanner policy and scoped exceptions are unchanged.

## Agreed follow-up

[Mikhail's November 23 decision](https://linear.app/paveldik/issue/ANY-674#comment-7545d4a8)
assigns Iosif Wednesday dependency/image checks and reports, with immediate
escalation for critical findings or changed API applicability. Wait for official
Debian Trixie fixes rather than undertake own-package fixes now. Preserve
production restrictions and keep findings visible in Trivy.

Review SQLite/ACL again on 2026-12-02. Apply supported fixes and rescan when
available; otherwise reassess and propose the next review date. This decision
does not authorize scanner exceptions, architecture migration, merge or deployment.

## Verification

Run production-image runtime and disposable PostgreSQL migration verifiers,
deployment-contract tests and canonical checks. Record results against the tested
revision in the PR; do not describe incomplete runs as passes.

ANY-742 owns the separately integrated pip work. ANY-904 owns the CI-port repair;
ANY-831 scanner integration and strict redaction are preserved.
