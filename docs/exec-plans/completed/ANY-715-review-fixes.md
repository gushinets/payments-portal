# ANY-715 — Resolve sequential review findings

Status: implemented and locally verified; real integration checkpoint remains open
Updated: 2026-11-02

Issue: https://linear.app/paveldik/issue/ANY-715

Baseline: ANY-715 `9d57bc45cbe47ab8aa9e283e6a3496aa36e11edf`, merge base
`71ad993e843f7910626d6a9f40ce2b8a67494f1e`. The predecessor now contains
`cfb1265`; preserve its compatible distinction between diagnostic observations
and financial admission fences without rewriting branch history.

## Intended result

1. **P1-1:** deadline apply rereads the operation after business locks. A bind or
   completed no-send result committed after initial lookup cannot become review.
   The overdue customer path also calls the existing `record_customer_review`
   writer instead of the removed `customers._manual_review` alias. Its real
   PostgreSQL regression failed with `AttributeError`; completed-customer control
   passed before the correction.
2. **P1-2:** product-local incomplete LBX proof cannot discard another product's
   already proven inventory conflict. Keep the same live budget, queue fence and
   atomic scoped conflict writer; never save late or stale evidence.
3. **ARCH-2:** the final payment Widget admission checks current customer and
   purchase together under one short transaction, after all source I/O. Reuse
   the account Widget's customer guard. Preserve real financial fences while
   excluding mutable diagnostic failure observations from admission equality.

## Execution and evidence

- [x] Add PostgreSQL regressions with real writers and valid control cases:
  baseline 5 PASS / 5 FAIL in 30.85s. The failures reproduce both deadline races,
  discarded inventory conflict, customer-conflicted Widget admission and the
  predecessor's diagnostic-only false refusal.
- [x] Implement the smallest shared guards and scoped error handling; no DDL,
  public API change, CREATE permission or paid-access writer.
- [x] Run focused affected regressions and complete supported canonical checks.
- [x] Record final evidence and update the current implementation record.

Focused verification after the corrections: **12 PASS in 39.37s**, including
both deadline interleavings, customer escalation/idempotency, scoped inventory,
real shared reconciliation during Widget admission and diagnostic-only updates.
The first complete-check invocation passed its fast/API/web/build stages and was
intentionally interrupted during PostgreSQL verification to reproduce and repair
the removed customer-review alias. It is not a complete-check PASS. A fresh
complete-check invocation subsequently passed against the final application/test
source.

## Final verification

- Full `npm run check`: **PASS / exit 0**, with 1,689 fast API, 612 PostgreSQL,
  394 component and 38 web boundary tests; Python/web lint, production build,
  architecture, documentation and generated freshness all passed. The 12 new
  regressions are included in the 612 PostgreSQL cases, which took 1,567.67s.
- API source/test SHA-256 before and after the complete run was unchanged:
  `5f6cde4411b315d6a49aba2c99cc14ec74f743695b8127c05eb1790129ae14d9`.
- Child test environments clear inherited LBX/Kernel/telemetry development
  settings and set `KERNEL_MOCK_ENABLED=0`; root/private settings are untouched.
  Source responses are **SIMULATED**. Only worktree `payments-b7e9ed31` and its
  fixture-owned disposable `payments_b7e9ed31_review_fixes_tests` database were
  used. No application/production migration or real provider mutation occurred.
- Browser E2E was **SKIPPED** (`RUN_E2E` not enabled). Real LBX and webhook
  delivery remain **NOT_RUN**; webhook mode stays **DISABLED/POLLING-ONLY**.
- Local logs and reproducible runner scripts are retained under ignored
  `.harness/any715-review-fixes-20261102/`, including the failed reproductions
  and interrupted first canonical invocation. No commit/push or history rewrite
  is part of this correction.

The configured test-LBX read-only checkpoint remains separate: inspect an
existing owned subscription through the real reconciliation entrypoint, without
a new purchase/payment or any provider mutation. No credentials are configured
in this worktree, so simulated regression tests cannot close that checkpoint.
