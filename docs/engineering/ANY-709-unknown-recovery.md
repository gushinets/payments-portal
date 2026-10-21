# ANY-709 preparation and UNKNOWN recovery

Status: implemented local SIMULATED workflow; human verification pending.

`POST /api/purchases/{id}/continue` resumes the authenticated owner's existing
intent. `GET /api/purchases/{id}` and
`GET /api/billing/products/{product_id}/status` read PostgreSQL only. Product
status returns the owned intent ID so reload can resume the same operation.
Neither status nor `manage` authorizes a Widget credential or paid access.

Every never-sent operation compares the original accepted review through the
existing live Kernel HTTP and recorded LBX selected-offer path. The current
account date must still equal the accepted start date. Missing proof, material
drift, a date rollover or an ineligible user pauses the intent before POST.
Consent and the accepted snapshot are never rewritten.

The committed `unsent -> possible_send` claim owns the one POST permission,
send fence, ownership epoch and fixed two-hour recovery work item. A crash
between that commit and the first packet is still potentially sent. A receipt
alone cannot bind anything: current point GET must prove identity, owner,
seller, correlation and all material subscription terms. Dedicated agreement
identity is bound uniquely before subscription CREATE. The prepared link has
an expired, access-denying projection and no financial-state observation or
allowance. These defaults do not assert a measured provider financial state.

## Operator calls

Use the existing `purchase_application(configuration, factory, sources)`
composition in a controlled operator process on its resource-owning event
loop. Its `preparation` object exposes these deliberately private calls; there
is no public operator HTTP route or background scheduler in this slice:

- `await preparation.advance(user_id, intent_id, read_only=True)` performs only
  discovery/point GETs for previously claimed operations and binds a unique
  complete match. It stops at an unsent stage. No Kernel admission read or
  current profile load is required for recovery.
- `await preparation.inspect(user_id, intent_id)` performs bounded read-only
  discovery for the next unresolved operation, including a manual-review case.
  It returns private typed proof and never binds, sends or releases anything.
- `preparation.escalate_overdue(user_id, intent_id, principal="<audited operator>")`
  synchronously creates/coalesces a manual-review case for an overdue
  `possible_send`/`unknown`, completes its due item and retains the hold. It is
  idempotent. A worker does **not** execute this call yet; Step 8 owns scheduling.

Recovery capacity is separate from new-sale preflight capacity. Commands and
the SIMULATED preparation profile are pinned in the operation recovery
document; no credentials are persisted there. The recording directory must
remain available. Test recordings use fixed provider IDs and explicit opaque
correlation/date substitutions, so they are a single-account scenario fixture,
not a multi-customer provider emulator or production evidence.

Zero discovery results retain UNKNOWN and the original deadline. Multiple,
conflicting or incomplete candidates enter manual review. Network unavailability
retains UNKNOWN. No branch repeats a possibly sent POST, including after
process restart, browser close, source outage or deadline expiry. Definite
pre-send authentication/validation refusal leaves the unsent operation without
a send clock. A definite pre-send failure following a committed claim is
recorded separately and handed to review; it never restores send permission.

## Release and late objects

Use the existing audited `release_purchase_scope` API only with authoritative
no-effect proof, a verified terminal link plus no other unresolved operations,
or explicit audited support evidence. Payment state, elapsed time and empty
discovery are not no-effect proof. An unpaid prepared subscription retains its
hold indefinitely. Support must reconcile all customer/product create records
and retain proof/principal/observation time in the append-only release audit.

A late response must pass the recorded send fence and current hold epoch.
Changed ownership or a conflicting provider binding creates a manual-review
case, retaining evidence and denying progression. A repeated proof of the same
already-bound object is harmless. A late external object discovered after an
audited release requires support review; it cannot become a fresh send,
automatic scope reassignment or paid access.

## Human verification

Tests were written but not executed by the implementation agent. Run from the
repository root:

```bash
make test_db_up
npm run test:api:postgres
npm run test:api:fast
make test_db_stop
```

Focused evidence lives in `apps/api/tests/test_purchase_preparation_postgres.py`
and `apps/api/tests/test_purchase_preparation_contracts.py`: committed claims
before I/O, 200/201 receipts plus point proof, restart, lost commit acknowledgement,
concurrency, zero/one/multiple discovery, drift/date/ownership refusal, explicit
two-hour escalation, DB-only status and expired access-denying links.
