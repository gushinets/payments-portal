# Payments Portal <-> Platform Kernel access contract

Status: review requested after eighth external-review amendments  
Date: 2026-09-15

## Purpose

This companion design contains the cross-repository wire contracts between
Payments Portal and Platform Kernel for technical capability discovery, paid
access projection, cache fencing, and fast invalidation.

The billing-boundary design remains authoritative for commercial ownership,
provider integration, recovery, sellability, and entitlement derivation. This
file deliberately contains no LBX concepts, provider IDs, balances, payment
states, or billing-specific lifecycle values.

The contract has three required operations in MVP:

| Operation | Host | Caller |
|---|---|---|
| `GET /internal/v1/capability-manifest` | Platform Kernel | Payments Portal |
| `GET /internal/v1/access-snapshots/{user_id}` | Payments Portal | Platform Kernel |
| `POST /internal/v1/access-invalidations` | Platform Kernel | Payments Portal |

These routes intentionally live in different services. Capability discovery is
Kernel -> Portal at the domain level: Kernel defines technical vocabulary and
Portal consumes it. AccessSnapshot is pulled by Kernel from Portal.
AccessInvalidation is only a Portal -> Kernel cache-fencing delivery path; it
does not make Kernel a billing-system client.

Platform Kernel never calls External Billing directly.

## Scope key

Every cross-service value is scoped by tenant and region. User access values add
`user_id`:

```text
capability manifest: (tenant_id, region)
access state:         (tenant_id, region, user_id)
```

For AnyToolAI RU MVP:

```text
tenant_id = anytoolai
region    = ru
```

The same contracts are reusable for other regional contours. A regional service
must reject a request whose region does not match the contour it serves. Region
in the request is a validation guard, not a mechanism for cross-contour routing.

## Service authentication

All operations are internal service-to-service APIs. User authentication is not
sufficient.

Required properties:

- TLS in transit;
- explicit trusted-service authentication;
- tenant and region authorization;
- no browser access to these internal endpoints;
- no cross-region read or invalidation.

The concrete credential format should reuse the deployment's internal service
authentication mechanism. This design does not introduce a separate auth system
only for billing access.

## Capability Manifest

### Request ownership

Platform Kernel hosts the manifest endpoint. Payments Portal is the caller.

```http
GET /internal/v1/capability-manifest?tenant_id=anytoolai&region=ru
```

### Response

```json
{
  "schema_version": 1,
  "tenant_id": "anytoolai",
  "region": "ru",
  "manifest_version": "sha256:...",
  "generated_at": "2026-09-15T12:00:00Z",
  "products": [
    {
      "product_id": "document-summary",
      "enabled": true
    }
  ],
  "usage_metrics": [
    {
      "metric_key": "document-summary.generations",
      "product_id": "document-summary",
      "unit": "generation",
      "enabled": true
    }
  ]
}
```

Kernel validates before serving that:

```text
product_id is unique
metric_key is unique
metric_key -> exactly one existing product_id
```

`manifest_version` changes deterministically on semantic manifest changes.

The response is all-or-nothing. Kernel returns `200` only for a complete valid
manifest. It does not return a partial `200`.

### HTTP semantics

```text
200 -> complete valid manifest
401 -> missing/invalid service authentication
403 -> authenticated caller not authorized for tenant/region/scope
5xx -> Kernel cannot produce a complete valid manifest
```

### Portal import and freshness

Portal targets refresh at startup and approximately every five minutes. It keeps
a last-known-good projection.

`capability_manifest_last_complete_sync_at` advances only after all of these
succeed:

```text
HTTP 200
supported schema_version
full payload validation
all product/metric references valid
atomic local projection commit
```

Timeouts, `5xx`, malformed/partial responses, unsupported schema, broken
metric-to-product references, or local projection transaction failure do not
advance freshness and do not partially replace the prior projection.

The billing-boundary design applies:

```text
new_sales_projection_max_age = 24h
```

A manifest older than that blocks new sales and new mapping publication, but
does not silently rewrite or revoke already-pinned historical mappings or paid
access.

## AccessSnapshot

### Request ownership

Payments Portal hosts the snapshot endpoint. Platform Kernel is the caller.

```http
GET /internal/v1/access-snapshots/{user_id}?tenant_id=anytoolai&region=ru
```

### Response

```json
{
  "schema_version": 1,
  "tenant_id": "anytoolai",
  "region": "ru",
  "user_id": "uuid",
  "access_revision": 184,
  "authoritative_as_of": "2026-09-15T12:00:00Z",
  "refresh_after": "2026-09-15T12:01:00Z",
  "expires_at": "2026-09-15T12:05:00Z",
  "grants": [
    {
      "product_id": "document-summary",
      "valid_until": null
    }
  ],
  "allowances": [
    {
      "allowance_id": "opaque-uuid",
      "product_id": "document-summary",
      "metric_key": "document-summary.generations",
      "quantity": 1000,
      "period_start": "2026-09-01T00:00:00Z",
      "period_end": "2026-10-01T00:00:00Z"
    }
  ]
}
```

No provider-specific values may appear in this response.

`AccessSnapshot` is a complete current effective set, not a delta. If Product A
is absent while Product B is present, A is denied and B remains allowed.

### Immutable semantic state per revision

One `access_revision` identifies one immutable semantic effective access state.
For two successful responses with the same revision, the authorization-relevant
contents of `grants[]` and `allowances[]` must be identical, including grant
boundaries and allowance identity, product/metric binding, quantity, and period
bounds.

Any add, omission, or material change to an effective grant or allowance must be
committed first as:

```text
new effective access state
+ access_revision N+1
+ durable AccessInvalidation N+1
```

A GET serializes already-committed effective state; it never silently changes the
effective set while retaining the same revision.

Freshness metadata may be recomputed without changing the revision when semantic
access is unchanged:

```text
authoritative_as_of
refresh_after
expires_at
```

### Snapshot time semantics

MVP defaults:

```text
refresh_after = now + 1m
expires_at = min(
  now + 5m,
  deadlines of source facts actually included,
  included grant terminal boundaries,
  included allowance boundaries where relevant
)
```

A stale/expired/conflicted fact is omitted instead of invalidating unrelated
facts. Once omitted, its old deadline does not shorten the newly materialized
snapshot. The omission itself is a semantic access change and therefore requires
a new revision before the GET can return it.

Portal must not include a paid fact after its provider projection trust deadline.
Kernel must use an allowance only while `now` belongs to its half-open UTC period
`[period_start, period_end)` and the parent snapshot remains valid.

### HTTP semantics

For a canonical Portal user known in the requested tenant/region, Portal always
returns `200` with a complete versioned snapshot. This includes users with no
current paid access:

```json
{
  "access_revision": 185,
  "grants": [],
  "allowances": []
}
```

An empty paid-access set is therefore not `404` and not `204`.

```text
200 -> known user, complete current snapshot, possibly empty
404 -> canonical user_id is unknown in the requested tenant/region
401 -> missing/invalid service authentication
403 -> authenticated caller not authorized for tenant/region/scope
5xx -> Portal cannot produce a valid complete snapshot
```

`404` never means "known user with no entitlement". If Kernel previously accepted
snapshots for the same scoped user and later receives an unexpected `404`, it
treats that as an integration anomaly, alerts, and uses only a still-valid cached
snapshot until its existing `expires_at`; after expiry paid access fails closed.

For timeout/transport/`5xx`, Kernel may use an already-accepted cached snapshot
only while that snapshot remains within its existing validity. Kernel never
locally extends `expires_at`. Without a valid cache, or after expiry, paid access
fails closed.

`401`/`403` are service auth/configuration failures, not entitlement results, and
must not be converted into an empty snapshot.

## AccessInvalidation

### Request ownership

Platform Kernel hosts the invalidation endpoint. Payments Portal is the caller.

```http
POST /internal/v1/access-invalidations
Content-Type: application/json
```

Payload:

```json
{
  "schema_version": 1,
  "tenant_id": "anytoolai",
  "region": "ru",
  "user_id": "uuid",
  "access_revision": 184
}
```

The payload is only a cache-fencing hint. It contains no grant or allowance
delta and no billing reason.

### Success semantics

Kernel applies the invalidation atomically inside the same per-user coherence
domain as snapshot cache installation:

```text
floor = max(highest_seen_access_revision, request.access_revision)

if cached_snapshot.revision < floor:
    evict cached snapshot
```

After successful application Kernel returns:

```http
204 No Content
```

The endpoint is idempotent. A repeated or lower revision is a successful no-op
and also returns 204.

## Kernel monotonic revision floor

Kernel persists or otherwise durably/coherently maintains
`highest_seen_access_revision` independently from the snapshot cache for each:

```text
(tenant_id, region, user_id)
```

The floor only increases:

```text
floor = max(floor, received_invalidation_revision)
floor = max(floor, accepted_snapshot_revision)
```

When a snapshot response arrives:

```text
if response.access_revision < floor:
    reject response
    do not cache it
    do not authorize from it
else:
    raise floor if needed
    install response only if cached revision cannot regress
```

The stale check, floor update, and cache installation must be atomic relative to
invalidation for that user.

Therefore this race is forbidden:

```text
snapshot N request starts
Portal commits N+1
Kernel receives invalidation N+1
snapshot N response arrives late
-> N is rejected and cannot resurrect access
```

If Portal repeatedly returns a snapshot below Kernel's known floor, Kernel never
downgrades. It retries with bounded internal policy and paid access fails closed
if a snapshot at or above the floor cannot be obtained.

## Portal invalidation outbox

Every material access change is committed with the new user revision and durable
invalidation work in one PostgreSQL transaction:

```text
persist effective access change
access_revision = N + 1
upsert pending invalidation revision = N + 1
COMMIT
```

A process crash immediately after commit must not lose delivery work.

### Coalescing

Invalidation is not an event log. For one scope key, Portal may retain only the
maximum pending revision:

```text
pending_revision = max(pending_revision, new_revision)
```

For example, pending 181, 182, and 183 may be delivered as only 183.

Conceptual delivery state is sufficient:

```text
tenant_id
region
user_id
pending_revision
attempt_count
next_attempt_at
last_error
delivered_revision
updated_at
```

A separate row for every revision is not required for delivery. Access audit
lives in Portal's business/reconciliation state.

## Delivery and retry semantics

Delivery is at-least-once. Portal's durable worker POSTs the latest pending
revision until Kernel confirms success.

Retryable outcomes include:

```text
connection failure
timeout
HTTP 429
HTTP 5xx
```

Use bounded exponential backoff with jitter, conceptually:

```text
1s -> 5s -> 15s -> 1m -> 5m -> 15m ...
```

The durable row is not discarded because an attempt count was exceeded.

If revision N is still pending and N+1 is committed, the next delivery may send
only N+1.

Permanent/configuration outcomes include malformed contract, unsupported schema,
service-auth failure, or region/tenant mismatch. They must:

- remain durably unresolved;
- stop hot-loop retry;
- alert/on-call;
- resume after configuration/deployment repair.

## Correctness backstop

Push invalidation is a fast convergence and stale-cache-fencing mechanism, not
the sole safety mechanism.

Correctness also depends on:

```text
AccessSnapshot.refresh_after
AccessSnapshot.expires_at
temporal-boundary refresh
complete snapshot replacement semantics
```

If invalidation delivery is delayed, Kernel may continue only within the already
issued snapshot's valid temporal bounds. After expiry it must fail closed for
paid access it cannot refresh.

## Quota ownership and allowance-ledger lifetime

Platform Kernel owns durable actual usage. For each allowance independently:

```text
remaining = max(0, allowance.quantity - durable_usage[allowance_id])
```

Consumption must be atomic and must not exceed the allowance under concurrency.
Restart preserves used quantity. Two metric allowances never share a runtime
counter merely because they came from one provider billing cycle.

The usage ledger lifetime is independent of whether an allowance is present in
the current AccessSnapshot. Omission, financial block, snapshot expiry, or cache
eviction stops current authorization but never deletes or resets accumulated
usage for that `allowance_id`.

If the same allowance reappears after a same-cycle unblock, Kernel resumes the
same durable counter. Only a genuinely new `allowance_id` creates a fresh usage
bucket starting at zero. Historical usage rows are retained at least longer than
any possible reappearance of that allowance; MVP may retain them without
automatic deletion.

Portal never stores authoritative runtime remaining quota.

## Versioning and contract fixtures

All payloads carry `schema_version`.

MVP rules:

- incompatible/unsupported major schema is a contract error;
- consumers fail clearly rather than guess missing semantics;
- contract tests live in both repositories;
- do not introduce a shared runtime Python package that couples Portal and
  Kernel releases.

Canonical JSON contract fixtures are checked in with Payments Portal tests.
Platform Kernel vendors a hash-checked copy for producer/consumer compatibility
proofs. Intentional contract changes update the canonical fixture and expected
SHA-256 copy together. This is test data only, not a shared runtime package or a
cross-repository runtime dependency.

## Required contract proofs

The implementation plan must cover at least:

- same `access_revision` cannot return a different semantic grants/allowances set;
- snapshot N rejected after floor N+1 is learned;
- concurrent N+1 then delayed N cannot regress cache/floor;
- known user with no access returns `200` with empty arrays and committed revision;
- entitlement absence never produces `404`;
- unexpected `404` for a previously known user does not erase a still-valid cache;
- duplicate invalidation is idempotent;
- outbox survives crash after Portal commit;
- N pending plus N+1 committed may coalesce to N+1;
- invalidation outage still fails closed through snapshot expiry;
- stale one-product fact can be omitted while independent product access remains;
- same allowance omitted during block and restored during same cycle keeps the
  same accumulated usage;
- cache eviction does not delete allowance usage;
- concurrent Kernel quota consumption cannot exceed allowance quantity;
- capability-manifest partial/invalid sync keeps prior LKG and does not move
  `last_complete_sync_at`;
- hash-checked contract fixtures cannot drift silently between repositories.

## Result

The cross-repository boundary is intentionally small:

```text
Platform Kernel
  Capability Manifest producer
  AccessSnapshot cache/client
  monotonic revision floor
  AccessInvalidation receiver
  durable actual usage and quota enforcement

Payments Portal
  Capability Manifest consumer/LKG projection
  complete AccessSnapshot producer
  monotonic access_revision owner
  durable coalesced AccessInvalidation sender
```

Nothing in this contract makes Platform Kernel a billing-system client.
