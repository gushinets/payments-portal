# ANY-486 - Stage 1 AI PR Review Integration

## Objective

Add the Stage 1 informational AI PR Review integration to Payment Portal pull requests by wiring a thin GitHub Actions caller to the frozen central reusable workflow.

## Non-goals

- Do not change .github/workflows/ci.yml.
- Do not make AI PR Review required or modify repository rulesets.
- Do not add consumer-side AI review logic, scripts, package dependencies, or production code.
- Do not use dynamic engine references, extra engine inputs, inherited secrets, personal access tokens, or legacy credential names.
- Do not move this plan to completed/ before post-merge live smoke evidence exists.

## Decisions

- The consumer workflow runs only after the primary CI workflow completes for pull requests, with manual dispatch available for a specific PR number.
- The reusable workflow is pinned to 660525298b8785158fc8339add65f0e5cd87e749.
- The caller forwards only QWEN_TOKEN_PLAN_API_KEY, LINEAR_CLIENT_ID, and LINEAR_CLIENT_SECRET by name.
- .github/ai-review.yml keeps repo policy local and declarative: root instructions and coding conventions always apply, while API and web subtree guides are selected only for matching paths.

## Progress

- [x] Created an isolated worktree at D:/Work/AI/AnytoolAI/payments portal/.harness/worktrees/any-486-stage1-ai-pr-review.
- [x] Started from fresh origin/main at 2215227140d17698f689e0522f82c95fb81a4d53.
- [x] Read required repository instructions: AGENTS.md, docs/engineering/AGENT_WORKFLOW.md, docs/engineering/CODING_CONVENTIONS.md, apps/api/AGENTS.md, and apps/web/AGENTS.md.
- [x] Added .github/ai-review.yml.
- [x] Added .github/workflows/ai-pr-review.yml.
- [x] Completed static workflow, secret-name, policy-selection, YAML, and CI-preservation checks.
- [x] Ran required local repository gates and recorded the pre-existing Windows boundary failure.
- [x] Pushed branch codex/any-486-stage1-ai-pr-review.
- [x] Opened PR #95.
- [x] Verified exact-head GitHub CI on 2b5dc3fa20e69eadd8af95edf9623e40763ffb4c.
- [ ] Receive human merge approval.
- [ ] Merge the exact reviewed PR head.
- [ ] Run or observe the real automatic Stage 1 smoke after merge.

## Discoveries

- The original checkout had untracked user files and local main at 7d816f34b36b7aedd0b3672ec6a0e1da853eb487, while origin/main was 2215227140d17698f689e0522f82c95fb81a4d53; the task work stayed in an isolated worktree.
- The repo-managed setup requires uv==0.12.7; the active host uv was 0.9.0, so the active Python-installed uv package was updated to the pinned version before running npm run repo:setup.
- A pre-change npm run check:fast on Windows failed in npm run test:boundaries:web: CloudPayments browser SDK calls stay inside the checkout adapter reported unchanged apps/web/src/features/checkout/provider-adapters.ts on fresh origin/main.
- The same Windows boundary failure remains after the three-file Stage 1 integration; authoritative GitHub CI is green on the exact PR head.

## Validation

- [x] Static reusable workflow target: exact match and 40-character lowercase hexadecimal pin passed for gushinets/ai-pr-review/.github/workflows/reusable-ai-pr-review.yml@660525298b8785158fc8339add65f0e5cd87e749.
- [x] Secret mapping keys: exactly QWEN_TOKEN_PLAN_API_KEY, LINEAR_CLIENT_ID, and LINEAR_CLIENT_SECRET; each corresponding secrets name reference appears once.
- [x] Forbidden legacy credential names and inherited-secret syntax: absent from the changed files.
- [x] Primary CI preservation: git diff -- .github/workflows/ci.yml is empty.
- [x] API scoped policy for apps/api/example.py: selected exactly AGENTS.md, docs/engineering/CODING_CONVENTIONS.md, and apps/api/AGENTS.md; did not select apps/web/AGENTS.md.
- [x] Web scoped policy for apps/web/example.ts: selected exactly AGENTS.md, docs/engineering/CODING_CONVENTIONS.md, and apps/web/AGENTS.md; did not select apps/api/AGENTS.md.
- [x] YAML parse: .github/ai-review.yml and .github/workflows/ai-pr-review.yml parsed successfully with the repo Python environment. No repo-owned workflow linter command was found.
- [x] Secret-name readiness: gh secret list -R gushinets/payments-portal listed all three expected names: QWEN_TOKEN_PLAN_API_KEY, LINEAR_CLIENT_ID, and LINEAR_CLIENT_SECRET.
- [x] npm run check:fast fails on the accepted pre-existing Windows boundary test; 17/18 boundary tests pass.
- [x] npm run check fails at the same accepted pre-existing Windows boundary test before later full-check stages.
- [x] GitHub CI on PR head 2b5dc3fa20e69eadd8af95edf9623e40763ffb4c completed successfully.
- [ ] Post-merge live automatic Stage 1 smoke.

## Completion Evidence

The three-file consumer integration PR is ready for human merge approval. Live smoke remains incomplete until the workflow lands on main and a post-merge pull request can prove the automatic CI to AI PR Review path.
