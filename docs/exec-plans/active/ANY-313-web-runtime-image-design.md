# ANY-313 Web Runtime Image Design

Status: approved design
Date: 2026-08-16
Linear: https://linear.app/paveldik/issue/ANY-313/razdelit-web-dockerfile-na-builderruntime-i-ubrat-dev-tooling-iz

## Problem

The current `apps/web/Dockerfile` builds and runs the portal in one stage. Its
runtime filesystem therefore includes the complete workspace `node_modules`,
including Vitest, Vite, esbuild, coverage tooling, and their transitive
dependencies. The baseline image builds successfully and runs as the `node`
user, but it is 340,201,948 bytes and exposes build-only packages to the Trivy
image scan.

## Goals

- Build the web application with all required development dependencies in an
  isolated build stage.
- Run only the files emitted by Next.js standalone output in the production
  stage.
- Preserve the pinned Node 24.18.0 Alpine 3.24 base image and the
  `NEXT_PUBLIC_API_BASE_URL` build-time value.
- Run the production server as the non-root `node` user on port 3000.
- Keep checkout and payment behavior unchanged.
- Make the absence of known build/test tooling from the runtime image
  verifiable and regression-resistant.

## Non-goals

- React 19, ESLint 10, or TypeScript major-version migrations.
- Changes to checkout, payment, authentication, or legal-page behavior.
- GHCR publishing changes.
- A new Trivy exception unless a fresh scan identifies an unavoidable,
  fixable-upstream blocker that satisfies the repository exception policy.

## Considered approaches

### Selected: Next.js standalone runtime

Enable `output: "standalone"`, set `outputFileTracingRoot` to the repository
root for the npm workspace layout, install the locked workspace dependencies in
a builder stage, and copy only the traced standalone server, static assets, and
public assets into the final image. Start the server with the standalone entry
point generated for the workspace application.

This approach gives Next.js ownership of runtime dependency tracing, removes
the full workspace dependency tree, and aligns with the ticket's requested
minimal runtime layout.

### Rejected: prune the builder dependency tree

Running `npm prune --omit=dev` after the build could preserve the current
workspace `npm start` command. It would still copy a broad workspace layout,
make pruning correctness part of the runtime contract, and produce a larger
image than standalone output.

### Rejected: manually copy production packages

Installing selected runtime packages or copying hand-picked module paths would
reduce image contents, but it would duplicate Next.js dependency tracing and
would be brittle across framework updates.

## Architecture

`apps/web/Dockerfile` will use three named stages based on the same pinned Node
image:

1. `dependencies` copies the root and web workspace manifests and runs
   `npm ci`. Build and test tooling exists only in this stage and descendants.
2. `builder` copies the web source and legal documents, receives
   `NEXT_PUBLIC_API_BASE_URL`, and runs `npm run build:web` with Next.js
   standalone output enabled. Repository-root output tracing preserves the npm
   workspace paths in the emitted layout.
3. `runtime` receives only the standalone server tree, `.next/static`, and
   `public`. It sets production runtime environment, uses the existing `node`
   account, removes the base image's npm and Corepack files because the direct
   Node entry point does not use them, exposes port 3000, and runs the generated
   workspace server with `node apps/web/server.js`.

The final stage will not copy the root `node_modules`, source tree, TypeScript
configuration, tests, or builder package manager state.

## Configuration and runtime contract

`NEXT_PUBLIC_API_BASE_URL` remains an `ARG` and `ENV` in the builder so Next.js
captures it in the browser bundle. It is also declared in the runtime stage for
compatibility with the existing Compose environment, while preserving the
documented rule that changing a public value requires rebuilding the image.

The standalone server reads `HOSTNAME=0.0.0.0` and `PORT=3000`. The externally
observable container port and Compose service contract remain unchanged. The
entry command changes from workspace `npm start` to the compatible standalone
entry point `node apps/web/server.js`.

## Failure behavior

The Docker build fails if dependency installation, the Next.js build, or any
required standalone/static/public copy fails. The runtime does not fall back to
installing packages or running a development server. A missing standalone
artifact is therefore detected during image construction rather than after
deployment.

## Verification

The implementation will add a focused Node test under `apps/web/tests` that
checks the standalone configuration, repository-root tracing, named
builder/runtime split, minimal copy contract, non-root user, and standalone
command. Runtime evidence will additionally:

- build the production image with a non-default
  `NEXT_PUBLIC_API_BASE_URL`;
- inspect the configured user and command;
- start the container and request a representative RU route;
- verify that npm, Corepack, `vitest`, `vite`, `@vitejs`, `@vitest`, and known
  build-only binaries are absent from the final filesystem;
- compare the final image size with the 340,201,948-byte baseline;
- run web lint, typecheck, component/boundary tests, production build, and the
  critical Playwright checkout/payment smoke;
- run a fresh Trivy 0.72.0 image scan and the repository Trivy gate when the
  local scanner/database are available;
- run the broadest repository check supported by the local environment.

No UI screenshot comparison is required because the implementation changes
only the build and runtime packaging. Browser smoke remains required to prove
that public behavior is unchanged.
