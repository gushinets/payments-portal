# Payments Portal <-> Platform Kernel access contract

Status: review requested after seventh external-review amendments  
Date: 2026-09-15

## Purpose

This companion design contains the cross-repository wire contract between
Payments Portal and Platform Kernel for paid-access projection, cache fencing,
and fast invalidation.

The billing-boundary design remains authoritative for commercial ownership,
provider integration, recovery, sellability, and entitlement derivation. This
file deliberately contains no LBX concepts, provider IDs, balances, payment
states, or billing-specific lifecycle values.

The contract has two required operations in MVP:

```text
Kernel -> Portal: GET AccessSnapshot
Portal -> Kernel: POST AccessInvalidation
```

Platform Kernel never calls External Billing directly.

## Scope key

Every access value is scoped by:

```text
(tenant_id, region, user_id)
```

For AnyToolAI RU MVP:

```text
tenant_id = anytoolai
region    = ru
```

The same contract is reusable for other regional contours. A regional service
must reject a request whose region does not match the contour it serves.

## Service authentication

Both operations are internal service-to-service APIs. User authentication is not
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

## AccessSnapshot

### Request

Recommended MVP route:

```http
GET /internal/v1/access-snapshots/{user_id}?tenant_id=anytoolai&region=ru
```

The caller is Platform Kernel.

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
snapshot.

Portal must not include a paid fact after its provider projection trust deadline.
Kernel must use an allowance only while `now` belongs to its half-open UTC period
`[period_start, period_end)` and the parent snapshot remains valid.

## AccessInvalidation

### Request

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

## Quota ownership

Platform Kernel owns durable actual usage. For each allowance independently:

```text
remaining = max(0, allowance.quantity - durable_usage[allowance_id])
```

Consumption must be atomic and must not exceed the allowance under concurrency.
Restart preserves used quantity. Two metric allowances never share a runtime
counter merely because they came from one provider billing cycle.

Portal never stores authoritative runtime remaining quota.

## Versioning

All payloads carry `schema_version`.

MVP rules:

- incompatible/unsupported major schema is a contract error;
- consumers fail clearly rather than guess missing semantics;
- contract tests live in both repositories;
- do not introduce a shared runtime Python package that couples Portal and
  Kernel releases.

## Required contract proofs

The implementation plan must cover at least:

- snapshot N rejected after floor N+1 is learned;
- concurrent N+1 then delayed N cannot regress cache/floor;
- duplicate invalidation is idempotent;
- outbox survives crash after Portal commit;
- N pending plus N+1 committed may coalesce to N+1;
- invalidation outage still fails closed through snapshot expiry;
- stale one-product fact can be omitted while independent product access remains;
- concurrent Kernel quota consumption cannot exceed allowance quantity.

## Result

The cross-repository boundary is intentionally small:

```text
Payments Portal
  complete AccessSnapshot producer
  monotonic access_revision owner
  durable coalesced AccessInvalidation sender

Platform Kernel
  AccessSnapshot cache/client
  monotonic revision floor
  invalidation receiver
  durable actual usage and quota enforcement
```

Nothing in this contract makes Platform Kernel a billing-system client.
