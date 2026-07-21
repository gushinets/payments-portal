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

## 2026-07-20 05:38Z - Codex (GPT-5) - macOS

Running `npm run check:fast` directly → the npm script could not start because
`python` was not available on PATH. Once `scripts/repo.py` was launched with
`.venv/bin/python`, the existing virtualenv re-exec behavior kept checks and
pytest on the repository interpreter; the remaining friction is the npm entry
point's dependency on a `python` executable being discoverable.

## 2026-07-20 17:00Z - Codex (GPT-5) - macOS

Running PostgreSQL Alembic integration tests from the local `.env` database key
→ the sandboxed attempt was blocked and the escalated attempt found no local
database listener. `repo:doctor` reported busy preferred ports but did not give
a one-command path to a fresh test database; a targeted test-DB helper or clearer
doctor hint would make migration evidence less dependent on ambient harness
state.

## 2026-07-21 10:11Z - Codex - macOS

Running repository commands → every zsh startup printed missing
`/opt/homebrew/bin/brew` errors from `.zprofile`. Likely stale Homebrew init
lines on a machine without that path; guard the init with an existence check or
remove it to keep command evidence readable.

## 2026-07-21 10:42Z - Codex - macOS

Running targeted Playwright against Next dev → using `127.0.0.1` for a server
advertised as `localhost` blocked Next dev resources and prevented hydration.
Use `PLAYWRIGHT_BASE_URL=http://localhost:<port>` or configure
`allowedDevOrigins` when intentionally testing through `127.0.0.1`.

## 2026-07-21 12:52Z - Codex (GPT-5) - macOS

Running `python3 scripts/repo.py check --fast` after the npm `python` shim
failure → docs passed, then generation stopped on `ModuleNotFoundError: No
module named 'sqlalchemy'` while importing the API data model. A doctor hint or
bootstrap step for API Python dependencies would make the fallback check path
clearer.
