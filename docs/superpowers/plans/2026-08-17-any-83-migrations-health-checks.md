# ANY-83 Migration and Health-Check Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run Alembic as an explicit one-shot Compose prerequisite and expose safe canonical liveness/readiness endpoints while preserving every existing health route.

**Architecture:** Move health routing and the PostgreSQL readiness probe into a focused application-infrastructure module, then register canonical and compatibility routers at the composition root. Build migration and API services from the same image/environment contract, gate API startup on successful migration completion, and use canonical readiness for Docker and public monitoring.

**Tech Stack:** Python 3.12, FastAPI 0.141.1, SQLAlchemy 2.0.51, Alembic 1.18.5, PostgreSQL 18.4, Docker Compose, Caddy 2.11.4, pytest 9.1.1

## Global Constraints

- Work in the existing local `ANY-83` branch; the user explicitly selected that checkout, so do not create another worktree.
- Keep all existing `/health`, `/health/live`, and `/health/ready` routes during the compatibility period.
- `GET /api/health/live` must return HTTP 200 with exactly `{"status":"alive"}` and must never touch PostgreSQL.
- `GET /api/health/ready` must execute `SELECT 1`, return HTTP 200 with exactly `{"status":"ready"}`, and map database-layer failure to HTTP 503 with exactly `{"status":"not_ready"}`.
- Health responses must not contain connection strings, credentials, exception text, stack traces, CloudPayments configuration, or other internal state.
- The API must start only after a one-shot Alembic service completes successfully; migration failure must leave the API stopped.
- Remove Alembic from both API image startup commands and keep the current development reload and production proxy behavior.
- Docker healthchecks must call `/api/health/ready`; Caddy must continue to expose `/api/health/*` through the existing `/api/*` proxy boundary.
- Do not change schema revisions, payment, legal, authentication, catalog, subscription, entitlement, or Caddy's general API routing behavior.
- Do not hand-edit `docs/generated/openapi.json`; run the repository generator.
- Add behavior tests first and use PostgreSQL/Compose verification for migration lifecycle behavior.
- Record skipped verification explicitly when the local environment cannot support it.

---

### Task 1: Add canonical and compatibility health contracts

**Files:**
- Create: `apps/api/app/health.py`
- Create: `apps/api/tests/test_health.py`
- Modify: `apps/api/app/main.py:1-105`
- Modify: `apps/api/tests/test_api.py:386-412`
- Modify: `apps/api/tests/compatibility/test_app_factory.py:8-26`
- Modify: `apps/api/tests/compatibility/test_uvicorn_smoke.py:65-88`

**Interfaces:**
- Consumes: `app.core.database.SessionLocal`, SQLAlchemy `text` and `SQLAlchemyError`, FastAPI `APIRouter`, and `JSONResponse`.
- Produces: `canonical_health_router`, `legacy_health_router`, and `database_is_ready() -> bool` from `app.health`.

- [ ] **Step 1: Write focused failing health tests**

Create `apps/api/tests/test_health.py` with:

```python
from __future__ import annotations

from apps.api.tests.support.settings import configure_api_test_environment

configure_api_test_environment()

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

import app.health as health_module  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)


class FailingSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, statement):
        raise OperationalError(
            "SELECT 1",
            {},
            RuntimeError("postgresql://internal:secret@database/payments"),
        )


def test_canonical_health_contract() -> None:
    live_response = client.get(
        "/api/health/live",
        headers={"X-Request-ID": "canonical-live"},
    )
    ready_response = client.get("/api/health/ready")

    assert live_response.status_code == 200
    assert live_response.json() == {"status": "alive"}
    assert live_response.headers["X-Request-ID"] == "canonical-live"
    assert ready_response.status_code == 200
    assert ready_response.json() == {"status": "ready"}
    assert ready_response.headers["X-Request-ID"]


def test_liveness_does_not_call_database_probe(monkeypatch) -> None:
    def fail_if_called() -> bool:
        raise AssertionError("liveness called the database readiness probe")

    monkeypatch.setattr(health_module, "database_is_ready", fail_if_called)

    assert client.get("/api/health/live").json() == {"status": "alive"}
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health").json() == {"status": "ok"}


def test_readiness_database_failure_is_safe(monkeypatch) -> None:
    monkeypatch.setattr(health_module, "SessionLocal", FailingSession)

    for path in ("/api/health/ready", "/health/ready"):
        response = client.get(path)

        assert response.status_code == 503
        assert response.json() == {"status": "not_ready"}
        assert "postgresql" not in response.text
        assert "secret" not in response.text
```

- [ ] **Step 2: Run the focused module and verify the red state**

Run:

```bash
.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_health.py -v
```

Expected: collection fails because `app.health` does not exist. If the host
virtual environment is unavailable, run the same command with the development
API image and a repository bind mount; a missing interpreter is not the
expected red state.

- [ ] **Step 3: Implement the shared health infrastructure module**

Create `apps/api/app/health.py` with:

```python
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import SessionLocal


canonical_health_router = APIRouter(prefix="/api/health", tags=["health"])
legacy_health_router = APIRouter(prefix="/health", tags=["health"])


def database_is_ready() -> bool:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


def readiness_response() -> JSONResponse:
    if database_is_ready():
        return JSONResponse(status_code=200, content={"status": "ready"})
    return JSONResponse(status_code=503, content={"status": "not_ready"})


@canonical_health_router.get("/live")
def canonical_liveness():
    return {"status": "alive"}


@canonical_health_router.get("/ready")
def canonical_readiness():
    return readiness_response()


@legacy_health_router.get("")
def legacy_health():
    return {"status": "ok"}


@legacy_health_router.get("/live")
def legacy_liveness():
    return {"status": "ok"}


@legacy_health_router.get("/ready")
def legacy_readiness():
    return readiness_response()
```

In `apps/api/app/main.py`, remove the `APIRouter`, `text`, and `SessionLocal`
health implementation imports and functions. Import the two new routers:

```python
from app.health import canonical_health_router, legacy_health_router
```

Register them before metrics in `create_app()`:

```python
    app.include_router(canonical_health_router)
    app.include_router(legacy_health_router)
    app.include_router(metrics_router)
```

- [ ] **Step 4: Update existing compatibility assertions**

In `apps/api/tests/test_api.py`, make `test_healthcheck` assert the exact safe
legacy body and make the existing combined health test cover both families:

```python
def test_healthcheck() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_liveness_readiness_metrics_and_request_id() -> None:
    request_id = "agent-check-123"
    canonical_live_response = client.get(
        "/api/health/live",
        headers={"X-Request-ID": request_id},
    )
    canonical_ready_response = client.get("/api/health/ready")
    legacy_live_response = client.get("/health/live")
    legacy_ready_response = client.get("/health/ready")
    metrics_response = client.get("/metrics")

    assert canonical_live_response.status_code == 200
    assert canonical_live_response.headers["X-Request-ID"] == request_id
    assert canonical_live_response.json() == {"status": "alive"}
    assert canonical_ready_response.status_code == 200
    assert canonical_ready_response.json() == {"status": "ready"}
    assert canonical_ready_response.headers["X-Request-ID"]
    assert legacy_live_response.json() == {"status": "ok"}
    assert legacy_ready_response.json() == {"status": "ready"}
    assert metrics_response.status_code == 200
    assert metrics_response.headers["content-type"].startswith("text/plain")
```

In `apps/api/tests/compatibility/test_app_factory.py`, make the route loop:

```python
        for path in (
            "/api/health/live",
            "/api/health/ready",
            "/health",
            "/health/live",
            "/health/ready",
            "/metrics",
        ):
            assert client.get(path).status_code == 200
```

Also assert the OpenAPI health tag at the canonical route:

```python
    assert openapi["paths"]["/api/health/live"]["get"]["tags"] == ["health"]
```

In `apps/api/tests/compatibility/test_uvicorn_smoke.py`, request
`/api/health/live` and expect `{"status": "alive"}`.

- [ ] **Step 5: Run focused health and compatibility tests and verify green**

Run:

```bash
.venv/bin/python -m pytest -p no:cacheprovider \
  apps/api/tests/test_health.py \
  apps/api/tests/test_api.py -k 'health or liveness or readiness' -v
.venv/bin/python -m pytest -p no:cacheprovider \
  apps/api/tests/compatibility/test_app_factory.py \
  apps/api/tests/compatibility/test_uvicorn_smoke.py -v
```

Expected: every selected test passes; the failing-session test returns two
safe 503 responses.

- [ ] **Step 6: Run API lint and inspect the health diff**

Run:

```bash
.venv/bin/python -m ruff check apps/api/app/health.py apps/api/app/main.py \
  apps/api/tests/test_health.py apps/api/tests/test_api.py \
  apps/api/tests/compatibility/test_app_factory.py \
  apps/api/tests/compatibility/test_uvicorn_smoke.py
git diff --check
git diff -- apps/api/app/health.py apps/api/app/main.py apps/api/tests
```

Expected: Ruff and whitespace checks pass; no health response includes
configuration or exception content.

- [ ] **Step 7: Commit the health API contract**

```bash
git add apps/api/app/health.py apps/api/app/main.py apps/api/tests/test_health.py \
  apps/api/tests/test_api.py apps/api/tests/compatibility/test_app_factory.py \
  apps/api/tests/compatibility/test_uvicorn_smoke.py
git commit -m "ANY-83 - Add safe liveness and readiness endpoints"
```

---

### Task 2: Gate API startup on a one-shot migration service

**Files:**
- Create: `apps/api/tests/test_deployment_contract.py`
- Modify: `apps/api/Dockerfile:42-59`
- Modify: `docker-compose.yml:8-93`
- Modify: `docker-compose.prod.yml:8-105`
- Verify: `docker-compose.agent.yml`
- Verify: `deploy/caddy/Caddyfile.dev`
- Verify: `deploy/caddy/Caddyfile.prod`

**Interfaces:**
- Consumes: the existing API development/production image targets, validated settings environment, PostgreSQL healthcheck, and Caddy `/api/*` route.
- Produces: a `migrate` service whose successful completion is required by `api`, Uvicorn-only image startup commands, and canonical Docker readiness probes.

- [ ] **Step 1: Write failing deployment contract tests**

Create `apps/api/tests/test_deployment_contract.py` with:

```python
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]


def load_compose(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_migration_service_gates_api_startup(path: str) -> None:
    services = load_compose(path)["services"]
    migrate = services["migrate"]
    api = services["api"]

    assert migrate["restart"] == "no"
    assert migrate["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert migrate["command"] == [
        "python",
        "-m",
        "alembic",
        "-c",
        "apps/api/alembic.ini",
        "upgrade",
        "head",
    ]
    assert migrate["environment"] == api["environment"]
    assert api["depends_on"]["migrate"]["condition"] == "service_completed_successfully"


@pytest.mark.parametrize("path", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_api_healthcheck_uses_canonical_readiness(path: str) -> None:
    api = load_compose(path)["services"]["api"]

    assert "http://localhost:8000/api/health/ready" in " ".join(api["healthcheck"]["test"])


def test_api_image_commands_do_not_run_migrations() -> None:
    dockerfile = (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")
    commands = [line for line in dockerfile.splitlines() if line.startswith("CMD ")]

    assert len(commands) == 2
    assert all("alembic" not in command for command in commands)
    assert all("uvicorn" in command for command in commands)


@pytest.mark.parametrize(
    "path",
    ["deploy/caddy/Caddyfile.dev", "deploy/caddy/Caddyfile.prod"],
)
def test_caddy_proxies_canonical_health_routes(path: str) -> None:
    caddyfile = (ROOT / path).read_text(encoding="utf-8")

    assert "reverse_proxy /api/*" in caddyfile
```

- [ ] **Step 2: Run the deployment contract module and verify the red state**

Run:

```bash
.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_deployment_contract.py -v
```

Expected: migration-service assertions fail because neither Compose file has a
`migrate` service; Dockerfile and healthcheck assertions also fail.

- [ ] **Step 3: Remove Alembic from the API image startup commands**

Replace the development `CMD` in `apps/api/Dockerfile` with:

```dockerfile
CMD ["sh", "-c", "PYTHONPATH=apps/api python -c 'from app.core.settings import settings' && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --app-dir apps/api"]
```

Replace the production `CMD` with:

```dockerfile
CMD ["sh", "-c", "PYTHONPATH=apps/api python -c 'from app.core.settings import settings' && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-*}\" --app-dir apps/api"]
```

- [ ] **Step 4: Add the development migration prerequisite**

In `docker-compose.yml`, extract the current API build, environment, and source
volume into YAML anchors. Add this service before `api`:

```yaml
  migrate:
    build: *api-build
    restart: "no"
    security_opt:
      - no-new-privileges:true
    logging: *default-logging
    depends_on:
      postgres:
        condition: service_healthy
    environment: *api-environment
    command:
      - python
      - -m
      - alembic
      - -c
      - apps/api/alembic.ini
      - upgrade
      - head
    volumes: *api-volumes
    networks:
      - backend
```

Use the same anchors in `api`, and replace its direct PostgreSQL prerequisite
with:

```yaml
    depends_on:
      migrate:
        condition: service_completed_successfully
```

Change the development API healthcheck URL to
`http://localhost:8000/api/health/ready`.

- [ ] **Step 5: Add the production migration prerequisite**

In `docker-compose.prod.yml`, extract the production API build and current API
environment into YAML anchors. Add this service before `api`:

```yaml
  migrate:
    build: *api-build
    restart: "no"
    security_opt:
      - no-new-privileges:true
    logging: *default-logging
    depends_on:
      postgres:
        condition: service_healthy
    environment: *api-environment
    command:
      - python
      - -m
      - alembic
      - -c
      - apps/api/alembic.ini
      - upgrade
      - head
    networks:
      - backend
```

Use the same anchors in `api`, replace its direct PostgreSQL prerequisite with
the successful migration condition, and change its healthcheck URL to
`http://localhost:8000/api/health/ready`.

- [ ] **Step 6: Update the agent override healthcheck**

In `docker-compose.agent.yml`, change the API healthcheck URL to:

```text
http://localhost:8000/api/health/ready
```

Keep its PostgreSQL and observability dependencies; Compose mapping merge must
also retain the base file's successful migration prerequisite.

- [ ] **Step 7: Run static tests and render both Compose models**

Run:

```bash
.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_deployment_contract.py -v
docker compose -f docker-compose.yml config --format json
POSTGRES_DB=compose_contract POSTGRES_USER=compose_contract \
POSTGRES_PASSWORD=compose-contract-only CLOUDPAYMENTS_ENABLED=false \
CORS_ALLOW_ORIGINS=https://payments.example.test \
APP_PUBLIC_BASE_URL=https://payments.example.test \
NEXT_PUBLIC_API_BASE_URL=https://payments.example.test \
CADDY_DOMAIN=payments.example.test \
docker compose -f docker-compose.prod.yml config --format json
git diff --check
```

Expected: deployment tests pass; both Compose commands return valid JSON. The
development model has `api.depends_on.migrate.condition` equal to
`service_completed_successfully`. The production render uses only the explicit
non-secret contract-test values shown above and does not write an env file.

- [ ] **Step 8: Prove the merged agent model retains the migration gate**

Run the harness-equivalent config command with local-only contract ports:

```bash
WEB_PORT=39000 GRAFANA_PORT=39001 LOKI_PORT=39002 \
PROMETHEUS_PORT=39003 TEMPO_PORT=39004 \
OTLP_GRPC_PORT=39005 OTLP_HTTP_PORT=39006 \
docker compose --project-name payments-any83-contract \
  --env-file .env.example \
  -f docker-compose.yml \
  -f docker-compose.agent.yml \
  config --format json
```

Expected: the rendered `api.depends_on` contains `migrate` with
`service_completed_successfully`, `postgres` with `service_healthy`, and
`observability` with `service_started`.

- [ ] **Step 9: Commit the deployment lifecycle**

```bash
git add apps/api/Dockerfile apps/api/tests/test_deployment_contract.py \
  docker-compose.yml docker-compose.prod.yml docker-compose.agent.yml
git commit -m "ANY-83 - Gate API startup on migrations"
```

---

### Task 3: Update deployment documentation and generated API contract

**Files:**
- Modify: `README.md:79-123`
- Modify: `docs/architecture/deployment.md:1-28`
- Generate: `docs/generated/openapi.json`
- Modify: `apps/api/tests/compatibility/test_app_factory.py`

**Interfaces:**
- Consumes: the implemented health routers, one-shot migration lifecycle, repository generator, and existing documentation authority hierarchy.
- Produces: current operational documentation and a generated OpenAPI artifact containing both canonical and compatibility health paths.

- [ ] **Step 1: Add the generated-contract assertions before regeneration**

Extend `test_app_factory_builds_independent_apps_with_stable_routes` with:

```python
    assert {
        "/api/health/live",
        "/api/health/ready",
        "/health",
        "/health/live",
        "/health/ready",
    } <= set(openapi["paths"])
```

Run:

```bash
python3 scripts/repo.py generate --check
```

Expected: the generator reports that `docs/generated/openapi.json` is stale
because the canonical health paths are absent from the checked-in artifact.

- [ ] **Step 2: Document the local and production lifecycle**

Update `README.md` so it states:

```markdown
Compose runs Alembic in a one-shot `migrate` service after PostgreSQL becomes
healthy. The API starts only after that service completes successfully; the API
container command never applies migrations itself.

Canonical health endpoints are `/api/health/live` for process liveness and
`/api/health/ready` for PostgreSQL-backed readiness. Docker and external
monitoring use readiness. The legacy `/health`, `/health/live`, and
`/health/ready` routes remain available during the compatibility period.
```

Replace every statement that says the API container applies migrations during
startup with the one-shot service contract.

- [ ] **Step 3: Update the authoritative deployment architecture**

Update `docs/architecture/deployment.md` to show this flow:

```mermaid
flowchart LR
  Browser["Browser"] --> Caddy["Caddy"]
  Caddy --> Web["Next.js web container"]
  Caddy --> API["FastAPI API container"]
  DB[("PostgreSQL 18")] -->|"healthy"| Migrate["One-shot Alembic service"]
  Migrate -->|"completed successfully"| API
  API --> DB
  Browser --> CP["CloudPayments widget"]
  CP -->|"HTTPS webhook"| API
  API --> OTEL["Optional telemetry backend"]
```

Describe canonical liveness/readiness, the safe readiness 503 response, legacy
route compatibility, and the existing Caddy `/api/*` path used by HetrixTools.

- [ ] **Step 4: Regenerate artifacts through the repository generator**

Run:

```bash
npm run generate
```

Expected: `docs/generated/openapi.json` contains the two canonical health paths
and preserves the three legacy paths. If npm is unavailable, run the same
checked-in generator entrypoint in the API development image and record that
environment substitution:

```bash
docker compose run --rm --no-deps \
  --volume "$PWD:/workspace" --workdir /workspace \
  migrate python scripts/repo.py generate
```

- [ ] **Step 5: Run documentation, generator, and OpenAPI checks**

Run:

```bash
python3 scripts/repo.py docs check
python3 scripts/repo.py generate --check
.venv/bin/python -m pytest -p no:cacheprovider \
  apps/api/tests/compatibility/test_app_factory.py -v
git diff --check
```

Expected: documentation and generator checks pass, the app-factory test passes,
and no generated file other than the OpenAPI artifact changes.

- [ ] **Step 6: Commit documentation and generated contracts**

```bash
git add README.md docs/architecture/deployment.md docs/generated/openapi.json \
  apps/api/tests/compatibility/test_app_factory.py
git commit -m "ANY-83 - Document migration and health operations"
```

---

### Task 4: Verify migration gating and complete delivery evidence

**Files:**
- Create: `docs/exec-plans/active/ANY-83-migrations-health-checks.md`
- Modify: `docs/superpowers/plans/2026-08-17-any-83-migrations-health-checks.md`
- Verify: all files changed by Tasks 1-3

**Interfaces:**
- Consumes: the final Compose stack, canonical and legacy health routes, repository checks, and Linear issue URL.
- Produces: positive and negative migration lifecycle evidence, focused and canonical test evidence, and a clean local `ANY-83` branch ready for human review.

- [ ] **Step 1: Run the complete backend and architecture checks**

Run:

```bash
.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests -v
python3 scripts/repo.py architecture check
python3 scripts/repo.py docs check
python3 scripts/repo.py generate --check
git diff --check
```

Expected: backend, architecture, documentation, generated-artifact, and
whitespace checks pass. PostgreSQL-marked tests must use the dedicated test
database and never the application database.

- [ ] **Step 2: Start the real development stack and inspect ordering**

Run:

```bash
python3 scripts/repo.py up
docker compose --project-name "$(python3 -c 'import json; print(json.load(open(".harness/runtime.json"))["compose_project"])')" \
  --env-file .harness/runtime.env \
  -f docker-compose.yml \
  -f docker-compose.agent.yml \
  ps -a
```

Expected: `migrate` is `Exited (0)` before API is healthy; PostgreSQL, API,
web, Caddy, and observability are running without restart loops.

- [ ] **Step 3: Exercise direct and Caddy health contracts**

Read ports from `.harness/runtime.json` and request:

```text
direct API  /api/health/live   -> 200 {"status":"alive"}
direct API  /api/health/ready  -> 200 {"status":"ready"}
direct API  /health            -> 200 {"status":"ok"}
direct API  /health/live       -> 200 {"status":"ok"}
direct API  /health/ready      -> 200 {"status":"ready"}
Caddy       /api/health/live   -> 200 {"status":"alive"}
Caddy       /api/health/ready  -> 200 {"status":"ready"}
```

Expected: every body is exact and every response has `X-Request-ID`; no body
contains application configuration or database details.

- [ ] **Step 4: Prove a failed migration blocks API startup**

Create an ignored temporary Compose override in `.harness/tmp` that changes the
migration command and removes conflicting host port publications:

```yaml
services:
  postgres:
    ports: !reset []
  migrate:
    command: ["sh", "-c", "exit 42"]
  api:
    ports: !reset []
```

Start only `api` and its dependencies under the explicit project name
`payments-any83-negative`:

```bash
docker compose --project-name payments-any83-negative \
  --env-file .env.example \
  -f docker-compose.yml \
  -f .harness/tmp/any83-failing-migration.yml \
  up --build api
docker compose --project-name payments-any83-negative \
  --env-file .env.example \
  -f docker-compose.yml \
  -f .harness/tmp/any83-failing-migration.yml \
  ps -a
```

Expected: Compose exits non-zero because `migrate` exits 42; `api` remains in
the created/not-started state or is absent, never running and never serving
liveness. After recording `ps -a` and the exit status, tear down only the
explicit `payments-any83-negative` project and its project-scoped volumes:

```bash
docker compose --project-name payments-any83-negative \
  --env-file .env.example \
  -f docker-compose.yml \
  -f .harness/tmp/any83-failing-migration.yml \
  down --volumes --remove-orphans
```

- [ ] **Step 5: Inspect logs for unexpected runtime behavior**

Inspect migration, API, PostgreSQL, and Caddy logs from the successful stack.

Expected: one successful Alembic run, no Alembic invocation in API logs, no
traceback for successful probes, and no secret, authorization header,
connection string, raw token, or payment field in captured output.

- [ ] **Step 6: Run the broadest supported canonical check**

Run:

```bash
npm run check
```

Expected: the canonical check passes. If host Node/npm remains unavailable, run
all API, Compose, documentation, generation, web build, and security checks
supported by repository containers and record `npm run check` as skipped for
that exact environment reason.

- [ ] **Step 7: Write the execution evidence record**

Create `docs/exec-plans/active/ANY-83-migrations-health-checks.md` in English.
Record the Linear URL, implemented scope, commit IDs, exact commands and
observed pass counts, positive service ordering, negative migration exit code,
direct/Caddy response bodies, log inspection, canonical-check result, and every
skipped check with its reason. Do not include credentials, environment values,
connection strings, raw logs containing secrets, or invented results.

- [ ] **Step 8: Review the final diff and mark this plan complete**

Run:

```bash
git status --short
git diff main...HEAD --stat
git diff main...HEAD --check
git log --oneline main..HEAD
```

Inspect every changed file for unrelated edits, generated-file hand edits,
secrets, migration changes, payment/legal behavior changes, and accidental
route removal. Change every completed checkbox in this plan from `[ ]` to
`[x]` only after its evidence exists.

- [ ] **Step 9: Commit final evidence**

```bash
git add docs/exec-plans/active/ANY-83-migrations-health-checks.md \
  docs/superpowers/plans/2026-08-17-any-83-migrations-health-checks.md
git commit -m "ANY-83 - Record migration health-check evidence"
```

- [ ] **Step 10: Prepare the human-review handoff**

Report the local branch, commit list, test and runtime evidence, skipped checks,
and Linear URL. Use PR title `ANY-83 - Separate migrations and add health
checks` if the user later requests publication. Do not push, open a PR, update
Linear state, or merge without a separate user request.
