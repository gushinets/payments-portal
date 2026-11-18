# ANY-832 — LBX 043 annual calendar evidence

Status: implementation note
Observed: 2026-11-18
Scope: the first paid cycle of a one-year LBX offer anchored to the first day of the month.

## What we observed

On stand 043, the [test tariff](https://043.lbxbilling.ru/lbxaas-admin/tariffs/30)
used `float_period=0` (first day of the month). The
[test subscription](https://043.lbxbilling.ru/lbxaas-admin/subscriptions/55)
had `period_type=4` and `period_length=1` (one year). It activated after a
20 RUB test balance entry. LBX recorded a 10 RUB annual charge and a separate
10 RUB connection charge. No external payment system was used.

An authenticated Server API read of the active subscription returned:

```json
{
  "subscription_start_date": "2026-11-18 00:00:00",
  "subscription_end_date": "2027-11-17 23:59:59",
  "subscription_instance_start_date": "2026-11-18 00:00:00",
  "subscription_instance_end_date": "2027-11-17 23:59:59",
  "last_tariffication_period_start": "2026-11-01",
  "last_tariffication_period_end": "2027-10-31"
}
```

The subscription covers a full year from activation. The November 1 boundary
belongs to the allowance cycle. Before this correction, Portal's calendar
containment check rejected the date-only period starting before the local
activation timestamp, and normalization could not form a date-only anchor.
Product access could remain eligible while the allowance was omitted.

## Decision and behavior

Keep the annual offer supported. For the observed
`year / 1 / calendar_month` profile with two date-only cycle bounds, interpret
a local midnight activation timestamp as a calendar date when checking the
cycle. The integration derives the first day of that month and permits the
first proven cycle to begin at that boundary. The existing classifier still
checks duration, phase and history. The source timestamps and dates remain
unchanged in retained observations.

Eligible, active source proof can issue the full fixed allowance from the
accepted offer. The subscription lifetime still follows its own LBX evidence.
This profile creates no inferred UTC start, end or grant deadline. A reread of
the same cycle reuses the frozen allowance and its ID, which preserves its
association with existing usage in Kernel. A later qualifying cycle must be
confirmed by LBX before Portal can issue a new allowance. Contradictory cycles
or unsupported precision still fail closed for the affected allowance.

The [PostgreSQL regression](../../apps/api/tests/test_paid_access_reconciliation_postgres.py)
replays the observed first cycle through the HTTP adapter and the allowance
writer. It checks issuance, stable identity on reread and a simulated next
cycle. The stand observation covers the first paid cycle only. Renewal and
production rollout acceptance were outside this check. The accepted
[B10 specification](../superpowers/specs/2026-09-15-external-billing-boundary-design.md#b10-and-immutable-authority)
continues to govern source evidence and immutable allowance identity.
