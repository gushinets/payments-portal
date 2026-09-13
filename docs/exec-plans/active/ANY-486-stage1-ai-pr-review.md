# ANY-486 — Stage 1 AI PR Review Integration

## Objective

Add the Stage 1 informational AI PR Review integration to Payment Portal pull requests by wiring a thin GitHub Actions caller to the frozen central reusable workflow.

## Non-goals

- Do not change `.github/workflows/ci.yml`.
- Do not make AI PR Review required or modify repository rulesets.
- Do not add consumer-side AI review logic, scripts, package dependencies, or production code.
- Do not use dynamic engine references, extra engine inputs, inherited secrets, personal access tokens, or legacy credential names.

## Decisions

- The consumer workflow runs only after the primary `CI` workflow completes for pull requests, with manual dispatch available for a specific PR number.
- The reusable workflow is pinned to `660525298b8785158fc8339add65f0e5cd87e749`.
- The caller forwards only `QWEN_TOKEN_PLAN_API_KEY`, `LINEAR_CLIENT_ID`, and `LINEAR_CLIENT_SECRET` by name.
- `.github/ai-review.yml` keeps repo policy local and declarative: root instructions and coding conventions always apply, while API and web subtree guides are selected only for matching paths.

## Progress

- [x] Created an isolated worktree at `D:\Work\AI\AnytoolAI\payments portal\.harness\worktrees\any-486-stage1-ai-pr-review`.
- [x] Started from fresh `origin/main` at `2215227140d17698f689e0522f82c95fb81a4d53`.
- [x] Read required repository instructions: `AGENTS.md`, `docs/engineering/AGENT_WORKFLOW.md`, `docs/engineering/CODING_CONVENTIONS.md`, `apps/api/AGENTS.md`, and `apps/web/AGENTS.md`.
- [x] Added `.github/ai-review.yml`.
- [x] Added `.github/workflows/ai-pr-review.yml`.
- [x] Completed static workflow, secret-name, policy-selection, YAML, and CI-preservation checks.
- [x] Ran required local repository gates and recorded the pre-existing Windows boundary failure.
- [ ] Push branch, open PR, and wait for PR CI.

## Discoveries

- The original checkout had untracked user files and local `main` at `7d816f34b36b7aedd0b3672ec6a0e1da853eb487`, while `origin/main` was `2215227140d17698f689e0522f82c95fb81a4d53`; the task work stayed in an isolated worktree.
- The repo-managed setup requires `uv==0.12.7`; the active host `uv` was `0.9.0`, so the active Python-installed `uv` package was updated to the pinned version before running `npm run repo:setup`.
- A pre-change `npm run check:fast` on Windows failed in `npm run test:boundaries:web`: `CloudPayments browser SDK calls stay inside the checkout adapter` reported `apps/web/src/features/checkout/provider-adapters.ts` on fresh `origin/main`.

## Validation

- Static reusable workflow target: exact match and 40-character lowercase hexadecimal pin passed for `gushinets/ai-pr-review/.github/workflows/reusable-ai-pr-review.yml@660525298b8785158fc8339add65f0e5cd87e749`.
- Secret mapping keys: exactly `QWEN_TOKEN_PLAN_API_KEY`, `LINEAR_CLIENT_ID`, and `LINEAR_CLIENT_SECRET`; each corresponding `secrets.<name>` reference appears once.
- Forbidden legacy credential names and inherited-secret syntax: absent from the changed files.
- Primary CI preservation: `git hash-object .github/workflows/ci.yml` stayed `9cc23a0f5934e5149e0dca92f9c1abf92775ef6b`; `git diff -- .github/workflows/ci.yml` was empty.
- API scoped policy for `apps/api/example.py`: selected exactly `AGENTS.md`, `docs/engineering/CODING_CONVENTIONS.md`, and `apps/api/AGENTS.md`; did not select `apps/web/AGENTS.md`.
- Web scoped policy for `apps/web/example.ts`: selected exactly `AGENTS.md`, `docs/engineering/CODING_CONVENTIONS.md`, and `apps/web/AGENTS.md`; did not select `apps/api/AGENTS.md`.
- YAML parse: `.github/ai-review.yml` and `.github/workflows/ai-pr-review.yml` parsed successfully with the repo Python environment. No repo-owned workflow linter command was found.
- Secret-name readiness: `gh secret list -R gushinets/payments-portal` listed all three expected names: `QWEN_TOKEN_PLAN_API_KEY`, `LINEAR_CLIENT_ID`, and `LINEAR_CLIENT_SECRET`.
- `npm run check:fast`: failed on Windows in `npm run test:boundaries:web`; 17/18 boundary tests passed and the failing assertion matched the pre-change baseline for `apps/web/src/features/checkout/provider-adapters.ts`.
- `npm run check`: failed on Windows at the same boundary assertion before later full-check stages.

## Completion Evidence

Local Stage 1 integration evidence is complete for the three-file consumer change. PR creation and remote CI evidence remain to be collected after pushing the branch.
