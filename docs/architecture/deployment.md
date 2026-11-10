# Deployment Architecture

Status: authoritative current deployment plus target contour isolation
Last source review: 2026-11-10; deployment acceptance remains separate.

## Current `ru` deployment

The AnyToolAI Portal remains pre-production. This topology is the supported
deployment composition, not evidence of a launched billing service. Its web
entry combines public product discovery and the account/auth cabinet.

```mermaid
flowchart LR
  Browser["Browser"] --> Caddy["Caddy"]
  Caddy --> Web["AnyToolAI Portal · Next.js web container"]
  Caddy --> API["Portal backend · FastAPI API container"]
  DB[("PostgreSQL 18")] -->|"healthy"| Migrate["One-shot Alembic service"]
  Migrate -->|"completed successfully"| API
  API --> DB
  API --> OTEL["Optional telemetry backend"]
  API --> Sentry["Optional Sentry error reporting"]
```

Production Compose builds web and API images and runs Alembic through a
one-shot `migrate` service after PostgreSQL becomes healthy. The API depends on
successful migration completion and its container command starts only Uvicorn;
a failed migration therefore blocks API startup. Only Caddy publishes host
ports, while PostgreSQL, API, and web remain internal. Production must provide
HTTPS termination, `ru` data residency, backups, secret storage, and
monitoring outside this repository's local Compose assumptions.

Both the API and migration service require explicit `INSTANCE_TENANT_ID` and
`INSTANCE_REGION` production environment values. `docker-compose.prod.yml`
fails interpolation when either is absent. The settings are normalized to
lowercase and are the implemented server authority for registration, login,
password reset, required legal-document discovery, authenticated session
scope, and legal writes. They are descriptive deployment identity, not
caller-selectable routing inputs. Local repository defaults are explicitly
`anytoolai` / `ru`; production has no silent contour default. The current
bootstrap and legal source support exactly `anytoolai` / `ru`. Settings,
Alembic bootstrap, and runtime legal seeding fail before successful startup or
bootstrap when a different tenant/region pair is configured. Enabling another
scope requires its dedicated contour/legal enablement ticket; the current
deployment variables are not a generic contour bootstrap selector.

The direct-provider and CloudPayments runtime has been physically removed.
The API implements configured External Billing source reads, purchase/Widget
flows, embedded polling/recovery and local paid projection/cabinet reads. Its
worker runs inside the API process; there is no separate worker service.
Production source conformance, metered vocabulary and launch retain their
acceptance gates. ANY-766 implements snapshot V2, scoped delegation and durable
invalidation delivery; browser launch, usage integration and local paired
acceptance remain pending. Remote installation/live acceptance belong to
ANY-767. Configuration and resource limits are in the
[billing runbook](../engineering/ANY-709-billing-runbook.md#connection-and-deployment)
and [worker operations guide](../engineering/billing-background-operations.md#embedded-worker-settings-and-resource-limits).

Production exposes optional `SENTRY_DSN` and `SENTRY_RELEASE` values to the
shared API/migration environment. An empty DSN keeps Sentry disabled; when a
production deployment supplies a DSN, it must use HTTPS and must also supply
the immutable release identifier through `SENTRY_RELEASE`. `APP_ENV` remains
the Sentry environment source and `OTEL_SERVICE_NAME` remains the
service-identity source. The repository does not hardcode a DSN, discover
releases from container git state, or expose separate Sentry enablement,
environment, service, sampling, debug, Spotlight, metrics, or logging switches.

Sentry is an optional outbound backend application-error destination, separate
from the optional OTLP telemetry backend. It does not own or receive tracing,
application logs, metrics, or profiling, and it does not replace persisted
database state as business truth. Project-side data scrubbing, disabled or
policy-compliant IP collection, and notifications for new or regressed
production issues are operator-managed settings; this repository does not
automate Sentry project management or broad monitoring owned by ANY-86.

`GET /api/health/live` reports only whether the API process can serve HTTP and
does not access PostgreSQL. `GET /api/health/ready` runs `SELECT 1` and returns
HTTP 503 with `{"status":"not_ready"}` when PostgreSQL is unavailable, without
returning database or exception details. Docker uses readiness for API health.
Caddy's `/api/*` proxy exposes both canonical health endpoints for external
monitoring such as HetrixTools. The supported health surface is limited to
these two endpoints; `/health`, `/health/live`, and `/health/ready` are removed
and return HTTP 404.

## Target contour deployments

Each production contour is its own data plane: web, API, PostgreSQL and configured
External Billing credentials and objects. A `ru` instance
does not serve `eu` or `us`. No user or payment data may be silently replicated
between contour data planes.

Region Resolver is deployed separately. It is not part of this Compose stack.
This portal may later receive the resolver origin as instance configuration.
The conceptual user-facing destination is the AnyToolAI Portal for the selected
contour, with Platform Kernel as a separate API/service boundary; no separate
Application Portal peer frontend is required. The Resolver API schema remains
undefined, and this topology defines no response fields or client behavior.
The ANY-715 MVP build uses contour-local embedded polling and has no webhook
receiver. `/api/billing/lbx/webhook` returns 404; there are no receiver settings
to forward through Compose/harness. Keep polling enabled and use the
[polling-only operations guide](../engineering/billing-background-operations.md#polling-only-operation).
Retain existing receipt tables/history; this build does not process that inbox.

The clean baseline validates the configured scope and then bootstraps only the
currently supported `anytoolai` / `ru` contour and its RU country membership.
It never silently substitutes RU data for a different configured scope or
authorizes one production database to operate as two contours.

<a id="one-time-step-4-recreate-and-bootstrap"></a>

## One-time Step-4 recreate and current bootstrap

The Step-4 database is a destructive compatibility boundary. Pre-Step-4
application binaries must never run against it. A database stamped with any
discarded pre-Step-4 migration revision is recreated, not upgraded, downgraded,
stamped or bridged into the clean baseline. Image-only rollback across this boundary
is forbidden: rollback or recovery restores a matching application and
database baseline. Any reset, bootstrap, schema verification, or smoke failure
blocks rollout.

Retired post-Step-4 ANY-709 branch labels use the separately verified
[consolidation transition](../engineering/ANY-709-billing-runbook.md#consolidated-any-709-migration).
They must not be confused with discarded pre-Step-4 databases.

Before starting, identify the exact target application revision/image and
target environment, and record the pre-reset application/database pairing.
Stop every pre-Step-4 API, web, worker, and scheduler process that can access
the database and verify that it cannot restart against the clean database.

For the repository-managed local harness, read `worktree_id` from
`.harness/runtime.json` or from the JSON previously printed by
`python scripts/repo.py up`, then run exactly:

```bash
python scripts/repo.py reset --confirm <worktree_id>
python scripts/repo.py test-db up
python scripts/repo.py migrate-api
```

`reset` executes the harness-scoped Compose
`down --volumes --remove-orphans`; it is the supported destructive local reset.
`test-db up` starts only PostgreSQL. `migrate-api` applies `alembic upgrade head`
to that harness database.

The clean baseline migration owns schema creation and configured-contour/legal
bootstrap; subsequent revisions apply through the same `upgrade head`. The
[schema reference](payment-portal-data-model.md#physical-baseline) owns the
current migration chain and table inventory. Do not create a separate
bootstrap CLI. Before starting normal runtime on a fresh database, verify:

- Alembic reports one head and the database is at that head;
- the current head is `20261110_0008` and exactly 28 application tables exist;
- every removed legacy catalog/order/payment/provider/subscription/
  entitlement/trial table is absent;
- all seventeen billing/link/purchase tables are empty before explicit flows;
- only the configured contour/country state is present;
- the expected legal entity and six current legal document rows match the
  canonical legal source.

After verification succeeds, start only the matching application stack:

```bash
python scripts/repo.py up --reuse
```

The Compose `migrate` service runs the same `alembic upgrade head` before API
startup. The API legal seed remains an idempotent, fail-closed runtime check of
canonical legal material, not a second schema authority. Run retained
provider-independent registration, login, session, password-recovery, and
legal smoke checks.

For shared dev/test/pre-production environments, operators must use that
environment's authoritative process-stop and database destroy/recreate
mechanisms. This repository has no canonical shared-environment commands for
those actions, so the runbook does not fabricate them. The required order is
still: stop and fence old consumers; recreate the old-stamped database; apply
the current head/bootstrap from the matching build; perform the same
schema/bootstrap checks; start only the matching runtime; run the
provider-independent auth/legal smoke suite.

On any failure, keep rollout blocked. Recovery restores or recreates a matching
application+database pair. Never roll back only the image while preserving the
Step-4 database.

## Local worktree deployment

`scripts/repo.py` creates a Compose project name and ports derived from the Git
worktree. PostgreSQL, the one-shot migration service, web, API, and the optional
observability service are scoped to that project. No fixed container names are
permitted in development Compose.

## Platform Kernel connection

Platform Kernel is a separately deployed service and repository in the **same**
contour. Portal reads its configured Capability Manifest endpoint and serves
authenticated snapshot V2. Its embedded worker sends invalidations through the
same Portal → Kernel connection automatically when enabled; configure the
Kernel receiver permission before starting the sender. See
[delivery startup and recovery](../engineering/billing-background-operations.md#any-766-step-7--durable-kernel-invalidations).
Paired local acceptance remains ANY-766 Step 11. Follow the
[pinned implementation map](../integrations/platform-kernel.md) and the boundary
defined by [ADR 0005](decisions/0005-external-billing-boundary.md) and the accepted
[Portal <-> Kernel Access Contract Design](../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md).
This repository must not copy Platform Kernel runtime tables or store its
artifacts and usage events.
