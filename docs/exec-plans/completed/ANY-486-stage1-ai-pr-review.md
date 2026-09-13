# ANY-486 - Stage 1 AI PR Review Integration

## Status

- State: completed
- Owner: agent
- Created: 2026-09-13
- Last updated: 2026-09-14
- Linear issue: https://linear.app/paveldik/issue/ANY-486/integrate-stage-1-ai-pr-review-into-payment-portal

## Objective

Add the Stage 1 informational AI PR Review integration to Payment Portal pull requests by wiring a thin GitHub Actions caller to the frozen central reusable workflow.

## Final integration evidence

- Integration PR: https://github.com/gushinets/payments-portal/pull/95
- PR state: merged
- Target branch: main
- Approved exact PR head: ab9ba776e46092a4b47b41d8116eb971b39d2aaa
- Actual merged PR head: ab9ba776e46092a4b47b41d8116eb971b39d2aaa
- Merge commit / merged main SHA: be6351b2c8c71f210a7e4c1a8e4eeaa2060e1838
- Merged at: 2026-09-13T17:15:36Z
- Merged files present on origin/main: .github/ai-review.yml, .github/workflows/ai-pr-review.yml, this execution plan
- Frozen engine SHA: 660525298b8785158fc8339add65f0e5cd87e749

## Post-merge automatic smoke evidence

- Smoke Linear issue: ANY-488, https://linear.app/paveldik/issue/ANY-488/ai-pr-review-stage-1-smoke-payment-portal-api-scope
- Smoke PR: https://github.com/gushinets/payments-portal/pull/96
- Smoke branch: codex/any-488-stage1-smoke-api
- Smoke head SHA: b2ecb2fa45e9e374910a31af3d6a314259467e97
- Smoke diff: apps/api/ai-pr-review-stage1-smoke.md only; documentation-only, no runtime code
- Primary CI run: CI 34771521399, https://github.com/gushinets/payments-portal/actions/runs/34771521399
- Primary CI result: success on b2ecb2fa45e9e374910a31af3d6a314259467e97
- Automatic AI PR Review run: 34771727206, https://github.com/gushinets/payments-portal/actions/runs/34771727206
- AI trigger: workflow_run after the CI pull_request run completed
- AI jobs: preflight 103762421741, review 103762521714, publisher 103763152242
- Called engine SHA: 660525298b8785158fc8339add65f0e5cd87e749
- Canonical artifact: 10322233556, ai-review-state-v1-pr-96, digest sha256:d54d4e1f2bbbdf8d7815a50d57edb6407ce6227d2c2d09613d74d451d9a9eb48
- Artifact review identity: gushinets/payments-portal#96; base be6351b2c8c71f210a7e4c1a8e4eeaa2060e1838; head b2ecb2fa45e9e374910a31af3d6a314259467e97; engine 660525298b8785158fc8339add65f0e5cd87e749; Linear ANY-488
- AI PR Review Check: 103763244709, https://github.com/gushinets/payments-portal/runs/103763244709
- Check head SHA: b2ecb2fa45e9e374910a31af3d6a314259467e97
- Final outcome: PASS
- Blocking findings: 0
- Non-blocking findings: 0
- Stable summary comment: IC_kwDOTIm_Wc8AAAABUQ8c8A, https://github.com/gushinets/payments-portal/pull/96#issuecomment-5654912240
- Smoke PR disposition: closed without merge; remote smoke branch deleted

## Scoped policy evidence

- Live API-scope artifact evidence for apps/api/ai-pr-review-stage1-smoke.md: selected AGENTS.md, docs/engineering/CODING_CONVENTIONS.md, and apps/api/AGENTS.md; apps/web/AGENTS.md absent.
- Deterministic central selector evidence for apps/api/ai-pr-review-stage1-smoke.md: selected [AGENTS.md, docs/engineering/CODING_CONVENTIONS.md, apps/api/AGENTS.md], includesApi=true, includesWeb=false.
- Deterministic central selector evidence for apps/web/example.ts: selected [AGENTS.md, docs/engineering/CODING_CONVENTIONS.md, apps/web/AGENTS.md], includesApi=false, includesWeb=true.

## Validation

- Static reusable workflow target check passed for gushinets/ai-pr-review/.github/workflows/reusable-ai-pr-review.yml@660525298b8785158fc8339add65f0e5cd87e749.
- Secret mapping keys are exactly QWEN_TOKEN_PLAN_API_KEY, LINEAR_CLIENT_ID, and LINEAR_CLIENT_SECRET.
- Forbidden legacy credential names and inherited-secret syntax were absent from the integration diff.
- Primary CI preservation check passed: .github/workflows/ci.yml unchanged.
- GitHub CI was green on the approved integration PR head.
- Post-merge CI was green on the smoke PR head.
- Automatic AI PR Review published PASS on the exact smoke PR head.
- Local Windows npm run check:fast and npm run check still fail only on the accepted pre-existing boundary issue in unchanged apps/web/src/features/checkout/provider-adapters.ts; authoritative GitHub CI is green.

## Ruleset and security evidence

- protect main required checks at verification time: harness-smoke (ubuntu-latest), harness-smoke (windows-latest), Production gate, Code quality, validate.
- AI PR Review is not a required status check; Stage 1 remains informational.
- Merged caller forwards only QWEN_TOKEN_PLAN_API_KEY, LINEAR_CLIENT_ID, and LINEAR_CLIENT_SECRET.
- Frozen reusable workflow job permissions: preflight/review use read-only GitHub permissions; publisher uses pull-requests: write and checks: write.
- Model execution step has no GitHub write token; publisher has no QWEN or Linear credentials.
- All reusable workflow jobs checkout job.workflow_repository at job.workflow_sha with persist-credentials: false; the privileged AI path did not checkout or execute smoke PR code.
- Canonical artifacts and AI summary comments were scanned for secret names, bearer/authorization patterns, raw prompt/transcript indicators, and full Linear-description indicators; matches: 0.
- linear-code[bot] public comment exposed only a Linear link/key for ANY-488, not the issue description.

## Completion

Task 21 is complete. The Stage 1 Payments integration is merged, pinned to the frozen engine, proven by a real automatic post-merge API-scoped smoke, has deterministic web-scope proof, and remains informational.