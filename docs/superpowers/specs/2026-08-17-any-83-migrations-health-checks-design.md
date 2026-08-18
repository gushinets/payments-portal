# ANY-83 migration and health-check lifecycle design

Status: approved design, amended after review
Date: 2026-08-18
Linear: https://linear.app/paveldik/issue/ANY-83/vynesti-migracii-iz-zapuska-api-i-dobavit-livenessreadiness-proverki

## Goal

Make API startup deterministic by running Alembic as a separate one-shot
Compose service, and expose distinct liveness and readiness contracts that
Docker, Caddy, and external monitoring can use without leaking configuration or
database failure details.

## Current baseline

The PR branch already runs Alembic through separate development and production
Compose migration services, gates API startup on their successful completion,
and keeps migrations out of the Uvicorn image command. Docker healthchecks and
the production CI smoke use the canonical readiness route.

The PR branch currently exposes both `/api/health/*` and the older `/health*`
routes. Docker Compose, CI, and Uvicorn smoke checks already use the canonical
routes. Caddy proxies only `/api/*`, so the older routes are not available
through the public production boundary. The only non-test repository consumer
of an older route is the API image runtime verifier, which is maintained in
this repository and can move to `/api/health/live`. The application has not
been deployed to production, so there is no external compatibility contract to
preserve.

This review amendment is limited to simplifying the health route surface,
updating the repository-owned runtime verifier, and closing the remaining
OpenAPI review assertion. It does not change the migration lifecycle.

## Considered approaches

### Selected: explicit migration service plus canonical health routes only

Add one-shot `migrate` services to development and production Compose, built
from the same API target and configured with the same validated application and
database environment as the API. The migration service waits for healthy
PostgreSQL and runs `alembic upgrade head`. The API waits for the migration
service to complete successfully and its image command starts only Uvicorn
after the existing settings validation.

Expose liveness and readiness only under `/api/health`. Remove `/health`,
`/health/live`, and `/health/ready`, and update the repository-owned runtime
verifier, tests, generated OpenAPI, and documentation to use the canonical
routes.

This makes migration failure visible as a failed prerequisite, keeps a single
public health contract, and uses the existing Caddy `/api/*` boundary without a
rewrite or duplicate route implementation.

### Rejected: retain compatibility aliases

Keeping `/health*` as aliases would preserve an unused contract and duplicate
the route surface without helping production callers because Caddy does not
proxy those paths. There is no deployed consumer that justifies the additional
compatibility layer.

### Rejected: combine liveness and readiness into one endpoint

A single database-backed health endpoint would make a PostgreSQL outage look
like process failure. Kubernetes and similar orchestrators need separate
liveness and readiness signals so they can stop routing traffic without
restarting an otherwise healthy API process.

### Rejected: a multi-mode shell entrypoint

A custom entrypoint could select migration or server mode from an argument.
That centralizes process commands, but adds shell branching and another runtime
artifact when Compose can already override the command for a one-shot service.

## Health API contract

The canonical endpoints are:

- `GET /api/health/live` returns HTTP 200 and exactly
  `{"status":"alive"}`. It performs no database access.
- `GET /api/health/ready` executes `SELECT 1` through the application session
  factory. Success returns HTTP 200 and exactly `{"status":"ready"}`.
- A SQLAlchemy database failure returns HTTP 503 and exactly
  `{"status":"not_ready"}`. The response contains no exception text,
  connection string, credentials, driver details, or stack trace.

`GET /health`, `GET /health/live`, and `GET /health/ready` are removed. Their
documented replacements are `/api/health/live` and `/api/health/ready`.

Both routes continue through the existing request-context middleware and return
an `X-Request-ID`. Unexpected programming errors are not converted into a
readiness result; only database-layer failures are mapped to the safe 503
response.

The health router and small readiness probe remain application infrastructure.
The probe has one responsibility: open a short-lived session, execute
`SELECT 1`, and close the session. The route layer translates its success or
database exception into the public response contract.

## Compose and process lifecycle

Development and production Compose receive a `migrate` service with these
properties:

1. It uses the same API image target, application code, and environment contract
   as the corresponding API service.
2. It depends on PostgreSQL with `condition: service_healthy`.
3. It runs `python -m alembic -c apps/api/alembic.ini upgrade head` once and
   does not restart after completion.
4. The API depends on it with `condition: service_completed_successfully`.

Shared Compose extension fields may be used for API build and environment
configuration so migration and server settings do not drift. The agent Compose
override continues to add observability dependencies while inheriting the
migration prerequisite from the base file.

Alembic and its shell chaining are removed from both Dockerfile `CMD` values.
The commands retain current development reload behavior and production proxy
flags. Starting an API image directly no longer performs schema mutation; the
deployment orchestrator is responsible for running the migration step first.

The API Docker healthcheck calls
`http://localhost:8000/api/health/ready`. A later database outage therefore
makes the API unready/unhealthy while the liveness endpoint continues to report
that the HTTP process can serve requests.

The existing Caddy `reverse_proxy /api/*` rule already sends
`/api/health/live` and `/api/health/ready` to the API without stripping the
path. No special-case proxy rule is needed. Static contract coverage and an
end-to-end Compose probe will verify the external route used by HetrixTools.

## Tests and verification

Implementation will follow a red/green sequence:

1. Add backend tests for the exact canonical liveness and readiness payloads,
   status codes, and request IDs.
2. Force the database session to fail and prove canonical readiness returns the
   exact safe 503 body without exception or connection details.
3. Prove canonical liveness succeeds while the database probe is failing or
   replaced with a function that would fail if called.
4. Prove the removed `/health*` routes are absent from the application and
   generated OpenAPI contract.
5. Add deployment contract tests proving Dockerfile server commands contain no
   Alembic invocation, both Compose stacks define a one-shot migration service,
   API startup depends on successful migration, and healthchecks use the
   canonical readiness endpoint.
6. Regenerate the OpenAPI artifact with `npm run generate`; do not edit it by
   hand.
7. Run focused API and repository tests, architecture and documentation checks,
   and the broadest supported canonical check.
8. Build and start the Compose stack against PostgreSQL, confirm migration
   completion precedes API startup, exercise the canonical health routes
   directly, and exercise `/api/health/*` through Caddy.
9. Run a negative Compose probe with a deliberately failing migration command
   and confirm that the API does not start.
10. Inspect service logs and the final diff for leaked secrets, raw database
    errors, unrelated edits, and generated-file drift.

If host tooling remains unavailable, equivalent checks will run inside the
repository images. Any verification that cannot run in the local environment
will be recorded explicitly rather than inferred.

## Documentation, scope, and rollback

`README.md` and `docs/architecture/deployment.md` will describe the separate
migration lifecycle, canonical external health paths, removal of the older
routes, and monitoring semantics. `docs/generated/openapi.json` will be
regenerated from the application.

This change does not alter database schema, migrations, payment or legal
behavior, authentication, application settings, or Caddy's general API routing
boundary. It does not add a process manager, a second database, or an external
monitoring service.

The route and Compose changes can be reverted without a data migration. The
one-shot migration remains idempotent under Alembic's revision tracking. If a
migration fails, the deployment stays blocked before API startup and operators
must correct the migration or database condition rather than bypass the
prerequisite.
