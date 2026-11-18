# ANY-828 glob and minimatch remediation

Issue: https://linear.app/paveldik/issue/ANY-828

## Objective and constraints

Remove GHSA-3g3m-2fjr-6pw4 and GHSA-g3hv-75wg-m249 from every affected npm chain while preserving Node 24, Next 16.4.2, lint, generated contracts and runtime behavior. Baseline: fetched origin/main aa9d8f996cba91feaaaad6a9937eef0c590ae4fa. Do not change API images, Debian packages, uv.lock, installation-script policy, scanner enforcement or legal/UI behavior.

## Decisions and coverage

Official advisories affect glob >=9.0.0 <=14.0.1 (fixed 14.0.2) and minimatch >=7.0.0 <11.0.1. Leave minimatch 3.1.5 compatible. Closed/unmerged Dependabot PR165 updates Sentry 11.4.0 to 11.11.0 and glob to14.0.4, but retains independent affected lint copies; reuse its parent selection rather than its generated lock diff.

Prefer @sentry/nextjs 11.11.0 (bundler-plugins declares glob ^14.0.3), ESLint10.15.0 (declares minimatch ^11.0.5/config-array ^0.23.6), and refresh the existing eslint-config-next -> typescript-eslint range to8.73.0 (estree declares minimatch ^11.0.1). No override planned. Node24 meets all engines; TypeScript6.0.2 and ESLint10 meet typescript-eslint peers. Next16 meets Sentry peer range. Review native matcher/Bash edge changes through real lint and ordinary file selection, not adversarial patterns.

Existing coverage: boundary tests exercise ESLint configuration and architectural rules, SentryReporting has eight sanitization/init/reporting cases, all component tests cover UI, typecheck/build cover imports and tracing. next.config.mjs does not install withSentryConfig; preserve the actual existing integration. Check actual bundled Sentry APIs and production standalone runtime; mocked tests alone do not prove SDK compatibility.

## Execution

- [x] Read instructions, issue, private coordination; inspect existing branches/worktrees and PR165; fetch main and isolate.
- [ ] Record unchanged clean install, dependency inventory/explanations, audit, Trivy filesystem scan and focused characterization/build results.
- [ ] Upgrade only owning packages and their required dependency closure; regenerate root package-lock via npm; inspect all nested copies and unchanged3.x line.
- [ ] Clean install; run lint/typecheck/boundaries/components, real Sentry API smoke, Next production build and generate:check.
- [ ] Coordinate Docker/full-check window with ANY-674; build baseline/final web images separately, run existing runtime verification and consistent Trivy filesystem/image scans. Preserve commands, DB/scanner metadata, hashes, UTC timestamps and immutable identities.
- [ ] Run check:fast and broadest supported check, review final diff/fresh main, publish focused PR using template. No merge/deploy/Done.

Rollback is reverting the owning-package manifest and regenerated lock together. Scanner absence proves only target removal; retain unrelated findings. UI/provider journeys are not changed; production HTTP/runtime smoke is applicable, live payment acceptance is not.

## Evidence

Task-local raw logs/reports: .harness/any-828. Sanitized portable evidence and exact command outcomes will be recorded here before handoff. No private diary content belongs in this document.
