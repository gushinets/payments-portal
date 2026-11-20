# ANY-828 glob and minimatch remediation

Issue: https://linear.app/paveldik/issue/ANY-828

## Objective and constraints

Remove GHSA-3g3m-2fjr-6pw4 and GHSA-g3hv-75wg-m249 from every affected npm chain while preserving Node 24, Next 16.4.2, lint, generated contracts and runtime behavior. Baseline: fetched origin/main aa9d8f996cba91feaaaad6a9937eef0c590ae4fa. Do not change API images, Debian packages, uv.lock, installation-script policy, scanner enforcement or legal/UI behavior.

## Decisions and coverage

Official advisories affect glob >=9.0.0 <=14.0.1 (fixed 14.0.2) and minimatch >=7.0.0 <11.0.1. Leave minimatch 3.1.5 compatible. Closed/unmerged Dependabot PR165 updates Sentry 11.4.0 to 11.11.0 and glob to14.0.4, but retains independent affected lint copies; reuse its parent selection rather than its generated lock diff.

Prefer @sentry/nextjs 11.11.0 (bundler-plugins declares glob ^14.0.3), ESLint10.15.0 (declares minimatch ^11.0.5/config-array ^0.23.6), and refresh the existing eslint-config-next -> typescript-eslint range to8.73.0 (estree declares minimatch ^11.0.1). No override planned. Node24 meets all engines; The parser's resolved TypeScript 5.9.3 API and ESLint 10 meet typescript-eslint peers. The web workspace separately retains @typescript/typescript6@6.0.2, which exports API 6.0.3. Next16 meets Sentry peer range. Review native matcher/Bash edge changes through real lint and ordinary file selection, not adversarial patterns.

Existing coverage: boundary tests exercise ESLint configuration and architectural rules, SentryReporting has eight sanitization/init/reporting cases, all component tests cover UI, typecheck/build cover imports and tracing. next.config.mjs does not install withSentryConfig; preserve the actual existing integration. Check actual bundled Sentry APIs and production standalone runtime; mocked tests alone do not prove SDK compatibility.

## Execution

- [x] Read instructions, issue, private coordination; inspect existing branches/worktrees and PR165; fetch main and isolate.
- [x] Record unchanged clean install, dependency inventory/explanations, audit, Trivy filesystem scan and focused characterization/build results.
- [x] Upgrade only owning packages and their required dependency closure; regenerate root package-lock via npm; inspect all nested copies and unchanged3.x line.
- [x] Clean install; run lint/typecheck/boundaries/components, real Sentry API smoke, Next production build and generate:check.
- [x] Coordinate Docker/full-check window with ANY-674; build baseline/final web images separately, run existing runtime verification and consistent Trivy filesystem/image scans. Preserve commands, DB/scanner metadata, hashes, UTC timestamps and immutable identities.
- [x] Run check:fast and broadest supported check, review final diff/fresh main, publish focused PR using template. No merge/deploy/Done.

Rollback is reverting the owning-package manifest and regenerated lock together. Scanner absence proves only target removal; retain unrelated findings. UI/provider journeys are not changed; production HTTP/runtime smoke is applicable, live payment acceptance is not.

## Evidence

Task-local raw logs/reports: .harness/any-828. Sanitized portable evidence and exact command outcomes will be recorded here before handoff. No private diary content belongs in this document.

## Verified implementation and scans

Implementation source: `2eddd69c86d07e64f2cf3cf1f606637f61a1471f`.
The image context's application, manifest, lock and Dockerfile contents match
that revision after Windows checkout line-ending normalization; only subsequent
evidence documents differ. The baseline context was extracted with `git archive`
from the fetched baseline SHA. Its lock matches the saved before checkout
representation. Recorded lock hashes identify CRLF checkout files; separate LF
Git-blob hashes and normalized equality are retained in the evidence. Full copy inventories, report SHA-256 hashes,
scanner/database metadata and immutable image identities are retained in
[the sanitized evidence](2026-11-18-any-828-evidence.json).

| Chain | Before | After |
| --- | --- | --- |
| Sentry Next/node -> bundler-plugins -> glob -> minimatch | 11.4.0 -> 11.4.0 -> 13.0.6 -> 10.2.6 | 11.11.0 -> 11.11.0 -> 14.0.6 -> 11.0.9 |
| ESLint -> config-array/direct minimatch | 10.8.1 -> 0.23.5 -> 10.2.6 | 10.15.0 -> 0.23.6 -> 11.0.9 |
| eslint-config-next -> typescript-eslint -> estree -> minimatch | 16.4.2 -> 8.67.0 -> 8.67.0 -> 10.2.6 | 16.4.2 -> 8.73.0 -> 8.73.0 -> 11.0.9 |
| Compatible ESLint9/import/react/a11y release line | minimatch3.1.5 | minimatch3.1.5 |

There is one fixed glob copy and six fixed minimatch11 copies (one for ESLint,
one for glob, four under TypeScript ESLint consumers). npm's dev flag on the
Sentry dependency closure is not runtime reachability: the standalone final
image contains neither target package. Both baseline and rebuilt image scans
contain neither target advisory. These are build/lint paths, not Portal HTTP
pattern inputs.

Local Trivy0.72.0 uses an isolated copy of database UpdatedAt
`2026-11-18T07:15:21.579242117Z`, originally downloaded by the independent image
lane, copied read-only; its metadata/database bytes are hashed in the evidence.
The scanner image is immutable in that file. Before/after local vulnerability
scans use identical flags and DB bytes. They intentionally scan vulnerabilities
only. The full repository filesystem/Compose/IaC/secret/image workflow also
[passed on the implementation](https://github.com/gushinets/payments-portal/actions/runs/44311980289).
Its artifact14430842120, SHA-256
`c54e18605788f324db275a9bb48fade609ad362e5001f867f6bbe2ac7b703587`, was downloaded,
hash-verified and inspected; full CI filesystem/web reports contain neither
advisory. CI image configuration identity differs from the local build and is
retained separately. This task never substitutes an API image for web evidence.

Npm audit exits1 before and after because unrelated findings remain. Before:
29 affected-package entries (12 Moderate/17 High); after23 (1 Moderate/22 High).
The unique non-target advisory set is unchanged (Next, picomatch, zod); changing
parent topology changes propagated package counts. Local/CI filesystem after
scan has7 findings across npm/uv, web image3 (Next CVE-2026-119351,
CVE-2026-119790 and zlib CVE-2026-4738). No claim of a clean repository/image.
No ignores, security bypasses or enforcement changes.

### Reproducible local commands

Run from the isolated repository root in PowerShell with Node24/npm11; caches,
temporary files, node_modules, Python environment and all evidence stay task-local
on D:. `uv0.12.7` is selected on PATH for Python-backed commands.

```powershell
$env:npm_config_cache = "$PWD/.harness/any-828/npm-cache"
$env:TEMP = "$PWD/.harness/any-828/tmp"
$env:TMP = $env:TEMP
npm ci --no-audit --fund=false
npm ls glob minimatch --all --json
npm explain glob
npm explain minimatch
npm audit --fetch-retries=0 --fetch-timeout=60000 --json
npm run lint:web
npm run typecheck:web
npm run test:boundaries:web
npm --workspace @anytoolai/web run test:components
npm run generate:check
$env:APP_PUBLIC_BASE_URL = 'https://payments.example.test'
npm run build:web
npm run check:fast
npm run check
```

Lock regeneration used `npm install @sentry/nextjs@11.11.0 --workspace
@anytoolai/web --save-exact --package-lock-only --ignore-scripts --no-audit`,
`npm install eslint@10.15.0 --workspace @anytoolai/web --save-dev --save-prefix='^'
--package-lock-only --ignore-scripts --no-audit`, and targeted `npm update` of
`typescript-eslint` plus its `@typescript-eslint` package family with the same
lock-only flags. These flags apply only to dependency resolution; both clean
installs and Docker use the existing lifecycle policy without changes. All
non-target version changes belong to the upgraded parents' dependency closure.

```powershell
docker build --file apps/web/Dockerfile --build-arg APP_PUBLIC_BASE_URL=https://payments.example.test --tag payment-portal-web:any-828-after .
# Before uses the git-archive baseline context and its apps/web/Dockerfile.
docker image inspect payment-portal-web:any-828-after
docker save --output .harness/any-828/after-image.tar payment-portal-web:any-828-after
$env:MSYS_NO_PATHCONV = '1'
& D:/Git/bin/bash.exe security/trivy/verify-web-runtime.sh payment-portal-web:any-828-after
docker run --rm --network none --mount "type=bind,source=$PWD/.harness/any-828,target=/evidence" aquasec/trivy:0.72.0 --cache-dir /evidence/trivy-cache image --input /evidence/after-image.tar --skip-db-update --scanners vuln --format json --output /evidence/after-web-image.json
docker run --rm --network none --mount "type=bind,source=$PWD,target=/repo,readonly" --mount "type=bind,source=$PWD/.harness/any-828,target=/evidence" aquasec/trivy:0.72.0 --cache-dir /evidence/trivy-cache fs --config /repo/trivy.yaml --include-dev-deps --skip-db-update --skip-check-update --scanners vuln --format json --output /evidence/after-filesystem.json --skip-dirs .git,.harness,node_modules,apps/web/node_modules,apps/web/.next,.venv,security/trivy/fixtures /repo
```

Baseline and final production Docker builds PASS. Final immutable local index:
`sha256:aaf34f49b03d594620ab651ff693a37ab715afad4231084c7ecc705177733f15`;
configuration`sha256:4268fb42bc6ec593560a2a6f0a5db1215c90a0cb243a3e1a3dc020325290c4f9`.
The existing runtime verifier PASS for both images (non-root node24.22.1,
standalone entrypoint, required OS patch constraints, no build tooling,
compression and native sharp). Final-image HTTP smoke on task-specific
127.0.0.1:39828 served `/en`200 with lang=en; only its temporary container was
removed. No shared service was restarted or stopped.

### Checks and limitations

PASS: before/after clean install; updated lint/typecheck;40 boundary tests
(including2 real Sentry/glob tests);454 component tests; generate:check;
production Docker build/runtime/HTTP; both target advisories absent in audit,
local FS and before/after web images; official security workflow.

The unchanged host build compiled/generated102 pages then stopped at the
existing unrelated Next security upgrade notice. The first updated host build
failed with Windows1450 insufficient resources; the isolated Linux production
build subsequently passed without disabling any build checks. Canonical command
completion is recorded below when finished. Live-provider/payment/browser visual
acceptance is not required for this tooling change; CI browser regression remains
applicable. Independent read-only review found no actionable findings; it did not
rerun checks or independently verify upstream provenance.

Canonical `npm run check:fast` PASS (2294 API tests passed,43 skipped,
1210 PostgreSQL tests deselected;40 boundary/454 component tests).
`npm run check` FAIL after the same2294 API pass/43 skips and successful
web compilation/typechecking/102-page generation: the existing unrelated
Next SecurityFatalError requested a same-command retry. PostgreSQL and
optional browser stages were unreached locally, not passed. A single standalone
build retry is recorded separately; no security check was disabled. The separate
docs command initially selected global Python and lacked pydantic_settings;
rerunning with canonical `.venv/Scripts/python.exe scripts/repo.py docs check`
PASS. Canonical commands already selected their required environment and passed
docs/architecture/generation/Python lint/format.

The permitted standalone host `npm run build:web` retry PASS (exit0), with no
dependency/config/security-policy changes. The complete local `npm run check`
remains recorded as FAIL at the earlier notice; it was not relabeled from a
successful standalone build. Final fresh-main fetch remains
aa9d8f996cba91feaaaad6a9937eef0c590ae4fa, with no intervening overlap.
Implementation CI production gate, code quality and Windows/Linux harness
checks PASS; browser job subsequently PASS (248 browser tests passed, 2 skipped; 4 React runtime tests passed).

CI production gate PASS on implementation source: 1209 PostgreSQL tests passed,
1 skipped across four partitions, production images and API smoke passed.
The provenance review verified all retained report/database/artifact hashes and
matcher inventories. Its checkout-versus-Git line-ending wording correction was
applied; no executable code changed after implementation verification.

All implementation-revision CI jobs, security scan and Linear metadata checks
PASS. Evidence-only follow-up changes do not alter the tested manifest, lock,
application, Dockerfile or tests; automatic checks on that documentation commit
may still be pending. PR: [ANY-828 - Patch glob and minimatch dependency chains](https://github.com/gushinets/payments-portal/pull/180).
No remaining overlap or resource coordination is required with ANY-674; its API
image/package scope and retained services were preserved. No merge, deployment
or Linear Done transition was performed.

## PR review follow-up: optional compiler peer and checkout-path portability

Review baseline: `611716ff815292ff6936ffe3a3d1421986d7a7ed`.

- [x] Establish failing regressions for the installed peer graph and literal
  glob selection with braces in a parent directory.
- [x] Rename only the TypeScript 7 CLI alias, leaving the parser's optional native
  backend absent; regenerate the lock through npm. Keep the parser's root
  TypeScript 5.9.3 API resolution, the web TypeScript 6 compatibility wrapper
  and the fixed matcher release lines unchanged.
- [x] Use a relative literal glob with the fixture as cwd; retain a brace-containing
  fixture so the checkout-name failure remains covered.
- [ ] Clean install, validate the full installed graph and TypeScript 7 CLI,
  run relevant web/canonical checks, and publish results in the existing review.

Root cause: `@typescript/native` was a local alias for the CLI's stable TypeScript
7.0.2 package. TypeScript ESLint 8.73.0 now recognizes that same package key as an
optional native-parser backend requiring a 7.1 prerelease. The configured parser
resolves the root `node_modules/typescript` API at version 5.9.3. Separately,
the web workspace resolves `@typescript/typescript6@6.0.2`, whose exported API
is version 6.0.3. Keeping the CLI under a distinct local alias avoids falsely
advertising the incompatible
optional backend; it does not relax validation or change the compiler release.

The glob test used an escaped absolute path as a pattern. Its parent directories
could contain brace expansions, making the test depend on its checkout name.
The cwd option expresses that directory as a filesystem path, while only the
relative fixture filename is interpreted as a glob.


Follow-up verification before publishing the fix:

- Unchanged clean install PASS. Added brace-path regression FAIL as expected
  (actual empty matches, existing literal file); installed-peer regression FAIL
  as expected with ELSPROBLEMS. This establishes both failures before the fixes.
- Corrected clean install PASS. Full installed `npm ls --all --json` PASS;
  both targeted regressions PASS. The native-backend peer is absent, not ignored.
  Filtering only `npm ls --all @typescript/native` now yields an empty result
  (npm exit 1 for no matching installed package), not an invalid peer graph.
- Lock comparison PASS: the old compiler payload equals the new alias payload
  exactly; every other existing package version is unchanged. The compiler is
  still 7.0.2; the ESLint parser API remains 5.9.3, and the web compatibility
  wrapper remains 6.0.2 (exported API 6.0.3). Glob remains 14.0.6, with six
  minimatch 11.0.9 copies and unaffected minimatch 3.1.5. No prerelease compiler or override was added.
- Canonical web checks PASS: 41 boundary tests, 454 component tests, lint,
  TypeScript 7 CLI/project typechecking, generated freshness and architecture.
- Standalone web build compiled/typechecked/generated 102 pages, then stopped
  at the pre-existing Next security recommendation. Its permitted same-command
  retry PASS, without disabling any check or changing Next.
- Fresh npm audit exits 1 for the same 23 unrelated affected-package entries
  (1 Moderate, 22 High); neither target advisory is present.
- Independent read-only review found no actionable findings. No API, image,
  installation-script or scanner policy change belongs to this follow-up.
- The local broad `npm run check` encountered a failure in unchanged
  `compatibility/test_uvicorn_smoke.py` while continuing the API suite.
  Complete local acceptance is not claimed; final details are reported in the
  PR follow-up review. This task does not repair unrelated API smoke behavior.

The original scan/image evidence above remains attributed to its original
source revisions. It is not presented as a new scan of this follow-up commit;
automatic PR security/production/browser checks will run on the pushed fix.


## Review correction: actual TypeScript API resolution

The earlier wording incorrectly inferred the ESLint parser's API from the web
workspace dependency declaration. Resolution was checked directly on executable
source/lock revision `776061961612b9dfac803449d4c98ad77f63649c` while preparing
this documentation-only correction:

| Consumer | Actual version | Resolution from repository root |
| --- | --- | --- |
| Explicit typecheck CLI | 7.0.2 | `node_modules/@anytoolai/typescript-cli/bin/tsc` |
| ESLint's configured TypeScript parser | 5.9.3 | `node_modules/typescript/lib/typescript.js` |
| Web workspace API / Next.js API mode | 6.0.3 | `apps/web/node_modules/typescript/lib/typescript.js`; compatibility package `@typescript/typescript6@6.0.2` delegates to `@typescript/old@6.0.3` |

Node resolves a dependency relative to its consuming module. The hoisted ESLint
parser does not resolve the web workspace's nested compatibility alias. The
root 5.9.3 API satisfies the parser's declared `>=4.8.4 <6.1.0` peer range.
A fresh-process lintText check with the real web ESLint configuration returned
zero errors and loaded only the root TypeScript 5.9.3 API.

Reproduce the API paths from the repository root:

```sh
node -e "const {createRequire}=require('node:module'); const path=require('node:path'); const parser=createRequire(require.resolve('@typescript-eslint/parser/package.json')); const web=createRequire(path.resolve('apps/web/package.json')); console.log('ESLint parser',parser('typescript').version,parser.resolve('typescript')); console.log('web API',web('typescript').version,web.resolve('typescript'));"
```

This corrects evidence and consumer attribution only. No dependency, lockfile,
configuration, executable source or compiler behavior changes. The decision to
retain the TypeScript 7 CLI and the TypeScript 6 API needed by web tooling is
unchanged; it does not claim that ESLint already consumes that TypeScript 6 API.
The existing TypeScript 6.0.3 versus 7.0.2 CLI benchmark remains valid because it
invoked those compiler entrypoints directly, independently of ESLint resolution.
