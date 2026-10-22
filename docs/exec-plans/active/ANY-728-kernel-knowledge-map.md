# Execution Plan: ANY-728 Kernel knowledge map

Status: active
Created: 2026-10-23
Owner: agent

## Objective

[ANY-728](https://linear.app/paveldik/issue/ANY-728) implements the approved
2026-10-23 cross-repository audit with companion
[ANY-727](https://linear.app/paveldik/issue/ANY-727).
Observed baselines: Portal `79dc3f4d204aec4ac9552e3d1da3481553cc8aef`,
Platform `79a2ada5b790f959a40b3e08451ef9ed8d97da5b`.

## Scope and decisions

Add `docs/integrations/platform-kernel.md`; link root AGENTS, ARCHITECTURE and
docs/README; add PR Peer impact. Correct stale current-state and evidence text
in RELIABILITY, contract README, DEVELOPMENT, ADR 0005, payment-providers,
CODING_CONVENTIONS, API AGENTS and TESTING. Extend the existing authority-link
graph and `test_repository_docs.py` for the new map and accepted amendment.

The map delegates normative semantics to existing owners. Preserve historical
documents' classification and obligations, source pins, simulation containment
and real enablement gates. No runtime, migration, fixture, generated-artifact,
Region Resolver or deployment changes.

## Steps

- [x] Extend the graph tests and removal diagnostics; observe missing-link failures before implementation.
- [x] Write the map, repair current guidance and add the precise active-source graph edges.
- [ ] Run focused documentation tests and supported canonical checks; record results and limitations.
- [ ] Commit and obtain sequential fresh Astra xhigh, then fresh Sol max review on identical base/head SHAs; restart after fixes.
- [x] Open [PR 146](https://github.com/gushinets/payments-portal/pull/146), linked to ANY-727 and [Platform PR 204](https://github.com/gushinets/anytoolai-platform/pull/204); human merge approval remains required.

## Review focus

- Three request directions; local client/mock evidence never claims real producer conformance.
- Existing mapping publication versus future purchase, reconciliation and paid access.
- Accepted amendment's narrow precedence; retained historical source obligations.
- Actual regional scope mismatch and configured provisional client refusal in production.
- Root-to-map and map-to-authority navigation, including missing-link diagnostics.

## Evidence and discoveries

- Initial repository doctor: passed on Windows, Python 3.12.10, Node 24.18.0.
- Linear agent-context endpoint is unavailable; repository sources control this implementation.
- All 18 new link-graph cases failed before the graph was extended. The final
  repository-doc suite passes: 197 tests. Documentation and changed-file lint
  checks pass.
- Two existing ACL tests failed on Windows because expected paths were literal
  forward-slash strings. Expectations now use `str(Path(...))`, matching the
  existing implementation without changing ACL behavior.
- Canonical `check --fast` passed docs, generated artifacts, architecture, API
  lint, web boundaries, 281 component tests and web lint. The backend stage was
  interrupted after Windows shell failures and a stall in unchanged HTTP-client
  tests; it is not a passing full check.
- Canonical generation normalized CRLF/LF in local generated TypeScript;
  `git diff --exit-code` confirms no generated artifact change.
- PostgreSQL reported 110 passed, 5 skipped and 4 failed on Windows. Three
  failures require `os.geteuid`; one requires a POSIX operator lock. The
  production web build passed with the example public URL. The interrupted
  Windows backend check remains a limitation.
- Linux [CI run 39836638193](https://github.com/gushinets/payments-portal/actions/runs/39836638193)
  passed for `81b18c0cdff17f9384f28a1cf05f2eabfe9f2418`, including Code quality,
  Production gate, browser and both harness smoke jobs. This is recorded
  evidence for that SHA, not a claim for later commits. Final-SHA CI and
  sequential Astra/Sol results are tracked in
  [PR 146](https://github.com/gushinets/payments-portal/pull/146).
