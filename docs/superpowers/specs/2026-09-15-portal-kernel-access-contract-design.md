# Payments Portal <-> Platform Kernel access contract

Status: accepted implementation baseline  
Date: 2026-09-15

Amended 2026-10-20: the owner-approved
[live-source commercial admission amendment](2026-10-15-live-source-commercial-admission-design-amendment.md)
supersedes Portal manifest mirroring and catalog-age admission only. Manifest
wire semantics, AccessSnapshot, AccessInvalidation and paid-access trust remain unchanged.

## ANY-766 consumer-neutral amendment — 2026-11-10

Status: **Steps 10/11 identity and technical sources implemented (2026-11-11); remaining consumer-neutral
runtime work is planned.** Common delegation V2, configured callbacks, the
persisted policy guard and generated identity security are implemented. Snapshot
remains Kernel-only V2; Step 11 implements source/owner routing and historical
serialization compatibility. Filtering/P/R coherence is Step 12 and
recipient routing Step 13. The implementation status is recorded in the guide
and active plan; historical baseline sections below do not restore old routes.
The [common product backend API guide](../../contracts/product-backend-api/README.md)
and [paired schemas/fixtures](../../contracts/portal-kernel-paid/README.md)
are the normative consumer-neutral target. The guide records complete safe
identity/access examples, operation permissions, source/owner versioning,
bounded replacement/migration owners and local acceptance cases. The working
identity/access/OpenAPI handoff is Step 12 (2026-11-13 priority), not this
specification checkpoint. Delivery/usage remain Steps 13–15; assembled local
acceptance is Step 16, build/install preparation Step 17 and remote/live work
ANY-767. Document Summary adoption belongs to its own team.

This amendment supersedes only the Kernel-exclusive consumer/source/audience,
V2 snapshot semantic identity, single-recipient assumptions and unrestricted
historical-allowance fallback below. Its breaking wire cutover also replaces
unqualified independent-rollout wording. Kernel execution/product behavior,
ANY-507 ownership/replay, purchased history,
commercial gates and every unrelated accepted baseline rule remain unchanged.
No runtime route, setting, migration or generated OpenAPI changes in Step 9.

### Consumer identity and delegation V2 target

Configure a small explicit set of consumers with independent current/previous
backend-to-Portal credentials, separate Portal-to-backend credentials, canonical
consumer_id/tenant/region, product scope, permissions, fixed callback and technical
source/backend owner. Kernel is platform-kernel, with the same protocol as a
synthetic second consumer; no registration/admin API or external backend build.
Trusted service identity selects consumer; request fields only narrow authority.

Replace the Portal Kernel-named routes with POST /api/backend-session-codes,
/internal/v1/backend-sessions/exchange and
/internal/v1/backend-sessions/introspect; use localized /[locale]/backend/authorize.
Code request adds consumer_id (code-request-v2, no schema_version field); code
response and exchange/introspection requests retain V1 shape. Exchange and
introspection responses use integer schema_version=2 and add consumer_id and
strict positive consumer_policy_revision P. Use backend-session:exchange and
backend-session:introspect permissions. Preserve one-use S256, 60-second code,
hash-only parent linkage, min(30-minute,parent) token lifetime, parent revocation,
active-user checks, no PII/primary-bearer forwarding, secret-safe errors/no-store,
fixed callback and tab custody/recovery. Cross-consumer redemption/introspection
fails. Kernel's local launch/callback/exchange names may stay. Keep Core owner
and accepted replay unchanged; invalidate incompatible browser tokens while
preserving same-owner pending request/key. Step 10 owns the synchronized change.

### Snapshot V3 and independent P/R target

Keep GET /internal/v1/access-snapshots/{user_id} with explicit tenant_id/region.
V3 retains grants/allowances and adds consumer_id/P. R remains whole-user paid
access_revision; semantic identity is consumer/tenant/region/user/P/R. Identical
identity freezes grants and tuples apart from envelope refresh/expiry. Filter
products plus supporting provenance/deadlines before completeness/expiry checks;
unrelated overdue products do not deny service, included overdue facts return
503 until the existing writer commits reduction. Response filtering after
whole-user require_current is insufficient. Preserve sole writer/cabinet rules,
read-only empty R0, later positive empty R, B10/finite-source-trust/clock bounds
and no local authority extension or inferred cycle.

Persist current P/digest in consumer-scoped Portal configuration guard state.
Initial migrated Kernel P is 1. Digest canonicalization and field inventory are
fixed in the guide/bundle; authorized product/snapshot-scope changes require
higher P, and changed reused versions/rollback fail. Rotation alone changes no
snapshot meaning. Every introspection returns current P. Extend existing backend
coherence identity/lock with consumer and independent durable P/R floors; install
and admission match current introspected P and preserve monotonic R, including
post-wait checks. Old-P responses cannot restore old policy. Eviction retains
both floors. Do not add consumer/P/R to usage buckets, jobs or accepted replay.
Quantity is purchased ceiling, never remaining or atomic execution permission;
backends own durable reserve/finalize/release/recovery. Step 12 implements V3.

### Technical ownership, delivery and migration target

Step 11 replaces unconditional require_kernel with configured manifest V1 source
selection. One product has one backend execution/usage owner. New link/terms/
acceptance documents use new versions with technical_source_id/backend_consumer_id;
old documents, model_dump serialization, both consent digest variants,
SIMULATED labels, quantities, allowance IDs and same-cycle usage stay exact.
Missing legacy owner/source resolves to Kernel only in a separate in-memory
view; no JSON rewrite, default-field hash change, owner transfer or usage reset.

Step 13 partitions existing outbox/work uniqueness, coalescing, claims, retries,
parking, repair and delivered R by recipient plus scoped user. Fan out R in the
sole writer transaction, including grant removal. Keep invalidation V1; endpoint
authentication selects recipient. ACK N affects only that recipient through N,
retaining N+1; policy is fenced by introspection/P, not a second event protocol.
Steps 14/15 reuse V1 usage/exhaustion for all backends: route usage by saved owner,
check authenticated exhaustion consumer/product plus full immutable tuple and
ACK only after durable deduplicated hint commit. Unknown remains unobserved,
outage unavailable, busy distinct from exhausted; no Portal meter/financial action.

Extend Portal head 20261110_0008 and Kernel head 0019 with populated-state forward
migration checks. Quiesce both APIs/workers for synchronized cutover; preserve
parent delegation bindings/hashes/state, initialize Kernel consumer/P, retain R
floor while clearing incompatible cache metadata, and bind old outbox/work to
Kernel with exact pending/delivered revisions. Retire stale claims only after
workers stop and prove repair resumes unresolved delivery. Preserve purchases,
digests, prepared starts, buckets/usage/replay; exclude obsolete binaries from
installation. No concurrent old wire route or translation layer is required.

FastAPI/Pydantic and the existing generator remain runtime OpenAPI authority.
Step 9 leaves generated artifacts unchanged and documents missing named Bearer
schemes/per-operation security/descriptions. Steps 10/12 add security, schemas,
safe examples/errors and regenerate actual routes. Swagger never permits exposing
service keys to external browsers. Reverse backend endpoints are documented as
backend obligations, not fabricated Portal operations.

## ANY-766 selected contracts — 2026-11-09

Status at Step 1 formalization: **formalized target; runtime implementation was pending**.
Current implementation status and acceptance limits are recorded in the
[active ANY-766 plan](../../exec-plans/active/ANY-766-implementation-plan.md).
The accepted
2026-11-03 strategy and 2026-11-09 scope clarification in
[ANY-766](https://linear.app/paveldik/issue/ANY-766) are implemented by these
concrete contracts. Their technical review belongs to Step 1; no additional
preliminary protocol approval is required. This does not claim that the owner
historically approved these exact field names, or that paid HTTP is delivered.

This section supersedes the preserved September baseline below **only** for
snapshot version/allowance tuple/clock rules, session delegation and recovery,
coherence/admission/ownership/events, and usage/exhaustion/cabinet delivery.
In particular, the old three-operation inventory is incomplete for ANY-766;
its V1 period-bearing snapshot, UTC allowance tuple and interval admission
predicates must not be implemented as the selected target. Manifest and
invalidation remain V1. Billing ownership, source trust, revision semantics,
same-cycle history, request-driven refresh and exact-N ACK remain in force.

The normative field inventory, schemas, operation permissions, positive/negative
fixtures and semantic validation rules are in the
[paired target contract bundle](../../contracts/portal-kernel-paid/README.md).
Its `contract-index.json` distinguishes payload producer from route host. Portal
owns snapshot/invalidation/identity fixtures; Kernel owns usage/exhaustion and
usage query input contracts. Both independently validate
hash-checked copies. No shared runtime package is introduced. Applications keep
separate databases, builds and deployment ownership. The consumer-neutral wire
cutover in the 2026-11-10 amendment requires coordinated Portal, Kernel and browser
updates; independent updates require compatible versions.

### B10 snapshot V2

Keep `GET /internal/v1/access-snapshots/{user_id}?tenant_id=anytoolai&region=ru`.
The target producer serves only integer `schema_version: 2`, canonical
tenant/region/user, access_revision, refresh_after, expires_at, grants and
allowances. A grant is product_id + nullable conservative UTC valid_until. An
allowance is allowance_id + product_id + metric_key + **unit** + quantity.

The immutable tuple is tenant/region/user/allowance/product/metric/unit/quantity.
No period_start/period_end is exported or required by Kernel. LBX calendar proof
and independently supported UTC bounds stay Portal-internal. Committed snapshot
membership authorizes a bucket; its identity/history outlives omission. Future
facts are not exposed before a proven start; schedule authoritative reconciliation
at that boundary. Local clock progression cannot create new positive authority
or prove renewal. Same-cycle recovery reuses the same ID/quantity/usage; refill
requires a proven new cycle.

For local/staging B=5 seconds and Portal database time T:

```text
expires_at = min(T+300 seconds, all included effective source/grant/proven UTC deadlines) - B
refresh_after = min(T+60 seconds, expires_at)
```

With no included facts, only T+300 applies. Wire grant deadlines are conservative;
subtract the cross-service budget once, without reapplying it to a wire bound
already reduced by B. Existing LBX conservatism remains separate. A deployment
must support the budget; fixture arithmetic is no production-clock proof.
Quantity is a strict JSON integer in 0…2^53−1, rejecting bool/float/lossy values.

Retain read-only implicit empty revision zero, positive later empty revisions,
semantic immutability per revision, source trust no longer than six hours and
overdue-boundary refusal. GET performs neither source/Kernel I/O nor state writes;
`503` means no complete currently valid document. Known empty users return `200`,
unknown scoped users `404`. Service `401/403` and unexpected `404` remain
integration failures. Request-driven refresh may retain accepted cached authority
only while still valid, above the durable floor and satisfying all predicates;
never extend expiry. Install compatible consumers before connecting V2. No V1
translation invents period semantics.

### Scoped delegation and recoverable launch

Kernel `/portal-session/launch` stores unpredictable state, S256 verifier and a
validated local product/result/handoff target in tab sessionStorage. Portal's
localized `/[locale]/kernel/authorize` authenticates its existing session.
The fixed Kernel `/portal-session/callback` receives code/state in the fragment,
clears it immediately and verifies state; no external callback is caller-selected.

Portal `POST /api/kernel-session-codes` accepts code_challenge and S256 method
under the Portal bearer, returning a random 32-byte code and 60-second expiry.
Kernel `POST /v1/portal-session/exchange` accepts code/verifier and forwards them
to Portal `POST /internal/v1/kernel-sessions/exchange` under service auth.
Atomic single-use PKCE exchange returns version 1, a narrow Bearer access_token,
canonical scope/user and expiry=min(issuance+30 minutes, parent-session expiry).
No refresh token exists. Portal
`POST /internal/v1/kernel-sessions/introspect` receives the token in a secret
body field with service authorization in the header. Every protected Kernel
request verifies audience, parent session and active user; the response contains
only version, canonical scope/user and conservative valid_until with B removed.

Invalid/revoked/expired delegation is `401`, with distinct safe codes for ordinary
delegated expiry and invalid/revoked parent authority; permission/scope refusal is
`403`, dependency failure `503`. See the bundle for the fixed codes. Store only
hashes in one AuthSession-linked kernel_session_delegations table with cascading
deletion. Security writes lock User → AuthSession → delegation; internal identity
reads do not commit. No second identity directory is introduced.

Keep delegated token/owner in tab sessionStorage, original Portal bearer only at
Portal. Extend CE-kit's prepared start with a versioned, owner-bound descriptor
containing original key/frozen request, persisted before a new send. Storage
refusal blocks only that new send. On an accepted response, replace it with a
session reference and remove frozen input. If that post-acceptance storage update
fails, preserve the accepted response; any retained pending descriptor remains
owner-bound and replays the original request/key until replacement succeeds or
private state is cleared. This failure never permits a new logical start.
Uncertain response/reload/normal token expiry retries
the same key/request after same-owner reauthorization. Different owner, logout or
parent revocation clears private state and pending inputs; discard late identity
generation responses. Rebuild the client on generation changes, preserve it
across ordinary remounts and restore the validated continuation without a new
logical start or guest fallback.

### Coherence, admission, resource ownership and events

Retain independent directional credentials and current/previous rotation slots
from ANY-711. Extend receiver-owned permissions per operation; a manifest-only
credential cannot invalidate or read usage. All internal routes require exactly
one Bearer, configured scope, verified TLS, no Origin/CORS and no-store on success
and errors. Codes, tokens, headers and PII never enter diagnostics.

Kernel stores floor/cache in one PostgreSQL coherence row per scoped user;
invalidation, installation and new admission lock that row. Eviction preserves
the floor. Admission order is canonical authentication → accepted owner/hash
replay → required HTTP refresh outside the business transaction → coherence lock
and repeated replay → server scenario metric/exact allowance → existing ANY-507
in the caller Session → post-bucket/reservation-wait DB wall-time and identity,
revision/floor, expiry and grant checks → one commit, or full rollback.

Preserve replay hashing/owner partition; allowance/revision are excluded from
replay meaning. Frozen-tuple conflict denies dependent metering without resetting
history. Protect start, handoff create/preview/accept/decline, poll, next-actions,
results/artifacts and client events with reservation/server deferred-handoff
ownership, never body user_id. Valid identity retains historical result access
after grant expiry; accepted jobs finalize against original buckets after
revocation/rollover. Checked in-flight requests may complete; new acceptance must
recheck identity expiry after waits. Retryable late handoff authority refusal
escapes the transaction, rolls back linkage/reserve and does not mark consent
terminally failed.

Extend ClientEventService with trusted paid owner, owner-checked scenario IDs,
server-derived user_id and pre-scenario authenticated product events. Preserve
guest validation/event-id deduplication. Events remain observational and cannot
authorize, finalize or debit.

### Usage, exhaustion and Portal display

Kernel `GET /internal/v1/usage/{user_id}` accepts tenant/region and 1–100 distinct
allowance_id parameters (`422` for malformed/repeated/excessive inputs). Version 1
returns canonical owner and one item per requested ID in request order.
Observed: complete allowance tuple, status=observed, successful_used, reserved,
remaining, available, UTC read_at. Unobserved: allowance_id/status only; foreign
and unknown are indistinguishable. Existing row-snapshot readback owns counters;
failure is `503`, not zero, and reads create no rows. Snapshot ingestion uses
ensure_usage for actual zero buckets. remaining=max(Q-successful_used,0),
available=max(Q-successful_used-reserved,0). Authenticated public
`GET /v1/products/{product_id}/paid-usage?allowance_id=...` derives owner through
introspection, restricts the product and retains historical reads without sales
enablement.

Write Kernel exhaustion V1 into a leased outbox in the SAME ANY-507 successful
finalization transaction when became_exhausted, including rollback recovery.
Payload: schema_version=1, event_type=allowance_exhausted, scope/user, complete
allowance tuple, occurred_at. Unique identity: scoped user + allowance ID + event
type. Existing worker delivery is independently bounded, sends outside SQL and
acknowledges only a live claim. Retry transport/429/5xx; park permanent faults.

Portal `POST /internal/v1/allowance-exhaustions` validates the issued full tuple,
commits one immutable deduplicated allowance_exhaustion work hint, THEN returns
`204`, including identical duplicate/historical deliveries. Duplicate coalescing
cannot revive completed hints. Unknown/mismatching tuple is `409`, malformed is
`422`. Current hints may schedule GET-only reconciliation; old-cycle hints finish
without changing a new cycle. No financial command, subscription/grant change,
refill or Portal usage ledger follows from this hint.

Portal invalidation reuses outbox/BillingWorkItem/embedded worker with an
independently bounded lane, exact-N monotonic acknowledgement, newer-generation
preservation, User → outbox → queue locks, HTTP outside locks, durable parking,
privileged inspect/retry and restart scheduling repair.

Separate Portal `GET /api/paid-usage` reuses the active verified-email billing
guard, server-derived scope and no-store responses. Derive current production
allowances locally. For each product without a current allowance, select its
most recently issued eligible historical allowance, ordered by `created_at` then
`allowance_id`. Eligibility requires compatible, proven `CONFIGURED_SOURCE`
technical terms and the saved product/metric/unit/quantity. Exclude SIMULATED
evidence, legacy rows without proven unit/terms, and future allowances awaiting
authoritative activation, even after their start boundary passes. Resolve the
persisted source/backend owner without rewriting history. No eligible allowance
means no item for that product; excluded rows cause no backend usage request or
invented tuple.

Backend I/O uses independent bounded resources outside SQL, preserving local
/api/paid-access capacity/cancellation ownership. Validate owner/IDs/tuples and
reread local access revision; change yields `503 paid_usage_state_changed`.
Named generated Portal DTOs include local terms, current/historical classification
and observed/unobserved/unavailable variants. Missing observations omit counters;
tuple mismatch is item-unavailable with diagnostics; dependency outage is `503`.
Never present invented zero/reset dates. Runtime Pydantic/OpenAPI/TypeScript
generation remains the existing boundary; fixture schemas do not implement it.

## Preserved September baseline

The original accepted text below is retained for traceability. Where explicitly
superseded above it describes the historical baseline, not the ANY-766 target.

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

For AccessSnapshot and AccessInvalidation, `user_id` is the canonical AnyToolAI
Portal user UUID carried by the authenticated identity flow. Platform Kernel must
use that canonical principal directly; it must not substitute a Kernel-local user
identifier or maintain a second billing-user mapping. The path parameter,
response body, invalidation payload, cache key, and revision floor all refer to
the same canonical Portal UUID.

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

### `enabled` semantics

`enabled` is admission control for new technical-commercial bindings, not a
runtime kill switch and not an entitlement-revocation signal.

A newly published mapping may reference only:

```text
product.enabled == true
and, for every mapped metric:
metric.enabled == true
metric.product_id == mapped product_id
```

Before every new purchase is pinned, Portal revalidates the referenced product
and metrics against the current fresh manifest. A previously published mapping
is not sufficient if the referenced capability is now disabled.

After a purchase has been pinned, a later `enabled=false` does not rewrite or
revoke that historical mapping, subscription, grant, or allowance. If Platform
Kernel needs an emergency/runtime suspension mechanism, it is a separate
Kernel-owned policy outside this manifest flag.

### HTTP semantics

```text
200 -> complete valid manifest
401 -> missing/invalid service authentication
403 -> authenticated caller not authorized for tenant/region/scope
5xx -> Kernel cannot produce a complete valid manifest
```

### Portal live admission

Portal fetches the complete authenticated manifest for each publication and
genuinely new purchase. Admission requires:

```text
HTTP 200
supported schema_version
full payload validation
all product/metric references valid
valid scope and deterministic manifest_version
selected product and metric enabled and correctly bound
```

Timeouts, `5xx`, malformed/partial responses, unsupported schema or broken
references refuse the new operation without a stored-manifest fallback. There
is no periodic/startup registry synchronization or 24h catalog-age permission.
Portal stores approved immutable bindings/terms and evidence in PostgreSQL;
catalog browsing reads only that stored state, with no source calls or current
sellability promise. Existing purchase retries/recovery follow the amendment.
Previously pinned mappings and paid-access facts are not rewritten or revoked
by a manifest admission failure. Subscription trust and AccessSnapshot caching
retain their existing separate deadlines.

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

`quantity` is a non-negative integer throughout the paid-access contract, Portal
storage/projection, fixtures, and Kernel quota ledger. Floating-point or decimal
representations, including integral-looking values such as `1000.0`, are invalid
contract data rather than alternate encodings of the same allowance.

`AccessSnapshot` is a complete current effective set, not a delta. If Product A
is absent while Product B is present, A is denied and B remains allowed.

The wire contract intentionally has no aggregate `authoritative_as_of` field.
Source-specific authoritative-read/projection timestamps remain internal to
Payments Portal. Kernel derives snapshot usability only from the revision,
`refresh_after`, `expires_at`, and explicit grant/allowance boundaries.

### Initial implicit revision zero

For every canonical Portal user known in the requested tenant/region, the initial
paid-access state is the implicit immutable empty state:

```text
access_revision = 0
grants = []
allowances = []
```

Revision zero does not require a persisted access-state row. `GET AccessSnapshot`
is read-only and must never INSERT/UPDATE access state merely to answer a request.

The first material paid-access change atomically creates committed revision `1`
and durable invalidation `1`. After any committed revision exists, that user never
returns to revision zero; a later empty effective set has its own monotonic
revision `N > 0`.

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
refresh_after
expires_at
```

### Snapshot time semantics and clock skew

Portal and Kernel have independent clocks. The deployment defines one positive
`clock_skew_budget` equal to the maximum tolerated absolute Portal<->Kernel clock
offset for this contract. Deployment validation requires the budget to be smaller
than the hard snapshot TTL. Portal publishes conservative authorization bounds;
Kernel compares received absolute timestamps with its own `now` and never adds
time or extends them locally.

For finite paid facts, Portal derives effective wire/authorization bounds
conservatively:

```text
effective source_trust_deadline = source projection_valid_until - clock_skew_budget
effective grant.valid_until = source valid_until - clock_skew_budget
effective allowance.period_start = source period_start + clock_skew_budget
effective allowance.period_end = source period_end - clock_skew_budget
```

A `null` `grant.valid_until` remains `null`; no arithmetic is applied to it and it
does not become an infinite provider-trust lease. Raw provider/source boundaries
remain internal to Portal. If the conservative haircut collapses a finite
interval, that paid fact is unusable and is omitted/fails closed rather than
widened.

For an already-issued `allowance_id`, the effective wire tuple is immutable. The
`clock_skew_budget` in effect when its effective `period_start`/`period_end` are
first committed is therefore part of how those frozen boundaries were derived.
A later deployment change to `clock_skew_budget` applies only when deriving future
allowance IDs; it must not rewrite the effective period bounds of an existing
`allowance_id`.

MVP snapshot defaults are:

```text
snapshot_hard_expiry = portal_now + 5m - clock_skew_budget

expires_at = min(
  snapshot_hard_expiry,
  effective source-trust deadlines of paid facts actually included,
  included effective finite grant.valid_until values,
  included effective allowance.period_end values
)

refresh_after = min(portal_now + 1m, expires_at)
```

Therefore `refresh_after` is never later than `expires_at`, and both the 5-minute
snapshot lease and the underlying source trust/period/grant deadlines are
conservative against the configured clock-skew budget.

A stale/expired/conflicted fact is omitted instead of invalidating unrelated
facts. The billing-boundary design requires deterministic due-boundary processing
through the existing Portal access-commit path, with no provider HTTP. When a paid
fact is committed or its effective deadline changes legitimately before issuance,
Portal schedules that same durable worker for the effective access-reducing
deadline rather than waiting for the 5m/15m provider-reconciliation cadence. An
overdue fact is removed by a new revision rather than by GET. GET itself remains
strictly read-only. If the due commit is temporarily late, the already-issued
snapshot remains expired and Kernel must not extend it; unrelated facts become
usable again when Portal commits the reduced effective set as the next revision.

Portal must not include a paid fact after its effective provider-projection trust
deadline. Kernel must use an allowance only while its own `now` belongs to the
received half-open UTC period `[period_start, period_end)` and the parent snapshot
remains valid.

### Request-driven refresh; no fleet poller

`refresh_after` is a cache-refresh hint, not a command to poll every user on a
fixed timer. Platform Kernel does not run a fleet-wide one-minute snapshot poller.

On a paid action:

```text
now < refresh_after
  -> current accepted cache may be used

refresh_after <= now < expires_at
  -> initiate/request refresh; the still-valid cached snapshot may authorize
     this action if all other predicates pass

now >= expires_at
  -> a fresh acceptable snapshot is required before paid authorization;
     otherwise fail closed
```

An invalidation revision floor always takes precedence over this timing behavior.

### HTTP semantics

For a canonical Portal user known in the requested tenant/region, Portal always
returns `200` with a complete versioned snapshot. A user with no prior material
paid-access transition returns the implicit empty revision zero:

```json
{
  "access_revision": 0,
  "grants": [],
  "allowances": []
}
```

A known user whose previous paid access has ended may instead return an empty
committed revision `N > 0`. An empty paid-access set is therefore never `404` or
`204`.

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

A `204` acknowledges only the revision carried by that concrete request. It does
not acknowledge a newer Portal revision that may have been committed while the
request was in flight.

## Kernel monotonic revision floor

Kernel persists or otherwise durably/coherently maintains
`highest_seen_access_revision` independently from the snapshot cache for each:

```text
(tenant_id, region, user_id)
```

The floor only increases and begins at zero:

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
invalidation work in one PostgreSQL transaction. Revision zero is implicit and
has no invalidation; the first material change is `0 -> 1`.

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

Delivery is at-least-once. Before each HTTP request, Portal's durable worker
captures the exact revision it is about to send:

```text
sent_revision = current pending_revision
```

The request payload contains `sent_revision`. A `204` permits only this monotonic
local acknowledgement:

```text
delivered_revision = max(delivered_revision, sent_revision)
```

Then, in a short transaction, Portal compares against the current pending value:

```text
if pending_revision <= delivered_revision:
    delivery is caught up
else:
    keep/schedule the row; a newer revision is still pending
```

Therefore a newer revision committed while an older request is in flight is never
cleared by the older `204`. A late acknowledgement for N after N+1 was already
acknowledged also cannot regress `delivered_revision`.

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

If revision N is still pending and N+1 is committed before the next send, that
next delivery may send only N+1. If Kernel applied a request but Portal crashes
before committing its acknowledgement, the same revision may be delivered again;
idempotency makes this safe.

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
temporal-boundary commits
complete snapshot replacement semantics
```

If invalidation delivery is delayed, Kernel may continue only within the already
issued snapshot's valid temporal bounds. After expiry it must fail closed for
paid access it cannot refresh.

## Quota ownership and allowance-ledger lifetime

Platform Kernel owns durable actual usage. For each allowance independently:

```text
remaining = max(0, frozen_quantity[allowance_id] - durable_usage[allowance_id])
```

On first acceptance of an `allowance_id`, Kernel durably freezes this scoped tuple:

```text
(tenant_id, region, user_id, allowance_id,
 product_id, metric_key, quantity, period_start, period_end)
```

`quantity` in the frozen tuple is a non-negative integer. For every later
appearance of the same `allowance_id`, all frozen fields must be identical. Any
difference in product, metric, integer quantity, or effective period boundaries
is an allowance contract conflict. A Portal-side change to clock-skew
configuration is not permission to rewrite an already-frozen allowance tuple.
Kernel must not overwrite the frozen tuple, reset usage, or authorize consumption
from that conflicting allowance. Unrelated grants and allowances may continue.

Consumption must be atomic and must not exceed the frozen allowance quantity under
concurrency. Restart preserves used quantity. Two metric allowances never share a
runtime counter merely because they came from one provider billing cycle.

The usage ledger lifetime is independent of whether an allowance is present in
the current AccessSnapshot. Omission, financial block, snapshot expiry, or cache
eviction stops current authorization but never deletes or resets accumulated
usage for that `allowance_id`.

If the same allowance reappears after a same-cycle unblock with the identical
frozen tuple, Kernel resumes the same durable counter. Only a genuinely new
`allowance_id` creates a fresh usage bucket starting at zero. Historical usage
rows are retained at least longer than any possible reappearance of that
allowance; MVP may retain them without automatic deletion.

### Metered paid execution

Every paid metered action in Platform Kernel must declare exactly one
`metric_key`, and that metric must belong to the action's `product_id` in the
Kernel registry.

For paid metered execution, a product grant alone is insufficient. Kernel requires
all of:

```text
valid product grant
exactly one action metric_key belonging to that product
exactly one currently effective allowance for (product_id, metric_key)
now inside allowance [period_start, period_end)
durable usage below frozen quantity
```

The absence or expiry of the paid allowance fails closed for that metric even if
the product grant remains present.

MVP does not stack multiple effective allowances for one `(product_id,
metric_key)`. If a snapshot contains more than one currently effective allowance
for that pair, Kernel fails closed only for that metric: it does not sum the
allowances, does not reject unrelated grants/metrics, and does not discard the
whole snapshot. Portal should likewise materialize that duplicate-source conflict
as omission of the affected metric allowance(s), not unrelated product access.

Free, guest, and trial access/quota, if configured, are separate Kernel-owned
policies. The paid AccessSnapshot remains empty until Portal has a paid grant; the
Portal does not issue an unpaid/free/trial grant through this billing rewrite.
Missing paid allowance never authorizes Kernel to invent paid quota.

Portal never stores authoritative runtime remaining quota.

## Versioning and contract fixtures

All payloads carry `schema_version`.

MVP rules:

- incompatible/unsupported major schema is a contract error;
- consumers fail clearly rather than guess missing semantics;
- contract tests live in both repositories;
- do not introduce a shared runtime Python package that couples Portal and
  Kernel releases.

Fixture ownership follows producer ownership:

```text
Platform Kernel owns canonical capability-manifest fixtures.
Payments Portal vendors hash-checked copies as the manifest consumer.

Payments Portal owns canonical access-snapshot fixtures.
Payments Portal owns canonical access-invalidation request fixtures.
Platform Kernel vendors hash-checked copies as the consumer/receiver.
```

Intentional contract changes update the producer-owned canonical fixture and the
consumer repository's expected SHA-256 copy together. These fixtures are test
data only, not a shared runtime package or a cross-repository runtime dependency.

## Required contract proofs

The implementation plan must cover at least:

- known user with no access-state row returns read-only `200`, revision `0`, and
  empty arrays; GET never creates revision state;
- the request path/body/cache/floor use the canonical Portal user UUID from the
  authenticated identity principal; a Kernel-local user id is never substituted;
- first material access change atomically creates revision `1` and invalidation
  `1`, with no competing GET-created revision;
- same `access_revision` cannot return a different semantic grants/allowances set;
- a deterministic time boundary is scheduled on the existing durable worker for
  its effective deadline, omits only the due fact through revision `N+1` without
  provider HTTP, and leaves unrelated paid facts available after refresh;
- `refresh_after <= expires_at` for every snapshot;
- `null grant.valid_until` remains null and does not bypass source-trust expiry;
- Portal's configured clock-skew haircut covers hard snapshot expiry, source trust,
  grant, and allowance bounds while Kernel never extends received bounds;
- changing `clock_skew_budget` does not change the effective period tuple of an
  already-issued `allowance_id`;
- allowance quantity is a non-negative integer end to end; decimal/float encodings
  are rejected;
- no fleet-wide snapshot poller is required; refresh is driven by paid actions,
  invalidations, and hard expiry;
- snapshot N rejected after floor N+1 is learned;
- concurrent N+1 then delayed N cannot regress cache/floor;
- entitlement absence never produces `404`;
- unexpected `404` for a previously known user does not erase a still-valid cache;
- duplicate invalidation is idempotent;
- outbox survives crash after Portal commit;
- an in-flight `204` for N cannot acknowledge a newly committed N+1;
- a late `204` for N cannot regress already acknowledged N+1;
- N pending plus N+1 committed may coalesce to N+1;
- invalidation outage still fails closed through snapshot expiry;
- stale one-product fact can be omitted while independent product access remains;
- same allowance omitted during block and restored during same cycle keeps the
  same accumulated usage and identical frozen tuple;
- the same `allowance_id` with changed quantity/product/metric/period fails closed
  instead of increasing or resetting quota;
- cache eviction does not delete allowance usage;
- a product grant without the required paid metric allowance cannot authorize a
  paid metered action;
- duplicate effective allowances for one metric fail closed only that metric and
  are never stacked;
- concurrent Kernel quota consumption cannot exceed allowance quantity;
- capability `enabled=false` blocks new mapping/purchase pins without revoking
  already-pinned historical access;
- capability-manifest partial/invalid live reads refuse new admission without
  a stored-manifest fallback; published browsing remains DB-only;
- manifest canonical fixture ownership remains in Kernel while snapshot/
  invalidation canonical fixtures remain in Portal, with hash-checked consumer
  copies and no shared runtime package.

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
  live Capability Manifest consumer + immutable approved bindings
  complete AccessSnapshot producer
  monotonic access_revision owner
  durable coalesced AccessInvalidation sender
```

Nothing in this contract makes Platform Kernel a billing-system client.
