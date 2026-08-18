# ANY-83 Canonical Health Routes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the undeployed `/health*` compatibility surface, keep distinct canonical liveness and readiness endpoints, and address the remaining PR review assertion.

**Architecture:** FastAPI exposes one health router at `/api/health`. Liveness remains process-only, while readiness owns the short PostgreSQL probe and safe 503 translation. Compose, CI, Caddy, and repository verification consume the canonical routes; no redirect or alias layer remains.

**Tech Stack:** Python 3.12, FastAPI 0.141.1, SQLAlchemy 2.0.51, pytest 9.1.1, Ruff 0.15.22, Docker Compose, Caddy, repository OpenAPI generator

## Global Constraints

- `GET /api/health/live` returns HTTP 200 with exactly `{"status":"alive"}` and never accesses PostgreSQL.
- `GET /api/health/ready` returns exactly `{"status":"ready"}` on success and HTTP 503 with exactly `{"status":"not_ready"}` for SQLAlchemy database failures.
- `/health`, `/health/live`, and `/health/ready` are removed rather than redirected; they return HTTP 404 and are absent from OpenAPI.
- Kubernetes-compatible liveness and readiness semantics stay separate.
- Docker Compose and CI continue to use `/api/health/ready`; Caddy continues to expose both canonical endpoints through `/api/*`.
- Do not hand-edit `docs/generated/openapi.json`; run the checked-in generator.
- Engineering artifacts remain in English.
- Do not reply to or resolve GitHub review threads without explicit user authorization.

---

### Task 1: Make the FastAPI health surface canonical-only

**Files:**
- Modify: `apps/api/app/health.py`
- Modify: `apps/api/app/main.py`
- Modify: `apps/api/tests/test_health.py`
- Modify: `apps/api/tests/test_api.py`
- Modify: `apps/api/tests/compatibility/test_app_factory.py`

**Interfaces:**
- Consumes: `app.core.database.SessionLocal`, SQLAlchemy `text` and `SQLAlchemyError`, FastAPI `APIRouter` and `JSONResponse`.
- Produces: `health_router`, `database_is_ready() -> bool`, and `readiness_response() -> JSONResponse` from `app.health`; only `/api/health/live` and `/api/health/ready` are public.

- [ ] **Step 1: Write failing canonical-only route tests**

In `apps/api/tests/test_health.py`, retain the exact canonical payload tests, make the database-independence checks canonical-only, and add the removal contract:

```python
@pytest.mark.parametrize("path", ["/health", "/health/live", "/health/ready"])
def test_legacy_health_routes_are_not_registered(path: str) -> None:
    assert client.get(path).status_code == 404
```

Change the readiness failure loop to request only `/api/health/ready` and retain the safe-body assertions.

In `apps/api/tests/test_api.py`, delete `test_healthcheck`, remove legacy requests from `test_liveness_readiness_metrics_and_request_id`, and make `test_invalid_request_id_is_replaced` request `/api/health/live`.

In `apps/api/tests/compatibility/test_app_factory.py`, request only the canonical routes and metrics, assert both canonical OpenAPI tags, and assert the older paths are absent:

```python
assert openapi["paths"]["/api/health/live"]["get"]["tags"] == ["health"]
assert openapi["paths"]["/api/health/ready"]["get"]["tags"] == ["health"]
assert {"/health", "/health/live", "/health/ready"}.isdisjoint(openapi["paths"])
```

This readiness tag assertion directly addresses unresolved review thread `PRRT_kwDOTIm_Wc6Z_py1`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
docker run --rm \
  -v "$PWD:/workspace" -w /workspace -e PYTHONPATH=apps/api \
  payments-portal-dev-migrate:latest \
  python -m pytest -p no:cacheprovider \
  apps/api/tests/test_health.py \
  apps/api/tests/test_api.py \
  apps/api/tests/compatibility/test_app_factory.py -q
```

Expected: FAIL because the three `/health*` routes still return HTTP 200 and still appear in OpenAPI. Canonical contract assertions remain green.

- [ ] **Step 3: Remove the compatibility router**

In `apps/api/app/health.py`, rename `canonical_health_router` to `health_router`, keep its `/api/health` prefix and both route functions, and delete `legacy_health_router`, `legacy_health`, `legacy_liveness`, and `legacy_readiness`:

```python
health_router = APIRouter(prefix="/api/health", tags=["health"])


@health_router.get("/live")
def liveness():
    return {"status": "alive"}


@health_router.get("/ready")
def readiness():
    return readiness_response()
```

In `apps/api/app/main.py`, import only `health_router` and include it once:

```python
from app.health import health_router

# inside create_app()
app.include_router(health_router)
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command again.

Expected: all selected tests pass; `/health*` return 404; canonical response bodies, readiness failure handling, request IDs, route tags, metrics, app-factory isolation, and lifespan behavior remain covered.

- [ ] **Step 5: Run Python lint and formatting checks**

Run:

```bash
docker run --rm -v "$PWD:/workspace" -w /workspace \
  payments-portal-dev-migrate:latest \
  python -m ruff check apps/api/app/health.py apps/api/app/main.py \
  apps/api/tests/test_health.py apps/api/tests/test_api.py \
  apps/api/tests/compatibility/test_app_factory.py

docker run --rm -v "$PWD:/workspace" -w /workspace \
  payments-portal-dev-migrate:latest \
  python -m ruff format --check apps/api/app/health.py apps/api/app/main.py \
  apps/api/tests/test_health.py apps/api/tests/test_api.py \
  apps/api/tests/compatibility/test_app_factory.py
```

Expected: both commands exit 0.

- [ ] **Step 6: Commit the canonical API contract**

```bash
git add apps/api/app/health.py apps/api/app/main.py \
  apps/api/tests/test_health.py apps/api/tests/test_api.py \
  apps/api/tests/compatibility/test_app_factory.py
git commit -m "ANY-83 - Remove legacy health routes"
```

---

### Task 2: Move repository consumers and contracts to canonical health

**Files:**
- Modify: `security/trivy/verify-api-runtime.sh`
- Modify: `README.md`
- Modify: `docs/architecture/deployment.md`
- Modify: `docs/exec-plans/active/ANY-83-migrations-health-checks.md`
- Modify: `docs/superpowers/plans/2026-08-17-any-83-migrations-health-checks.md`
- Generate: `docs/generated/openapi.json`

**Interfaces:**
- Consumes: production API image exposing `GET /api/health/live -> {"status":"alive"}` and the checked-in repository generator.
- Produces: a runtime verifier, current operational documentation, and generated OpenAPI containing only the two canonical health paths.

- [ ] **Step 1: Prove the old runtime verifier fails against the canonical-only API**

Build a fresh production image after Task 1 and run the unchanged verifier:

```bash
docker build --target production -t payments-any83-health-review \
  -f apps/api/Dockerfile .
security/trivy/verify-api-runtime.sh payments-any83-health-review
```

Expected: FAIL because the verifier requests removed `/health/live` or expects `{"status":"ok"}`.

- [ ] **Step 2: Update the runtime verifier**

In `security/trivy/verify-api-runtime.sh`, request the canonical path and exact payload:

```sh
"http://${endpoint}/api/health/live"
```

```sh
if [ "$response" != '{"status":"alive"}' ]; then
```

- [ ] **Step 3: Re-run the runtime verifier and verify GREEN**

Run:

```bash
security/trivy/verify-api-runtime.sh payments-any83-health-review
```

Expected: `Verified patched, non-root API production image liveness.`

- [ ] **Step 4: Update current documentation and supersede the old compatibility plan**

In `README.md` and `docs/architecture/deployment.md`, remove claims that `/health*` remain available and state that `/api/health/live` and `/api/health/ready` are the complete supported health surface.

In `docs/exec-plans/active/ANY-83-migrations-health-checks.md`, record the reviewed decision, the repository usage audit, the route removals, the runtime-verifier migration, and updated evidence.

At the top of `docs/superpowers/plans/2026-08-17-any-83-migrations-health-checks.md`, add:

```markdown
> Review amendment: the compatibility-route steps in this completed plan are
> superseded by `2026-08-18-any-83-canonical-health-routes.md`.
```

Do not rewrite the checked historical steps in the older plan.

- [ ] **Step 5: Regenerate and verify OpenAPI**

Run the checked-in generator in the API development image when host npm is unavailable:

```bash
docker run --rm -v "$PWD:/workspace" -w /workspace \
  -e PYTHONPATH=apps/api payments-portal-dev-migrate:latest \
  python scripts/repo.py generate

docker run --rm -v "$PWD:/workspace" -w /workspace \
  -e PYTHONPATH=apps/api payments-portal-dev-migrate:latest \
  python scripts/repo.py generate --check
```

Expected: `docs/generated/openapi.json` contains `/api/health/live` and `/api/health/ready`, contains neither `/health` nor its child paths, and the check exits 0.

- [ ] **Step 6: Run documentation and focused contract checks**

Run:

```bash
python3 scripts/repo.py docs check
python3 scripts/repo.py architecture check
docker run --rm -v "$PWD:/workspace" -w /workspace -e PYTHONPATH=apps/api \
  payments-portal-dev-migrate:latest \
  python -m pytest -p no:cacheprovider \
  apps/api/tests/compatibility/test_app_factory.py \
  apps/api/tests/test_deployment_contract.py -q
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 7: Commit repository consumers and documentation**

```bash
git add security/trivy/verify-api-runtime.sh README.md \
  docs/architecture/deployment.md \
  docs/exec-plans/active/ANY-83-migrations-health-checks.md \
  docs/superpowers/plans/2026-08-17-any-83-migrations-health-checks.md \
  docs/generated/openapi.json
git commit -m "ANY-83 - Document canonical health routes"
```

---

### Task 3: Verify the review amendment and update PR #52

**Files:**
- Verify: all files changed since `main`
- Update: `docs/exec-plans/active/ANY-83-migrations-health-checks.md` only if final evidence differs from Task 2

**Interfaces:**
- Consumes: canonical-only API, production image, Compose migration lifecycle, PR #52, and unresolved thread `PRRT_kwDOTIm_Wc6Z_py1`.
- Produces: clean branch evidence and pushed commits for human review; the GitHub thread remains unresolved unless the user separately authorizes a reply or resolution.

- [ ] **Step 1: Run the complete API suite against PostgreSQL**

Start the repository PostgreSQL service and apply migrations:

```bash
docker compose up -d --wait postgres
docker compose run --rm migrate
```

Run all API tests with the repository root available:

```bash
docker run --rm --network payments-portal-dev_backend \
  -v "$PWD:/workspace" -w /workspace -e PYTHONPATH=apps/api \
  -e TEST_POSTGRES_DATABASE_URL=postgresql+psycopg://anytoolai:anytoolai@postgres:5432/anytoolai_tests \
  payments-portal-dev-migrate:latest \
  python -m pytest -p no:cacheprovider apps/api/tests -q --disable-warnings
```

Expected: all non-PostgreSQL and PostgreSQL tests pass; no unexpected skip or failure is introduced.

- [ ] **Step 2: Run full API lint, format, docs, architecture, and generator checks**

Run:

```bash
docker run --rm -v "$PWD:/workspace" -w /workspace \
  payments-portal-dev-migrate:latest python -m ruff check apps/api
docker run --rm -v "$PWD:/workspace" -w /workspace \
  payments-portal-dev-migrate:latest python -m ruff format --check apps/api
python3 scripts/repo.py docs check
python3 scripts/repo.py architecture check
docker run --rm -v "$PWD:/workspace" -w /workspace \
  -e PYTHONPATH=apps/api payments-portal-dev-migrate:latest \
  python scripts/repo.py generate --check
```

Expected: every command exits 0.

- [ ] **Step 3: Verify production and Compose health behavior**

Build and run the production runtime verifier:

```bash
docker build --target production -t payments-any83-health-review \
  -f apps/api/Dockerfile .
security/trivy/verify-api-runtime.sh payments-any83-health-review
```

Start the Compose stack with repository-scoped ports and verify:

```text
direct API  /api/health/live   -> 200 {"status":"alive"}
direct API  /api/health/ready  -> 200 {"status":"ready"}
direct API  /health            -> 404
direct API  /health/live       -> 404
direct API  /health/ready      -> 404
Caddy       /api/health/live   -> 200 {"status":"alive"}
Caddy       /api/health/ready  -> 200 {"status":"ready"}
```

Stop the temporary stack with `docker compose down` and do not pass `--volumes`.

- [ ] **Step 4: Inspect the final diff and branch state**

Run:

```bash
git diff --check
git diff --stat main...HEAD
git status -sb
rg -n --hidden --glob '!.git/**' '/health' \
  apps/api security/trivy README.md docs/architecture \
  docs/exec-plans/active/ANY-83-migrations-health-checks.md
```

Expected: remaining `/health` matches describe removed paths or canonical `/api/health`; the worktree is clean after any evidence commit.

- [ ] **Step 5: Push the reviewed implementation**

```bash
git push origin ANY-83
gh pr checks 52 --repo gushinets/payments-portal
```

Expected: PR #52 points at the final `ANY-83` commit and a new CI run starts. Do not reply to or resolve the review thread without separate user authorization.
