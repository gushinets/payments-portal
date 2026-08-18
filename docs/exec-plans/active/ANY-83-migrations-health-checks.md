# ANY-83 - Migration and Health-Check Lifecycle

Status: active
Owner: Nikita
Started: 2026-08-17
Linear: https://linear.app/paveldik/issue/ANY-83/vynesti-migracii-iz-zapuska-api-i-dobavit-livenessreadiness-proverki

## Objective

Run Alembic as a separate one-shot Compose prerequisite, expose independent
liveness and PostgreSQL-backed readiness contracts, and use only the canonical
health surface before the first production deployment.

## Scope and decisions

- `GET /api/health/live` returns `{"status":"alive"}` without accessing the
  database.
- `GET /api/health/ready` runs `SELECT 1`, returns `{"status":"ready"}` on
  success, and returns HTTP 503 with `{"status":"not_ready"}` for a
  database-layer failure.
- `/health`, `/health/live`, and `/health/ready` are removed and return HTTP
  404. ANY-83 permits either temporary compatibility or a documented
  replacement; the repository is not deployed to production, so the reviewed
  decision is to document the canonical replacement without aliases.
- The repository usage audit found Docker Compose, CI, Caddy, and Uvicorn smoke
  tests already using `/api/health/*`. The only non-test legacy consumer was
  `security/trivy/verify-api-runtime.sh`, which now uses `/api/health/live`.
- Development and production Compose define a one-shot `migrate` service that
  waits for healthy PostgreSQL. The API waits for successful migration
  completion.
- Development, production, and agent API healthchecks use
  `/api/health/ready`.
- Existing Caddy `/api/*` routing exposes the canonical health endpoints; no
  special rewrite is required.
- No migration revision, database schema, payment, legal, authentication, web,
  or general Caddy-routing behavior changed.

## Progress

- [x] Approve and commit the design and implementation plan.
- [x] Add canonical liveness and readiness contracts through RED/GREEN tests.
- [x] Audit legacy consumers and remove the undeployed compatibility routes.
- [x] Add one-shot development and production migration services.
- [x] Remove Alembic from API image startup commands.
- [x] Switch every API Docker healthcheck to canonical readiness.
- [x] Update operational documentation and regenerate OpenAPI.
- [x] Verify positive and negative migration lifecycle behavior.
- [x] Verify real database outage and recovery behavior.
- [x] Run all locally supported backend, web, image, and repository checks.

## Commits

- `2a589b8` - `ANY-83 - Document migration and health-check design`
- `184db48` - `ANY-83 - Add implementation plan`
- `c85f784` - `ANY-83 - Add safe liveness and readiness endpoints`
- `363c1b2` - `ANY-83 - Gate API startup on migrations`
- `c9bbabe` - `ANY-83 - Document migration and health operations`
- `99f251e` - `ANY-83 - Fix production gate migration smoke`
- `b4ba406` - `ANY-83 - Simplify health route design`
- `8d595c0` - `ANY-83 - Add canonical health route plan`
- `ce8301f` - `ANY-83 - Remove legacy health routes`
- `64befda` - `ANY-83 - Document canonical health routes`

## TDD evidence

- Initial health contract run: 3 failed as expected. Canonical routes returned
  404 and legacy readiness did not satisfy the safe database-failure contract.
- After the minimal health implementation: 3 passed.
- Focused health/API run: 5 passed, 83 deselected.
- App-factory and Uvicorn compatibility run: 6 passed.
- Initial deployment contract run: 6 failed and 2 passed. Both Compose files
  lacked `migrate`, all three healthchecks used the legacy path, and both API
  image commands still contained Alembic.
- After the Compose and Dockerfile implementation: 8 deployment contract tests
  passed.
- Review amendment route run: 4 failed as expected because `/health`,
  `/health/live`, and `/health/ready` still returned 200 and remained in
  OpenAPI; the other 91 selected tests passed.
- After removing the compatibility router: all 95 selected health, API, and
  app-factory tests passed, including the requested readiness OpenAPI tag.
- The unchanged production-image verifier failed against removed
  `/health/live`; after moving it to `/api/health/live` and the canonical
  `{"status":"alive"}` payload, it passed against the same image.

## Static and generated validation

- `python3 scripts/repo.py architecture check`: passed.
- `python3 scripts/repo.py docs check`: passed.
- The repository generator first reported only
  `docs/generated/openapi.json` as stale. The generator was then run through
  the API development image because host npm is unavailable.
- `scripts/repo.py generate --check` in the API development image: passed.
- The generated OpenAPI contains `/api/health/live` and `/api/health/ready` and
  contains none of `/health`, `/health/live`, or `/health/ready`.
- Full API Ruff check: passed.
- Full API Ruff format check: 68 files already formatted.
- `git diff --check`: passed during every implementation stage.

## Backend validation

- Complete API run in the development image: 218 passed, 15 skipped. The 15
  skipped cases were exactly the PostgreSQL partition before a live test
  database was attached.
- PostgreSQL partition against a dedicated temporary database in the isolated
  development stack: 15 passed, 218 deselected.
- The PostgreSQL run covered Alembic upgrade/downgrade, database fixtures,
  SQLAlchemy PostgreSQL behavior, constraints, concurrency, idempotency, and
  CloudPayments webhook persistence.
- Review-amendment full API run used
  `TEST_POSTGRES_DATABASE_URL=.../anytoolai_tests`: 236 passed with no skipped
  tests. This combined the portable and PostgreSQL partitions in one run.

## Compose and runtime validation

The first-pass observations below predate the review amendment. Legacy-route
responses are retained as historical evidence, not as the current contract.

- Rendered development, production, and merged agent Compose models were valid.
  Development and production `api` depend on `migrate` with
  `service_completed_successfully`; `migrate` depends on PostgreSQL with
  `service_healthy`. The agent merge additionally preserves PostgreSQL and
  observability dependencies.
- Isolated development project `payments-5f528356` started successfully.
  PostgreSQL became healthy, `migrate` exited 0, then API became healthy. Web
  and Caddy also started successfully.
- The built development API image command contains settings validation and
  Uvicorn only; it contains no Alembic command.
- Direct API responses were exact and included `X-Request-ID`:
  `/api/health/live` -> 200 `{"status":"alive"}`,
  `/api/health/ready` -> 200 `{"status":"ready"}`,
  `/health` -> 200 `{"status":"ok"}`,
  `/health/live` -> 200 `{"status":"ok"}`, and
  `/health/ready` -> 200 `{"status":"ready"}`.
- Caddy returned 200 with the exact canonical `alive` and `ready` bodies and
  propagated `X-Request-ID`.
- With development PostgreSQL stopped, canonical and legacy readiness returned
  HTTP 503 with exactly `{"status":"not_ready"}`, while canonical liveness
  remained HTTP 200 with `{"status":"alive"}`. Readiness returned to HTTP 200
  after PostgreSQL became healthy again. Stable measured readiness latency was
  4-6 ms.
- The isolated negative project used a migration command that exited 42.
  Compose returned non-zero, `migrate` was `Exited (42)`, and `api` remained
  `Created` without starting. Its disposable containers, networks, and volume
  were removed after evidence capture.
- An isolated production Compose smoke built and ran PostgreSQL, production
  `migrate`, and production API. Migration exited 0 and API became healthy.
  Internal canonical live/ready probes returned the exact expected bodies.
- The production API image runs as non-root user `app`; its configured command
  contains settings validation and Uvicorn only.
- `security/trivy/verify-api-runtime.sh payments-any83-prod-smoke-api:latest`:
  passed.
- `security/trivy/verify-api-runtime.sh payments-any83-health-review`: passed
  after the verifier moved to canonical liveness.
- The review-amendment development Compose smoke rebuilt the API, completed
  the one-shot migration, and reached healthy API and Caddy states. Direct API
  `/api/health/live` and `/api/health/ready` returned exact 200 `alive` and
  `ready` bodies; `/health`, `/health/live`, and `/health/ready` returned 404.
  Caddy returned the same exact canonical 200 bodies through `/api/*`.
- The final production image rebuild and runtime verifier passed. The temporary
  Compose containers and networks were stopped without deleting volumes.
- The disposable production-smoke containers, networks, and PostgreSQL volume
  were removed after evidence capture.

## Log review

- Migration logs contained the expected Alembic upgrade sequence and no errors.
- API logs contained no Alembic invocation, traceback, exception, authorization
  value, bearer token, connection string, CloudPayments secret, SMTP password,
  or session token.
- Caddy logs contained no errors or sensitive patterns.
- PostgreSQL errors were limited to expected constraint tests and the
  administrator-command connection termination from the deliberate outage.

## Web and canonical-check evidence

- Production web build passed twice, including TypeScript and all 17 static
  pages.
- Web component tests: 4 files and 26 tests passed.
- Web ESLint: passed with zero warnings.
- Web boundary tests: 9 passed after mounting the root
  `playwright.runtime-env.cjs` helper read-only into the builder test context.
  The first builder-only attempt lacked that root helper; this was a test-image
  context limitation, not a source failure.
- Host `npm run check` was attempted and could not start because npm is absent
  from the host `PATH`. Every constituent canonical check was run through the
  repository's API and web images: docs, generated artifacts, architecture,
  API Ruff, API fast and PostgreSQL tests, web boundaries, web components, web
  lint, and production web build.
- Browser E2E was not run because ANY-83 changes no rendered UI and the
  canonical command skips it unless `RUN_E2E=true`. Direct and Caddy HTTP
  runtime probes covered the affected external journey.

## Handoff

PR #52 is the review vehicle for the local `ANY-83` branch and uses the required
title `ANY-83 - Separate migrations and add health checks`. Its body links the
Linear issue above. The remaining review thread stays unresolved until a human
explicitly authorizes a reply or resolution.
