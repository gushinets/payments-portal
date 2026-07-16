# Papercuts

This file records minor, actionable friction in repository workflows. Follow the
format and safety rules in [AGENTS.md](AGENTS.md), and use Linear or the
documented debt process for product bugs and tracked work.

## 2026-07-16 06:07Z - Codex (GPT-5) - Windows

Running `npm run check:fast` → pytest could not scan its default
`pytest-of-gushinets` temporary directory and stopped four architecture tests
with `PermissionError`. The check passed with
`PYTEST_ADDOPTS=--basetemp=.harness/pytest-tmp`; the harness could make a
repository-local pytest base temp directory the default.
