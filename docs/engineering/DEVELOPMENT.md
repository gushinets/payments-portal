# Development Environment

Status: authoritative
Last verified: 2026-07-11

Use `scripts/repo.py` through root npm commands. It derives a stable worktree ID,
Compose project, database port, and service ports without sharing state with
another worktree.

```bash
npm run repo:doctor
npm run repo:setup
npm run repo:up
```

The harness writes `.harness/runtime.json` and `.harness/runtime.env`; both are
untracked. Use `npm run repo:down` for normal teardown and `npm run repo:reset`
only when disposable database state may be removed.

Lower-level commands are diagnostic interfaces, not substitutes for the
canonical full check:

```bash
npm run dev:web
npm run dev:api
npm run lint:web
npm run test:api
```

## API dependency management

`apps/api/pyproject.toml` and `apps/api/poetry.lock` are the source of truth for
API dependencies. The API Docker image and repository setup install directly
from the Poetry lock file.

The Makefile API targets below are local shortcuts for Unix-compatible shells
on Linux, macOS, and WSL. They are not a native Windows command interface; use
WSL for these targets. The root npm commands backed by `scripts/repo.py` remain
the cross-platform interface for repository setup, checks, and harness control.

After changing an API dependency, regenerate the lock file:

```bash
make lock_api
```

To synchronize development dependencies into the canonical root virtual
environment, run:

```bash
make install_api
```
