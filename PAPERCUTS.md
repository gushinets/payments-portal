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

## 2026-07-27 07:18Z - Codex (GPT-5) - macOS

Building the production web Docker image → `RUN chown -R node:node /app` took
about 73 seconds and image unpack took about 83 seconds after a successful Next
build. Use `COPY --chown=node:node` or narrow ownership changes to avoid an
expensive full-tree metadata layer.

Trying to run a quick local Caddy/API/web smoke with `scripts/repo.py up` →
Compose began pulling the optional 536 MB observability image before the smoke
could run. Add a harness flag or profile for app-only Caddy smoke so baseline
checks do not need the telemetry stack.

## 2026-07-28 15:01Z - Codex (GPT-5) - macOS

Running targeted API tests with `npm run test:api -- -k ...` → the script failed
with `pytest: command not found` even though `.venv/bin/pytest` existed and
passed the same tests. The npm test entrypoint could delegate through the
repository virtualenv, or `repo:doctor` could warn when pytest is available only
inside `.venv`.

Running Playwright against a manually started local web server → the config read
a stale `.harness/runtime.json` and targeted `127.0.0.1:30207` instead of the
live server on port 3000. Prefer an explicit fresh runtime check, or print the
selected `PLAYWRIGHT_BASE_URL` when the harness runtime file is reused.

## 2026-07-29 08:30Z - Codex (GPT-5) - macOS

Running `npm run generate` after changing the password-reset request schema →
the script failed with `python: command not found` even though the repository
virtualenv had a working interpreter. The npm generate entrypoint could invoke
`.venv/bin/python` when present, or `repo:doctor` could flag a missing `python`
alias. Workaround: run `./.venv/bin/python scripts/repo.py generate`.
