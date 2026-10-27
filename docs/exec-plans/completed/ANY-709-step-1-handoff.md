# ANY-709 Step 1 - Connection, product links and current offers

Status: DONE - condensed historical implementation/evidence report
Date: 2026-10-27
Scope: Step 1 only; product-bound payment acceptance remains separate.

## Delivered result

- Normal LBX connection settings work through runtime, CLI and deployment;
  missing billing does not block unrelated authentication.
- The privileged CLI directly links Kernel product identity to LBX tariff,
  service and period. One current product pointer uses revision/CAS and preserves
  immutable mapping history. Price changes do not require republishing links.
- Browsing discovers enabled Kernel products and reads current selected LBX
  offers. Kernel and LBX provenance are independent; development Kernel mock
  data does not imply that LBX itself is simulated or production-approved.
- Approval/proposal files, manual account IDs, billing test profiles and catalog
  mirrors are removed from the normal path. No fake allowance is required.
- Connection identity is stable across credential rotation. Existing proven
  legacy scope may be retained through authorized origin binding; conflicting
  origins, ambiguous history and synthetic mappings are never adopted blindly.

## Important corrections

- LBX inline prices contain historical/future rows. Select the latest inclusive
  start on one captured `Europe/Moscow` date for the chosen service/period,
  compare it with the dedicated price method and use the confirmed money/ID.
- Validate discounts on that selected current row. Explicit empty discounts
  mean none; missing/null/conflicting facts fail safely and nonempty discounts
  remain unsupported. Other periods or future rows cannot override this proof.
- Preserve exact money, quantities, currency and two complete control reads;
  commercial drift refuses admission. Price-calendar dates do not define UTC
  subscription or quota intervals.
- `LBX_BILLING_TIMEZONE` was removed throughout configuration. The fixed source
  calendar is supported by system tzdata; it is not an operator setting.

## Recorded verification

At the 2026-10-27 price-calendar checkpoint:

- 317 focused offer/source/client regressions passed, including the final 62
  selected-offer cases. Captured source fixtures were unchanged.
- Canonical `npm run check` passed: 1,340 fast API tests, 210 PostgreSQL tests,
  300 component tests, 38 web boundary tests, lint/format, architecture, docs,
  generated-contract freshness and production web build. Development Kernel
  connection values were cleared only for the check process.
- Timezone/midnight regressions passed in network-disabled images; the production
  API image built and all 35 deployment-contract tests passed.
- Read-only local readiness and selected product GETs returned 200 with a
  current offer. Kernel provenance remained SIMULATED, LBX CONFIGURED_SOURCE.

These results describe that checkpoint, not a full final-SHA validation.
Browser E2E was skipped there; no real purchase or Widget payment was proven.

## Persistence and retained limits

Step 1 added the product pointer and origin provenance without guessed backfill
or rewriting immutable mappings. Its former separate revisions are now part of
`20261027_0003_normal_billing`; the verified local DB transition and current
migration rules are recorded in the completed plan.

Real Kernel producer conformance, product-bound payment/acquiring acceptance and
paid access remain outside this report. Current commands and recovery procedures
are maintained only in the billing runbook.

- [Completed plan](ANY-709-implementation-plan.md)
- [Billing runbook](../../engineering/ANY-709-billing-runbook.md)

Full pre-compaction chronology, original commands and intermediate failures are
retained in Git at `2961577`.
