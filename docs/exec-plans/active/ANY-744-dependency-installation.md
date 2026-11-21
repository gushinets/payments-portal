# ANY-744 dependency installation policy

[Linear issue](https://linear.app/paveldik/issue/ANY-744)

Baseline: `49ed895d3925e097ef7e46908c87a6cb75f0fb26` from freshly fetched
`origin/main`. Main includes ANY-828 and ANY-829. The selected Debian API
recipe and pip removal are in the separate ANY-674 branch with ANY-742 merged
into it. ANY-831 also edits the harness in the Trivy command area.

Existing tests protect Python dependency pins, Docker group separation, the
web runtime image, and Windows launcher behavior. They do not prove install
script enforcement or wheel-only resolution.

1. Inventory integrity-checked npm archives, including inapplicable optional
   packages, then review every explicit and implicit install entrypoint.
2. Run the synthetic npm and install-entrypoint regressions against main.
3. Install with lifecycle hooks disabled and report unreviewed hooks from the
   lock and unpacked tree. Strict preflight alone missed an implicit build in
   the clean fixture. Use the npm bundled with the existing web image in CI
   and local setup. Resolve Playwright from the installed tree.
4. Carry forward the ANY-674 wheel-only Docker flags and apply them to the
   locked CI and harness sync paths.
5. Verify cold Windows and Linux installs, the source-only rejection fixture,
   the canonical checks, and production builds/runtime. Fetch main again and
   report measured results and any remaining integration overlap in the PR.

## Baseline and rollout evidence

- Before the policy, the entrypoint regression found locked CI uv sync without
  `--no-build`. With npm 11.19.1 strict mode absent, the clean fixture
  attempted `node-gyp rebuild`. A strict-only follow-up showed that the
  clean preflight missed the fixture's implicit native hook.
- Refetched main before submission. The base remained `49ed895d`. ANY-674
  supplied the same two Docker flags. Its branch also carries the ANY-742
  pip removal. This change ports the flags and keeps the separate base,
  runtime minimization and verifier changes in their owning PR.
- Cold-install, build and runtime outcomes for the task recipe and the
  separately attributed ANY-674/742 recipe are recorded in the PR.
