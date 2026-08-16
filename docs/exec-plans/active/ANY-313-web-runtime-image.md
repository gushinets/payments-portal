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
- Create: `apps/web/tests/docker-runtime.test.mjs`
- Read: `apps/web/Dockerfile`
- Read: `apps/web/next.config.mjs`

**Interfaces:**
- Consumes: the approved ANY-313 standalone layout and the existing `test:boundaries` Node test command.
- Produces: a source-level regression contract for the standalone configuration, runtime copy boundary, package-manager removal, non-root user, and direct Node command.

- [ ] **Step 1: Add the focused failing contract test**

Create `apps/web/tests/docker-runtime.test.mjs` with this content:

```js
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const repositoryRoot = fileURLToPath(new URL("../../..", import.meta.url));
const dockerfilePath = path.join(repositoryRoot, "apps/web/Dockerfile");
const nextConfigPath = path.join(repositoryRoot, "apps/web/next.config.mjs");

test("Next.js emits a repository-root standalone workspace", async () => {
  const source = await readFile(nextConfigPath, "utf8");

  assert.match(source, /output:\s*"standalone"/);
  assert.match(source, /outputFileTracingRoot:\s*repositoryRoot/);
});

test("production web image contains only the standalone runtime", async () => {
  const source = await readFile(dockerfilePath, "utf8");
  const runtimeMarker = /^FROM .* AS runtime$/m;
  const runtimeStart = source.search(runtimeMarker);

  assert.notEqual(runtimeStart, -1, "runtime stage must be named");
  assert.match(source, /^FROM .* AS dependencies$/m);
  assert.match(source, /^FROM dependencies AS builder$/m);

  const runtime = source.slice(runtimeStart);
  assert.match(runtime, /COPY --from=builder .*\.next\/standalone \.\//);
  assert.match(runtime, /COPY --from=builder .*\.next\/static \.\/apps\/web\/\.next\/static/);
  assert.match(runtime, /COPY --from=builder .*apps\/web\/public \.\/apps\/web\/public/);
  assert.doesNotMatch(runtime, /COPY --from=dependencies/);
  assert.doesNotMatch(runtime, /npm (ci|install|prune)/);

  for (const packageManagerPath of [
    "/usr/local/bin/corepack",
    "/usr/local/bin/npm",
    "/usr/local/bin/npx",
    "/usr/local/lib/node_modules/corepack",
    "/usr/local/lib/node_modules/npm"
  ]) {
    assert.ok(runtime.includes(packageManagerPath));
  }

  assert.match(runtime, /^USER node$/m);
  assert.match(runtime, /^EXPOSE 3000$/m);
  assert.match(runtime, /^CMD \["node", "apps\/web\/server\.js"\]$/m);
});
```

- [ ] **Step 2: Run the focused test and verify the red state**

Run:

```bash
node --test apps/web/tests/docker-runtime.test.mjs
```

Expected: both tests fail because standalone output and a named runtime stage do not exist yet. If the host has no Node.js binary, run the same command in the pinned Node image with the worktree mounted read-only.

- [ ] **Step 3: Confirm the failure describes only the missing ANY-313 contract**

Expected failure messages must name `output: "standalone"` and `runtime stage must be named`. Fix test path or pattern errors before changing production files.

### Task 2: Build the standalone runtime image

**Files:**
- Modify: `apps/web/next.config.mjs`
- Modify: `apps/web/Dockerfile`
- Modify: `README.md`
- Test: `apps/web/tests/docker-runtime.test.mjs`

**Interfaces:**
- Consumes: the locked root npm workspace, `docs/legal` build input, `NEXT_PUBLIC_API_BASE_URL`, and Task 1's contract.
- Produces: `/app/apps/web/server.js`, `/app/apps/web/.next/static`, and `/app/apps/web/public` in a non-root runtime image listening on port 3000.

- [ ] **Step 1: Enable repository-root standalone tracing**

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

- [ ] **Step 2: Replace the single-stage Dockerfile**

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

- [ ] **Step 3: Document the compatible command replacement**

Add this paragraph after the web image bullet in `README.md`'s `Runtime baseline` section:

```markdown
  The production web image uses Next.js standalone output and starts the traced
  workspace server directly with `node apps/web/server.js`; npm and other build
  tooling are not part of the runtime image.
```

- [ ] **Step 4: Run the focused contract test and verify the green state**

Run:

```bash
node --test apps/web/tests/docker-runtime.test.mjs
```

Expected: 2 tests pass, 0 fail.

- [ ] **Step 5: Run the existing web source-contract suite**

Run:

```bash
npm run test:boundaries:web
```

Expected: all `apps/web/tests/*.test.mjs` tests pass, including the two new Docker runtime tests.

- [ ] **Step 6: Build the builder and runtime targets**

Run:

```bash
docker build --target builder --file apps/web/Dockerfile --tag payment-portal-web:any-313-builder .
docker build --file apps/web/Dockerfile --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.any-313.example --tag payment-portal-web:any-313 .
```

Expected: both images build successfully. The builder log shows `next build` emitting standalone output, and the runtime build copies `apps/web/server.js` without installing dependencies.

- [ ] **Step 7: Commit the coherent implementation**

```bash
git add apps/web/tests/docker-runtime.test.mjs apps/web/next.config.mjs apps/web/Dockerfile README.md
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

- [ ] **Step 1: Inspect the final image metadata**

Run:

```bash
docker image inspect payment-portal-web:any-313 --format '{{json .Config.User}} {{json .Config.Cmd}} {{.Size}}'
```

Expected: user is `node`, command is `["node","apps/web/server.js"]`, and size is materially below the 340,201,948-byte baseline.

- [ ] **Step 2: Prove build and test tooling is absent**

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

- [ ] **Step 3: Smoke the standalone server and build argument**

Start `payment-portal-web:any-313` on an unused loopback port, wait for readiness, and request `/ru/auth-checkout?product=document-summary`. Search `.next/static` inside the image for `https://api.any-313.example`, then stop the disposable container.

Expected: HTTP 200, Russian checkout markup, no root process, and the non-default public API origin appears in the browser bundle.

- [ ] **Step 4: Run focused web checks inside the builder image**

Run these commands in `payment-portal-web:any-313-builder`:

```bash
npm run lint:web
npm run typecheck:web
npm run test:boundaries:web
npm --workspace @anytoolai/web run test:components
npm run build:web
```

Expected: every command passes. The second `build:web` confirms the source tree remains independently buildable outside the final runtime stage.

- [ ] **Step 5: Run the Trivy 0.72.0 image policy**

Run the same image scan shape used by `.github/workflows/security.yml`:

```bash
trivy image --config trivy.yaml --scanners vuln,secret --format json --output .harness/trivy-any313/web-image.json --ignorefile .trivyignore.yaml payment-portal-web:any-313
python3 scripts/repo.py trivy redact .harness/trivy-any313
python3 scripts/repo.py trivy gate .harness/trivy-any313
```

Expected: 0 Critical vulnerabilities and 0 fixable High vulnerabilities. No Vitest, Vite, esbuild, npm, Corepack, tar, or Undici finding originates from removed build/package-manager paths. If Trivy or its database cannot run locally, record the exact environmental limitation and rely on the unchanged `Security scans` workflow for the remaining image scan.

- [ ] **Step 6: Run the critical Playwright smoke**

Use the isolated repository stack, then run:

```bash
PLAYWRIGHT_PROVIDER_UI_STUB=true npm exec playwright test -- --config playwright.config.ts apps/web/e2e/checkout-webhook.spec.ts apps/web/e2e/payment-result-refund.spec.ts --project desktop-chromium --workers=1
```

Expected: checkout, verified-webhook payment status, return-page polling, and refund scenarios pass without unexpected browser console errors, failed application requests, or error spans. Stop the isolated stack after collecting evidence.

- [ ] **Step 7: Run the broadest supported repository checks**

Run:

```bash
npm run check:fast
npm run check
```

Expected: both commands pass. Record any environment-dependent skip or failure verbatim rather than claiming it passed.

- [ ] **Step 8: Review scope and record completion evidence**

Run:

```bash
git diff main...HEAD --check
git diff main...HEAD -- apps/web/Dockerfile apps/web/next.config.mjs apps/web/tests/docker-runtime.test.mjs README.md .github/workflows/security.yml
git status --short
```

Append a `Completion Evidence` section to this plan with the exact command results, image size delta, runtime user/command, package absence result, Trivy summary, browser result, canonical check result, and any local limitation. Confirm that `.github/workflows/security.yml` still builds the default final web image.

- [ ] **Step 9: Commit the evidence**

```bash
git add docs/exec-plans/active/ANY-313-web-runtime-image.md
git commit -m "ANY-313 - Record web runtime image evidence"
```
