# ANY-313 Web Runtime Image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-stage web image with a minimal non-root Next.js standalone runtime that excludes development and package-manager tooling without changing public checkout or payment behavior.

**Architecture:** Build the npm workspace in named dependency and builder stages, with repository-root Next.js output tracing. Copy only the traced server, static assets, and public files into the pinned Node Alpine runtime, remove unused bundled package managers, and start the generated workspace server directly with Node.

**Tech Stack:** Docker BuildKit, Node.js 24.18.0 Alpine 3.24, npm 11, Next.js 16.3.1 standalone output, Node test runner, Playwright, Trivy 0.72.0

## Global Constraints

- Keep v1 scoped to the RU CloudPayments MVP.
- Preserve the pinned `node:24.18.0-alpine3.24` multi-architecture digest.
- Preserve `NEXT_PUBLIC_API_BASE_URL` as a build argument and runtime environment variable; browser-visible changes still require rebuilding the image.
- Keep the web service on port 3000 and run it as the non-root `node` user.
- Do not copy the builder workspace `node_modules`, source tree, tests, or package-manager state into the runtime stage.
- Do not change checkout, payment, authentication, API, or legal content behavior.
- Do not add a Trivy exception unless a fresh scan proves it is necessary and the entry includes ID, affected path, actionable reason, and expiry.
- Do not perform React 19, ESLint 10, TypeScript major, or GHCR publishing work.

---

### Task 1: Characterize the production-image contract

**Files:**
- Create: `security/trivy/verify-web-runtime.sh`
- Modify: `.github/workflows/security.yml`

**Interfaces:**
- Consumes: a locally available Docker image reference as its sole positional argument.
- Produces: an executable behavioral gate for the configured user and command, Node version, package-manager removal, and absence of known build/test modules.

- [x] **Step 1: Add the executable image-contract verifier**

Create executable `security/trivy/verify-web-runtime.sh` with this content:

```sh
#!/usr/bin/env sh
set -eu

image_ref=${1:?Usage: verify-web-runtime.sh IMAGE}
expected_command='["node","apps/web/server.js"]'

configured_user=$(docker image inspect --format '{{.Config.User}}' "$image_ref")
configured_command=$(docker image inspect --format '{{json .Config.Cmd}}' "$image_ref")

if [ "$configured_user" != "node" ]; then
  echo "Expected runtime user node, got: $configured_user" >&2
  exit 1
fi

if [ "$configured_command" != "$expected_command" ]; then
  echo "Expected runtime command $expected_command, got: $configured_command" >&2
  exit 1
fi

docker run --rm --entrypoint sh "$image_ref" -ec '
  test "$(id -u)" -ne 0
  test "$(node --version)" = "v24.18.0"

  for path in \
    /usr/local/bin/corepack \
    /usr/local/bin/npm \
    /usr/local/bin/npx \
    /usr/local/lib/node_modules/corepack \
    /usr/local/lib/node_modules/npm \
    /app/node_modules/vitest \
    /app/node_modules/vite \
    /app/node_modules/@vitejs \
    /app/node_modules/@vitest \
    /app/node_modules/esbuild \
    /app/apps/web/node_modules/vitest \
    /app/apps/web/node_modules/vite \
    /app/apps/web/node_modules/@vitejs \
    /app/apps/web/node_modules/@vitest \
    /app/apps/web/node_modules/esbuild
  do
    if [ -e "$path" ] || [ -L "$path" ]; then
      echo "Unexpected runtime path: $path" >&2
      exit 1
    fi
  done
'
```

- [x] **Step 2: Make the verifier executable**

Run:

```bash
chmod +x security/trivy/verify-web-runtime.sh
```

- [x] **Step 3: Wire the behavioral gate into Security scans**

Add this step immediately after `Build production web image` in `.github/workflows/security.yml`:

```yaml
      - name: Verify production web runtime
        run: security/trivy/verify-web-runtime.sh "$WEB_IMAGE"
```

- [x] **Step 4: Run the verifier against the measured baseline and verify the red state**

Run:

```bash
security/trivy/verify-web-runtime.sh payment-portal-web:any-313-baseline
```

Expected: non-zero exit with the exact command mismatch: the baseline uses workspace `npm start` instead of `["node","apps/web/server.js"]`. This proves the behavioral gate rejects the pre-change production image.

### Task 2: Build the standalone runtime image

**Files:**
- Modify: `apps/web/next.config.mjs`
- Modify: `apps/web/Dockerfile`
- Modify: `README.md`
- Test: `security/trivy/verify-web-runtime.sh`

**Interfaces:**
- Consumes: the locked root npm workspace, `docs/legal` build input, `NEXT_PUBLIC_API_BASE_URL`, and Task 1's contract.
- Produces: `/app/apps/web/server.js`, `/app/apps/web/.next/static`, and `/app/apps/web/public` in a non-root runtime image listening on port 3000.

- [x] **Step 1: Enable repository-root standalone tracing**

Update `apps/web/next.config.mjs` to define the repository root and add the two output properties without changing `allowedDevOrigins`:

```js
import { fileURLToPath } from "node:url";

const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));

const allowedDevOrigins = (
  process.env.NEXT_ALLOWED_DEV_ORIGINS ?? "192.168.1.102"
)
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean)
  .map((origin) => origin.replace(/^https?:\/\//, "").replace(/:\d+$/, ""));

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins,
  output: "standalone",
  outputFileTracingRoot: repositoryRoot
};

export default nextConfig;
```

- [x] **Step 2: Replace the single-stage Dockerfile**

Use this exact three-stage layout in `apps/web/Dockerfile`:

```dockerfile
FROM node:24.18.0-alpine3.24@sha256:a0b9bf06e4e6193cf7a0f58816cc935ff8c2a908f81e6f1a95432d679c54fbfd AS dependencies

WORKDIR /app

COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json

RUN npm ci

FROM dependencies AS builder

ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_TELEMETRY_DISABLED=1

COPY apps/web ./apps/web
COPY docs/legal ./docs/legal

RUN npm run build:web

FROM node:24.18.0-alpine3.24@sha256:a0b9bf06e4e6193cf7a0f58816cc935ff8c2a908f81e6f1a95432d679c54fbfd AS runtime

WORKDIR /app

ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

ENV HOSTNAME=0.0.0.0
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production
ENV PORT=3000

RUN rm -rf \
    /usr/local/bin/corepack \
    /usr/local/bin/npm \
    /usr/local/bin/npx \
    /usr/local/lib/node_modules/corepack \
    /usr/local/lib/node_modules/npm

COPY --from=builder --chown=node:node /app/apps/web/.next/standalone ./
COPY --from=builder --chown=node:node /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=node:node /app/apps/web/public ./apps/web/public

USER node

EXPOSE 3000

CMD ["node", "apps/web/server.js"]
```

- [x] **Step 3: Document the compatible command replacement**

Add this paragraph after the web image bullet in `README.md`'s `Runtime baseline` section:

```markdown
  The production web image uses Next.js standalone output and starts the traced
  workspace server directly with `node apps/web/server.js`; npm and other build
  tooling are not part of the runtime image.
```

- [x] **Step 4: Build both targets and verify the green runtime contract**

Run:

```bash
docker build --target builder --file apps/web/Dockerfile --tag payment-portal-web:any-313-builder .
docker build --file apps/web/Dockerfile --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.any-313.example --tag payment-portal-web:any-313 .
security/trivy/verify-web-runtime.sh payment-portal-web:any-313
```

Expected: both images build and the verifier exits 0. The builder log shows `next build` emitting standalone output; the runtime copies `apps/web/server.js`, uses the direct Node command, and contains none of the prohibited paths.

- [x] **Step 5: Run the existing web source-contract suite**

Run:

```bash
npm run test:boundaries:web
```

Expected: all existing `apps/web/tests/*.test.mjs` tests pass.

- [x] **Step 6: Commit the coherent implementation**

```bash
git add security/trivy/verify-web-runtime.sh .github/workflows/security.yml apps/web/next.config.mjs apps/web/Dockerfile README.md
git commit -m "ANY-313 - Minimize web runtime image"
```

### Task 3: Verify runtime contents and public behavior

**Files:**
- Modify: `docs/exec-plans/active/ANY-313-web-runtime-image.md`
- Verify: `.github/workflows/security.yml`
- Verify: `apps/web/e2e/checkout-webhook.spec.ts`
- Verify: `apps/web/e2e/payment-result-refund.spec.ts`

**Interfaces:**
- Consumes: the `payment-portal-web:any-313` image from Task 2 and the existing Trivy, Compose, and Playwright harnesses.
- Produces: exact handoff evidence for image size, user/command, runtime contents, Trivy policy, web checks, and unchanged critical journeys.

- [x] **Step 1: Inspect the final image metadata**

Run:

```bash
docker image inspect payment-portal-web:any-313 --format '{{json .Config.User}} {{json .Config.Cmd}} {{.Size}}'
```

Expected: user is `node`, command is `["node","apps/web/server.js"]`, and size is materially below the 340,201,948-byte baseline.

- [x] **Step 2: Prove build and test tooling is absent**

Run a shell in the final image and assert all of these paths are absent:

```text
/usr/local/bin/corepack
/usr/local/bin/npm
/usr/local/bin/npx
/usr/local/lib/node_modules/corepack
/usr/local/lib/node_modules/npm
/app/node_modules/vitest
/app/node_modules/vite
/app/node_modules/@vitejs
/app/node_modules/@vitest
/app/node_modules/esbuild
/app/apps/web/node_modules/vitest
/app/apps/web/node_modules/vite
/app/apps/web/node_modules/@vitejs
/app/apps/web/node_modules/@vitest
/app/apps/web/node_modules/esbuild
```

Expected: the check exits 0 and `node --version` still reports Node 24.18.0.

- [x] **Step 3: Smoke the standalone server and build argument**

Start `payment-portal-web:any-313` on an unused loopback port, wait for readiness, and request `/ru/auth-checkout?product=document-summary`. Search `.next/static` inside the image for `https://api.any-313.example`, then stop the disposable container.

Expected: HTTP 200, Russian checkout markup, no root process, and the non-default public API origin appears in the browser bundle.

- [x] **Step 4: Run focused web checks inside the builder image**

Run these commands in `payment-portal-web:any-313-builder`:

```bash
npm run lint:web
npm run typecheck:web
npm run test:boundaries:web
npm --workspace @anytoolai/web run test:components
npm run build:web
```

Expected: every command passes. The second `build:web` confirms the source tree remains independently buildable outside the final runtime stage.

- [x] **Step 5: Run the Trivy 0.72.0 image policy**

Run the same image scan shape used by `.github/workflows/security.yml`:

```bash
trivy image --config trivy.yaml --scanners vuln,secret --format json --output .harness/trivy-any313/web-image.json --ignorefile .trivyignore.yaml payment-portal-web:any-313
python3 scripts/repo.py trivy redact .harness/trivy-any313
python3 -c 'from pathlib import Path; from scripts.repo import summarize_trivy_report; summary = summarize_trivy_report(Path(".harness/trivy-any313/web-image.json")); print(summary); assert summary.blocking_findings == 0'
```

Expected: 0 Critical vulnerabilities and 0 fixable High vulnerabilities. No Vitest, Vite, esbuild, npm, Corepack, tar, or Undici finding originates from removed build/package-manager paths. If Trivy or its database cannot run locally, record the exact environmental limitation and rely on the unchanged `Security scans` workflow for the remaining image scan.

- [x] **Step 6: Run the critical Playwright smoke**

Use the isolated repository stack, then run:

```bash
PLAYWRIGHT_PROVIDER_UI_STUB=true npm exec playwright test -- --config playwright.config.ts apps/web/e2e/checkout-webhook.spec.ts apps/web/e2e/payment-result-refund.spec.ts --project desktop-chromium --workers=1
```

Expected: checkout, verified-webhook payment status, return-page polling, and refund scenarios pass without unexpected browser console errors, failed application requests, or error spans. Stop the isolated stack after collecting evidence.

- [x] **Step 7: Run the broadest supported repository checks**

Run:

```bash
npm run check:fast
npm run check
```

Expected: both commands pass. Record any environment-dependent skip or failure verbatim rather than claiming it passed.

- [x] **Step 8: Review scope and record completion evidence**

Run:

```bash
git diff main...HEAD --check
git diff main...HEAD -- apps/web/Dockerfile apps/web/next.config.mjs security/trivy/verify-web-runtime.sh README.md .github/workflows/security.yml
git status --short
```

Append a `Completion Evidence` section to this plan with the exact command results, image size delta, runtime user/command, package absence result, Trivy summary, browser result, canonical check result, and any local limitation. Confirm that `.github/workflows/security.yml` still builds the default final web image.

- [x] **Step 9: Commit the evidence**

```bash
git add docs/exec-plans/active/ANY-313-web-runtime-image.md
git commit -m "ANY-313 - Record web runtime image evidence"
```

## Completion Evidence

Collected on 2026-08-17 from the isolated
`nikitapotapovit/any-313-razdelit-web-dockerfile-na-builderruntime-i-ubrat-dev`
worktree.

- Contract red state: `security/trivy/verify-web-runtime.sh
  payment-portal-web:any-313-baseline` exited non-zero with `Expected runtime
  command ["node","apps/web/server.js"]`; the baseline command was the npm
  workspace start command.
- Final metadata: `payment-portal-web:any-313` reports user `node`, command
  `["node","apps/web/server.js"]`, and size `70,985,534` bytes. The measured
  baseline was `340,201,948` bytes, so the runtime is `269,216,414` bytes
  smaller (`79.1%`).
- Runtime contract: `security/trivy/verify-web-runtime.sh
  payment-portal-web:any-313` exited 0. The process UID was `1000`, Node was
  `v24.18.0`, and every prohibited npm, Corepack, Vitest, Vite, and esbuild
  path was absent.
- Standalone smoke: `/ru/auth-checkout?product=document-summary` returned HTTP
  200 with Russian checkout markup. The non-default build argument
  `https://api.any-313.example` was present in the browser chunks, proving the
  standalone build preserves `NEXT_PUBLIC_API_BASE_URL`.
- Trivy 0.72.0: the redacted `web-image.json` report produced
  `critical_vulnerabilities=0`, `fixable_high_vulnerabilities=0`,
  `high_or_critical_misconfigurations=0`, and
  `high_or_critical_secrets=0`. The Alpine and Node.js targets both reported
  zero vulnerabilities.
- Web checks: lint, typecheck, 9 boundary tests, 26 component tests, and the
  production build all passed in the builder environment. The build generated
  all 17 expected static routes.
- Browser smoke: the two focused Playwright files passed 5/5 tests on desktop
  Chromium against the isolated Compose stack using the final standalone web
  image. This covered legal gating, provider UI return behavior, authoritative
  webhook state, full and partial refunds, and stored checkout currency.
- Repository checks: documentation, generated artifacts, architecture, Ruff
  lint/format, 156 non-PostgreSQL API tests, and 15 PostgreSQL tests all passed.
  Direct `npm run check:fast` and `npm run check` invocations could not start on
  the host because npm is not installed (`zsh:1: command not found: npm`, exit
  127); every constituent command from both wrappers was therefore run in the
  matching Node builder or API development container. The browser suite was
  also run explicitly with `RUN_E2E` behavior covered by the focused 5/5 smoke.
- Scope review: `git diff main...HEAD --check` passed. The change is limited to
  the web runtime build/configuration, its security gate and workflow wiring,
  compatible runtime documentation, and ANY-313 planning evidence. The
  `Security scans` workflow still uses an unqualified `docker build` for the web
  image, so Docker selects the final `runtime` stage by default.
- Cleanup: `python3 scripts/repo.py down` stopped and removed the isolated
  Compose containers and networks after evidence collection; its named volume
  was preserved.
