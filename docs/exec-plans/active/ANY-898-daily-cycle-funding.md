# ANY-898 — Verify daily cycle funding before issuing allowances

## Objective

Use an authoritative LBX calculation for the exact current day before a
positive reconciliation can issue a fixed allowance on the supported
`day / 1 / first_instance_start` profile. [ANY-898](https://linear.app/paveldik/issue/ANY-898)
contains the three recorded LBX 043 responses for 25 November 2026.

## Boundaries

[PR #196](https://github.com/gushinets/payments-portal/pull/196) brings the daily
calendar and its funding verification through review together. The calendar was
prepared during ANY-767 acceptance and enables the observed LBX profile. The
funding check uses provider facts within the existing reconciliation and
allowance boundaries.

## Work and verification

1. Reproduce an active, unfunded daily point read through the actual LBX client
   with a mock transport. Keep recorded financial values attributable to the
   selected service, subscription instance and date.
2. Read and normalize LBX recommendation details in the common reconciliation
   path. Unconfirmed financial data does not create a new allowance or renew
   a prior trust deadline. Timely negative lifecycle facts still take effect.
3. Verify paid, underfunded, delayed and contradictory data, including first
   local observation, the existing monthly profile and persisted allowance
   identity. Record checks on the tested local base.

## Local verification

- The unfunded regression failed before the fix because a complete active
  provider read produced `GRANT` while the current day was underfunded.
- On draft head `8d4d0781`, with the funding patch applied, 823 LBX, billing,
  architecture and repository documentation tests passed. Seven isolated
  PostgreSQL tests passed, covering first observation, preservation of prior
  trust during underfunding, stable late issuance and the monthly baseline.
  Ruff and the documentation checker passed.
- CI and a live check of the combined change on LBX 043 are pending.
