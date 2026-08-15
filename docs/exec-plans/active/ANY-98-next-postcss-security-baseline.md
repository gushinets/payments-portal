# ANY-98 Next.js and npm Security Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the Next.js tooling versions and remove every Critical or fixable High npm finding without changing public checkout or payment behavior.

**Architecture:** Keep the application source unchanged and make explicit, reviewable dependency updates in the web manifest. Regenerate the npm 11 lockfile, prefer the fixed PostCSS supplied by the current Next.js release, and add a documented PostCSS override only if a current Trivy filesystem scan proves it is still required.

**Tech Stack:** Node.js 24, npm 11, Next.js 16, React 18, ESLint 9, TypeScript 5, Vitest 3, Trivy, Playwright

## Global Constraints

- Keep Next.js within major version 16 and align `eslint-config-next` to the exact same release.
- Preserve React 18, ESLint 9, and TypeScript 5.
- Do not run `npm audit fix`.
- Do not change application, checkout, payment, API, or legal behavior.
- Leave no Critical or fixable High npm finding in the refreshed Trivy filesystem report.
- Add no Trivy exception unless it has explicit human approval and an expiration date.

---

### Task 1: Record the failing dependency-security baseline

**Files:**
- Modify: `docs/exec-plans/active/ANY-98-next-postcss-security-baseline.md`
- Read: `apps/web/package.json`
- Read: `package-lock.json`

**Interfaces:**
- Consumes: ANY-98 acceptance criteria and the ANY-84 Trivy gate semantics in `scripts/repo.py`.
- Produces: Reproducible before-change evidence for the dependency update.

- [x] **Step 1: Confirm the branch and manifest scope**

Run:

```bash
git branch --show-current
git status --short
npm pkg get dependencies devDependencies --workspace @anytoolai/web
```

Expected: branch `ANY-98`; only this plan is uncommitted; Next.js is `16.3.1`, `eslint-config-next` is `16.2.9`, and React/ESLint/TypeScript remain on majors 18/9/5.

- [x] **Step 2: Run the npm audit baseline and verify it fails**

Run:

```bash
npm audit --json --package-lock-only --cache .harness/npm-cache
```

Expected: non-zero exit with current Critical or High findings through Vitest/Vite, `brace-expansion`, or `nanoid`; PostCSS is not reported by npm audit.

- [x] **Step 3: Run the reproducible local Trivy baseline**

Run:

```bash
TRIVY_INCLUDE_DEV_DEPS=true trivy filesystem --skip-db-update --config trivy.yaml --format json --output .harness/trivy-any98-baseline.json --ignorefile .trivyignore.yaml --skip-dirs .cache,.git,.harness,node_modules,apps/web/.next,.venv,security/trivy/fixtures .
python3 -c 'from pathlib import Path; from scripts.repo import summarize_trivy_report; print(summarize_trivy_report(Path(".harness/trivy-any98-baseline.json")))'
```

Expected: the cached database reproduces at least one Critical or fixable High npm finding. The report stays under ignored `.harness/` and is not committed.

- [x] **Step 4: Commit the execution plan**

```bash
git add docs/exec-plans/active/ANY-98-next-postcss-security-baseline.md
git commit -m "ANY-98 - Add dependency security implementation plan"
```

### Task 2: Update the minimum compatible dependency set

**Files:**
- Modify: `apps/web/package.json`
- Modify (generated): `package-lock.json`

**Interfaces:**
- Consumes: npm workspace `@anytoolai/web`, Node.js 24, and npm 11.
- Produces: Next.js/ESLint tooling aligned on `16.3.1` and a Vitest 3 dependency graph that admits a fixed Vite release.

- [ ] **Step 1: Change only the three required manifest entries**

Apply these exact values in `apps/web/package.json`:

```json
"@vitest/coverage-v8": "^3.2.7",
"eslint-config-next": "16.3.1",
"vitest": "^3.2.7"
```

Leave `next` at `16.3.1`, `react` and `react-dom` at `18.3.1`, ESLint on `^9.17.0`, and TypeScript on `^5.7.2`.

- [ ] **Step 2: Regenerate the lockfile without an audit fixer**

Run:

```bash
npm install --package-lock-only --ignore-scripts --cache .harness/npm-cache
```

Expected: npm updates `package-lock.json` from the explicit manifest and selects fixed compatible versions of Vite, `brace-expansion`, and `nanoid`.

- [ ] **Step 3: Install the exact refreshed graph**

Run:

```bash
npm ci --cache .harness/npm-cache
npm ls next eslint-config-next postcss vitest @vitest/coverage-v8 vite brace-expansion nanoid --all
```

Expected: `npm ci` succeeds; Next.js and `eslint-config-next` are both `16.3.1`; Vitest and its coverage provider are compatible `3.2.7` releases; the dependency tree has no invalid packages.

- [ ] **Step 4: Run focused web checks**

Run:

```bash
npm run lint:web
npm run typecheck:web
npm --workspace @anytoolai/web run test:components
npm --workspace @anytoolai/web run test:components:coverage
```

Expected: all commands pass without application-source changes.

- [ ] **Step 5: Commit the explicit dependency update**

```bash
git add apps/web/package.json package-lock.json
git commit -m "ANY-98 - Update Next tooling security baseline"
```

### Task 3: Prove whether a PostCSS override is necessary

**Files:**
- Read: `package-lock.json`
- Modify only if required: `package.json`
- Modify only if required: `docs/SECURITY.md`
- Modify only if required (generated): `package-lock.json`

**Interfaces:**
- Consumes: the refreshed npm graph from Task 2 and the repository Trivy policy.
- Produces: a clean npm/PostCSS security result, with a documented override only when current scanner evidence requires it.

- [ ] **Step 1: Inspect and audit the refreshed graph**

Run:

```bash
npm explain postcss
npm audit --json --package-lock-only --cache .harness/npm-cache
```

Expected: PostCSS resolves to a patched 8.5.x release and npm audit reports zero Critical and zero High vulnerabilities.

- [ ] **Step 2: Generate a current Trivy filesystem report**

Run the repository-equivalent scan with the newest locally available database:

```bash
TRIVY_INCLUDE_DEV_DEPS=true trivy filesystem --config trivy.yaml --format json --output .harness/trivy-any98/filesystem.json --ignorefile .trivyignore.yaml --skip-dirs .cache,.git,.harness,node_modules,apps/web/.next,.venv,security/trivy/fixtures .
python3 scripts/repo.py trivy redact .harness/trivy-any98
python3 -c 'from pathlib import Path; from scripts.repo import summarize_trivy_report; print(summarize_trivy_report(Path(".harness/trivy-any98/filesystem.json")))'
```

Expected: `critical_vulnerabilities=0`, `fixable_high_vulnerabilities=0`, `high_or_critical_misconfigurations=0`, and `high_or_critical_secrets=0`.

- [ ] **Step 3: Add the fallback override only if Step 2 reports PostCSS**

If and only if the remaining fixable High finding names `postcss`, add this root manifest entry:

```json
"overrides": {
  "postcss": "8.5.26"
}
```

Add this exact policy to `docs/SECURITY.md`: the override is temporary and must be removed once every dependency parent, including Next.js, resolves PostCSS `8.5.26` or newer without it and both npm audit and Trivy remain clean after removal. Then run:

```bash
npm install --package-lock-only --ignore-scripts --cache .harness/npm-cache
npm ci --cache .harness/npm-cache
npm audit --json --package-lock-only --cache .harness/npm-cache
```

Expected: all PostCSS instances resolve to `8.5.26`, and the audit remains free of Critical and High findings.

- [ ] **Step 4: Commit the override only when created**

```bash
git add package.json package-lock.json docs/SECURITY.md
git commit -m "ANY-98 - Pin patched PostCSS release"
```

Skip this commit when the upstream dependency graph passes Step 2.

### Task 4: Verify the characterized behavior and record evidence

**Files:**
- Modify: `docs/exec-plans/active/ANY-98-next-postcss-security-baseline.md`
- Verify: `apps/web/e2e/checkout-webhook.spec.ts`
- Verify: `apps/web/e2e/payment-result-refund.spec.ts`

**Interfaces:**
- Consumes: the final lockfile and existing ANY-95 characterization suite.
- Produces: handoff evidence for the ANY-98 pull request.

- [ ] **Step 1: Run clean-install and web production checks**

```bash
npm ci --cache .harness/npm-cache
npm run lint:web
npm run typecheck:web
npm run build:web
npm run test:boundaries:web
npm --workspace @anytoolai/web run test:components
npm --workspace @anytoolai/web run test:components:coverage
```

Expected: every command passes.

- [ ] **Step 2: Run canonical repository checks**

```bash
npm run check:fast
npm run check
```

Expected: both commands pass; any environment-dependent skip is recorded verbatim in this plan's completion evidence.

- [ ] **Step 3: Run the critical browser smoke**

Start the isolated repository stack with `npm run repo:up`, then run:

```bash
PLAYWRIGHT_PROVIDER_UI_STUB=true npm exec playwright test -- --config playwright.config.ts apps/web/e2e/checkout-webhook.spec.ts apps/web/e2e/payment-result-refund.spec.ts --project desktop-chromium --workers=1
```

Expected: checkout, verified-webhook payment confirmation, return-page polling, and refund scenarios pass against real Next.js, FastAPI, and PostgreSQL services. Stop the stack with `npm run repo:down` after evidence is collected.

- [ ] **Step 4: Review the final dependency-only diff**

```bash
git diff main...HEAD --check
git diff main...HEAD -- apps/web/package.json package.json docs/SECURITY.md
git status --short
```

Expected: no application source changes, no React/ESLint/TypeScript major changes, no generated or secret artifacts, and no unrelated worktree changes.

- [ ] **Step 5: Record completion evidence and commit it**

Update the `Completion Evidence` section below with exact command results, then run:

```bash
git add docs/exec-plans/active/ANY-98-next-postcss-security-baseline.md
git commit -m "ANY-98 - Record dependency upgrade evidence"
```

## Completion Evidence

Status before execution: no completion claim. The branch must not be pushed
until this section contains the exact audit, Trivy, test, build, and browser
results produced by Task 4.
