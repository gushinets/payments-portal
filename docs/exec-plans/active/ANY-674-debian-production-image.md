# ANY-674 — Production image delivery plan

Ticket: https://linear.app/paveldik/issue/ANY-674

## Scope and coverage

Apply supported Debian updates and justified runtime minimization while preserving
Python 3.12, uv, application dependencies and deployment contracts. Retain focused
regressions for package removal, native inspection, production settings, scanner
integration and CI port isolation. The [maintenance plan](../../engineering/ANY-674-high-remediation-followup.md)
records implementation boundaries and the agreed follow-up.

- [x] Implement supported image updates and runtime restrictions.
- [x] Preserve non-root startup, readiness and PostgreSQL migration verification.
- [x] Verify 183 focused tests with Git Bash, documentation, lint and PR metadata.
- [x] Record the agreed monitoring and December 2 review plan.
- [ ] Verify exact-head hosted canonical and security checks.
- [ ] Obtain human review acceptance.

Documentation-only edits require link and metadata checks; runtime changes require
image verification. No merge, deployment, policy exception or Linear completion.
