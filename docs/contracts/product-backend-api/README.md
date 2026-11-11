# Common product backend API

Status: **AUTH/ACCESS IMPLEMENTED — ANY-766 Step 12, 2026-11-11.**
Consumer-bound delegation V2, configured callbacks, the persisted policy guard,
consumer-filtered AccessSnapshot V3 and Kernel's durable consumer/P/R coherence
are implemented. Generated OpenAPI documents actual routes, security, schemas,
examples and refusals. Technical source/owner routing preserves purchased history.
Step 13 implements recipient-partitioned delivery; usage/exhaustion and cabinet
usage remain Steps 14–15;
assembled paid browser/execution acceptance remains Step 16, build/install Step 17.
Remote/live acceptance belongs to ANY-767. Synthetic providers and the second
consumer establish protocol behavior, not a real payment or third-party adoption.

Authority: [ADR 0005](../../architecture/decisions/0005-external-billing-boundary.md),
[external billing design](../../superpowers/specs/2026-09-15-external-billing-boundary-design.md),
[access design](../../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md)
and [ANY-766 Section 3.9](../../exec-plans/active/ANY-766-implementation-plan.md#39-consumer-neutral-api-amendment--2026-11-10).
The [paired bundle](../portal-kernel-paid/README.md) owns reviewed schemas,
fixture ownership, exact versions and checksums. This guide is not a second
OpenAPI specification. Existing baseline schemas/fixtures remain unchanged.

## Roles, configuration and onboarding

Portal owns canonical UUID identity, sessions, purchases and purchased ceilings.
External Billing owns financial facts. Each product has one configured technical
source and one execution/usage backend owner within the contour. Kernel is the
first backend, `consumer_id=platform-kernel`; it has no special wire privilege.
The second fixture consumer, `synthetic-summary`, owns only `synthetic_summary`.
It is an isolated protocol example, not the real Document Summary product or
approval to register, contact or implement another team's service. Step 10
validates configured product ownership and guards its policy digest; Step 11
routes technical reads by that ownership. Step 12 filters snapshot authority by
the configured product scope and verifies each included allowance's retained owner.

Operator configuration defines a small explicit consumer set. The following is
a **logical configuration**. The implemented server environment format is
specified below. Secret references in this overview are labels, never actual
credentials; they are not accepted field names in the runtime registry.

```json
{
  "consumers": [
    {
      "consumer_id": "platform-kernel",
      "tenant_id": "anytoolai",
      "region": "ru",
      "consumer_policy_revision": 1,
      "allowed_products": ["proposal_ai"],
      "permissions": ["backend-session:exchange", "backend-session:introspect", "access-snapshot:read", "allowance-exhaustion:write"],
      "callback_url": "https://kernel.example.test/portal-session/callback",
      "backend_base_url": "https://kernel.example.test",
      "technical_source_id": "platform-kernel",
      "backend_to_portal_current_secret_ref": "kernel-to-portal-current",
      "backend_to_portal_previous_secret_ref": null,
      "portal_to_backend_secret_ref": "portal-to-kernel-current"
    },
    {
      "consumer_id": "synthetic-summary",
      "tenant_id": "anytoolai",
      "region": "ru",
      "consumer_policy_revision": 1,
      "allowed_products": ["synthetic_summary"],
      "permissions": ["backend-session:exchange", "backend-session:introspect", "access-snapshot:read", "allowance-exhaustion:write"],
      "callback_url": "https://summary.example.test/portal-session/callback",
      "backend_base_url": "https://summary.example.test",
      "technical_source_id": "synthetic-summary",
      "backend_to_portal_current_secret_ref": "summary-to-portal-current",
      "backend_to_portal_previous_secret_ref": null,
      "portal_to_backend_secret_ref": "portal-to-summary-current"
    }
  ]
}
```

### Implemented Step 10 settings and cutover

`BACKEND_CONSUMERS` is a JSON array (at most 16 entries), parsed by Portal
`app/core/backend_consumers.py` and `Settings`. Each entry requires the identity,
scope, P, products, permissions, callback, backend origin and technical source
fields in the overview, plus actual server-only SecretStr fields
`backend_to_portal_current_secret` and `portal_to_backend_current_secret`.
Optional distinct previous slots are `backend_to_portal_previous_secret` and
`portal_to_backend_previous_secret`. The logical `*_secret_ref` fields above
must be resolved before supplying settings; no secret-manager framework is added.
Empty `[]` disables backend authentication. There are no default permissions.

For managed local startup, set `BACKEND_CONSUMERS` to a single-line JSON array
in the repository-root `.env`; a process environment value takes precedence.
`repo:up` forwards it through private `.harness/runtime.env` to the API and web
server environments. The registry stays out of runtime metadata and public
`NEXT_PUBLIC_*` configuration.

Safe synthetic example (one entry; add the independent second identity in tests):

```json
[{
  "consumer_id": "platform-kernel",
  "tenant_id": "anytoolai",
  "region": "ru",
  "consumer_policy_revision": 1,
  "allowed_products": ["kernel_demo", "proposal_ai", "client_update_writer", "brief_decoder", "acceptance_builder"],
  "permissions": ["backend-session:exchange", "backend-session:introspect", "access-snapshot:read"],
  "callback_url": "https://kernel.example.test/portal-session/callback",
  "backend_base_url": "https://kernel.example.test",
  "technical_source_id": "platform-kernel",
  "backend_to_portal_current_secret": "synthetic-incoming-not-a-real-key-1111111111",
  "portal_to_backend_current_secret": "synthetic-outgoing-not-a-real-key-2222222222"
}]
```

Real entries must include the full intended Kernel product scope. Configure
P=1 for the initial migrated Kernel policy. The registry accepts an empty product
scope at a higher P and retains the guard's monotonic history. Step 12 filters
products in V3 and fences cached authority/admission against every request's
current introspected P; a policy reduction does not require changing paid R.
IDs, per-product owners and all credential slots must be unambiguous; scope must
equal this Portal instance.
URL credentials, query/fragment and foreign callback origins are refused.
HTTPS is required, with loopback HTTP only in development/test. Rotation and
callback changes do not change the policy digest. `allowance-exhaustion:write`
is a recognized configuration permission but its receiver remains Step 14.

At API startup, `initialize_backend_consumers` atomically installs validated
policies in `backend_consumer_policies`. Reused-P digest changes and rollback
abort startup. Identity requests read the guard and refuse stale installations
with safe `503`; introspection performs no policy writes or session bookkeeping.
The persisted key is consumer/tenant/region. Rows retain P/digest and, since
Step 13, `snapshot_delivery_enabled` for installed snapshot-recipient membership.
Startup derives membership from the complete configured registry and each entry's
`access-snapshot:read` permission. This flag selects delivery recipients without
changing P/digest semantics or adding policy to Core owners, replay partitions
or usage buckets. No service secrets or callbacks are persisted in this table.
Introspection also requires `PAID_ACCESS_CLOCK_SKEW_SECONDS`; configure 5 for the
selected local clock budget. Missing configuration returns `503`; deployed
support for that budget remains an operator requirement.

Portal web uses the same **server-only** `BACKEND_CONSUMERS` registry and projects
only consumer_id/callback_url into the authorization component. A service-specific
web environment may supply just those two public fields. Never rename the
registry to a NEXT_PUBLIC variable. The page is `/[locale]/backend/authorize`;
its query requires exactly consumer_id/state/code_challenge/code_challenge_method.
Callback/redirect query fields, duplicate fields and unknown consumers are refused
before code issuance. Selection always uses a configured callback, with code/state
only in the fragment. `NEXT_PUBLIC_KERNEL_WEB_BASE_URL` remains the cabinet's
Kernel launch host; it no longer owns authorization callback selection.

Kernel continues to use `ANYTOOLAI_PORTAL_BASE_URL` plus
`ANYTOOLAI_PORTAL_ACCESS_SERVICE_TOKEN`; set `ANYTOOLAI_PORTAL_CONSUMER_ID` to
`platform-kernel` (the default). Configure its web
`NEXT_PUBLIC_PORTAL_AUTHORIZE_URL` as the localized `/backend/authorize` URL.
The host sends `consumer_id=platform-kernel` and accepts only its own V2 response.
Its local `/v1/portal-session/exchange` and `/portal-session/*` paths remain.

Stop old local APIs/workers before the synchronized cutover. Apply forward Portal
migration `20261111_0009` after `20261110_0008`, then start the updated pair/browser.
The migration renames kernel_session_delegations to backend_session_delegations
and audience to consumer_id, retaining the existing platform-kernel value and
all parent links, hashes, challenges, deadlines and single-use state. A historical
row with an audience other than platform-kernel refuses migration before changes;
no foreign credential is automatically adopted. Configure and initialize the
policy guard before serving identity. No Kernel schema change
is needed in Step 10. Old binaries are incompatible and excluded.

The stable tab key `anytoolai.portal_session.v1` now contains a version-2 envelope
with consumer/P. Version-1 envelopes fail closed and require authorization; the
separate owner/custody and pending prepared-start records remain readable. Same-owner
V2 authorization preserves the exact original request and idempotency key;
different-owner authorization clears private recovery. No guest fallback is added.

Step 11 selects manifest origins and outbound keys from `BACKEND_CONSUMERS`.
Step 13 selects invalidation origins and outbound keys from that same registry.
With the worker enabled, each snapshot consumer's delivery lane starts automatically;
legacy Kernel settings no longer select a delivery destination.
Step 12 replaces the interim Kernel-only V2 endpoint with consumer-filtered V3.
Every consumer requires explicit access-snapshot:read; the credential selects
consumer identity and products. No V2 wire translation or legacy route remains.

This minimal example does not replace Kernel's full configured product set.
The migrated Kernel policy must include every intended existing product.
Step 11 connects technical-source metadata to origin/client selection and
provenance through the existing manifest V1 validation seam. Each technical
source ID has one configured backend owner and each product belongs to one
entry. Validate unique consumer/source IDs, nonoverlapping service secrets and
a single source/backend owner for each product. Allowed
products must agree with that ownership. No shared Kernel key, dynamic
registration/admin API, source mirror or automatic owner transfer is added.

1. Agree on contour, product/metric/unit and sole source/backend owner. The
   configured contour is `anytoolai/ru`; locale never selects scope.
2. Configure independent secrets in both directions, fixed callback and explicit
   permissions. Each receiver accepts at most its own current/previous pair;
   a previous secret cannot authenticate as another consumer. Query/body fields
   can narrow a trusted principal, never select a service identity or broaden it.
3. Install/migrate compatible Portal, Kernel and browser together as described
   below. Verify identity/access locally before enabling any transport sender.
4. Backend owners implement durable enforcement and reverse endpoints. Actual
   third-party adoption/testing is their team's responsibility. Commercial
   quantities, LBX associations and sales retain separate approval gates.

Internal calls require exactly one service Bearer, verified TLS (only explicit
local dev/test loopback HTTP exceptions), no browser Origin/public CORS and
`Cache-Control: no-store` on success and refusal. The primary Portal bearer is
used only by Portal code issuance; never forward it to a backend. Operation
permissions grant no other operation. Do not use service keys in external
Swagger browsers or log bodies, codes, tokens, headers, fragments or PII.

## Implemented Step 11 technical sources and history

`BACKEND_CONSUMERS` is also the technical routing configuration. For each entry,
`technical_source_id` identifies the source, `consumer_id` the execution/usage
owner, `allowed_products` its product scope, `backend_base_url` the manifest
origin and `portal_to_backend_current_secret` the outbound Bearer credential.
Portal requests the same `/internal/v1/capability-manifest` V1 shape and validates
scope, digest, unique products/metrics, selected enabled capability and unit
through the existing client. No Kernel scenario registration is needed for an
external product. A selected detail/publication/purchase reads only its source;
discovery reads the configured sources under the same bounded preflight budget
and filters each response to its configured products.

Configured connections carry `CONFIGURED_SOURCE`, which does not establish live
producer conformance or approve sales. `KERNEL_MOCK_ENABLED` keeps the Kernel
consumer `SIMULATED`, including when its URL comes from the registry. With an
empty registry, technical reads retain the existing Kernel-only source settings,
while backend service authentication remains disabled. `require_kernel()` remains
for that compatibility path and the explicit Kernel conformance check. Step 13 composes independent invalidation clients from each snapshot consumer's
registry origin/outgoing key; legacy settings do not select delivery destinations. Unknown products, ambiguous source IDs and
source/owner disagreement with a saved link or purchase fail closed.

New metered publications write `product-link-v4`; purchased terms use
`purchased-technical-terms:v3` inside `accepted-purchase:v4`. Link and terms bind
`technical_source_id`/`backend_consumer_id` and neutral `manifest_provenance`;
terms use `manifest_version` instead of `kernel_manifest_version`. Selected
consent uses `selected-technical-terms:v2`, binding source/owner and the selected
commercial/technical meaning without unrelated manifest audit churn. The
unmetered development path retains its legacy link/test-terms format only for
the original `platform-kernel` source/owner pair; it cannot supply a new production
quantity. Every other source/owner pair requires an explicit technical offer.
Existing v3 links remain usable with terms v2 and acceptance v3 after fresh
admission; there is no mandatory republication or conversion to v4.

Pre-Step-11 links, terms and acceptances keep their original schemas, omitted
fields, serialization and hashes. Their legacy `ownership` view returns Kernel
in memory; it never adds fields to `model_dump()` or persisted JSON. New records
retain their explicit stored owner. Both historical
v2 consent-digest variants replay their saved digest. Allowance materialization
still compares the original `terms_document`; same-cycle recovery reuses its
allowance ID and a later cycle retains the accepted quantity. SIMULATED terms
remain excluded from production metering and v1 purchases gain no quantity.
Publication refuses a changed source/owner for a retained product head; owner
transfer needs a separately authorized continuity procedure.

Step 11 required no database migration or JSON rewrite: its heads were Portal
`20261111_0009`, Kernel `0019` (Step 12 now advances Kernel to `0020`). New formats require the Step 11 reader; equal
migration heads do not permit rollback to an older reader. Snapshot V3 and
recipient-specific delivery are now implemented; generic usage/exhaustion and
cabinet usage remain Steps 14–15. Do not enable
external-product sales before those dependent runtime steps and commercial gates.

Step 11 reuses the Step 1/2 manifest contract and leaves Kernel scenario/metric
declarations unchanged. Step 3 consent replay and Step 5 allowance issuance keep
their original identities; Steps 6/8 execution ownership, pending starts and
usage buckets do not acquire a consumer/source dimension. Step 10 delegation,
callback selection and policy guards are unchanged. At the Step 11 checkpoint the Step 5 V2 snapshot still exposed the whole-user
paid set; Step 12 supersedes it with the scoped V3 behavior below.
Step 13 now generalizes Step 7 delivery using this registry and the retained V1 wire.

## Identity and complete auth/access example

Calls 1–5 below are implemented: identity V2 and consumer-filtered snapshot V3.
The same flow applies to any configured consumer with its own credentials,
callback, products and policy. The synthetic second identity has no Kernel privileges.

All values below are synthetic. The examples form one Kernel flow at
`2026-11-09T04:00:00Z`; they are documentation, not commands to a running server.
Use a new unpredictable state and verifier for each real attempt. The verifier
`dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk` has S256 challenge
`E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM`.
The fixture bundle is authoritative for this pair and all body shapes.

1. Backend launch stores unpredictable state, verifier, custody epoch and a
   validated local product/result/handoff return target in tab sessionStorage.
   Navigate to Portal `/[locale]/backend/authorize` with configured consumer,
   challenge, S256 and state. This page authenticates the existing Portal
   session and resolves the fixed configured callback. It rejects a supplied
   external callback/redirect override. Kernel's local launch/callback names
   remain `/portal-session/launch` and `/portal-session/callback`.
2. Portal's page calls `POST /api/backend-session-codes` with its primary bearer:

```http
POST /api/backend-session-codes
Authorization: Bearer <PRIMARY_PORTAL_SESSION_ONLY_AT_PORTAL>
Content-Type: application/json

{"consumer_id":"platform-kernel","code_challenge":"E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM","code_challenge_method":"S256"}
```

```json
{"code":"BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB","expires_at":"2026-11-09T04:01:00Z"}
```

The unversioned request uses the `code-request-v2` schema; code response V1 is
unchanged and unversioned. Codes are 32 random bytes, unpadded base64url,
60 seconds, hash-only and bound to consumer plus the existing AuthSession.

3. The fixed callback receives `#code=...&state=...`, clears the fragment
   immediately and validates state/epoch. Kernel's browser posts code/verifier
   to its own `POST /v1/portal-session/exchange`. Its server forwards the unchanged
   `exchange-request-v1` under its service credential:

```http
POST /internal/v1/backend-sessions/exchange
Authorization: Bearer <KERNEL_TO_PORTAL_SERVICE_CREDENTIAL>
Content-Type: application/json

{"code":"BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB","code_verifier":"dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"}
```

```json
{
  "schema_version": 2,
  "consumer_id": "platform-kernel",
  "consumer_policy_revision": 1,
  "tenant_id": "anytoolai",
  "region": "ru",
  "user_id": "11111111-1111-4111-8111-111111111111",
  "access_token": "synthetic-never-a-credential-DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD",
  "token_type": "Bearer",
  "expires_at": "2026-11-09T04:30:00Z"
}
```

Permission: `backend-session:exchange`. Service authentication supplies consumer,
not the exchange body. Code exchange is atomic and single-use; cross-consumer
redemption fails. Delegated expiry is min(issuance+30 minutes,parent expiry).
There is no refresh token. A lost exchange response requires fresh authorization,
while preserving any same-owner pending execution request/key.

4. Every protected backend request introspects its delegated user bearer through
   this server-only call. Authorization is the service key; the token being
   inspected is a secret body field, using unchanged `introspection-request-v1`:

```http
POST /internal/v1/backend-sessions/introspect
Authorization: Bearer <KERNEL_TO_PORTAL_SERVICE_CREDENTIAL>
Content-Type: application/json

{"access_token":"synthetic-never-a-credential-DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD"}
```

```json
{
  "schema_version": 2,
  "consumer_id": "platform-kernel",
  "consumer_policy_revision": 1,
  "tenant_id": "anytoolai",
  "region": "ru",
  "user_id": "11111111-1111-4111-8111-111111111111",
  "valid_until": "2026-11-09T04:29:55Z"
}
```

Permission: `backend-session:introspect`. Check consumer audience, parent session,
active user, expiry and current policy on every request. Introspection reads do
not commit session bookkeeping. Responses have canonical scope/UUID and no PII.

5. Fetch consumer-scoped purchased limits under `access-snapshot:read`:

```http
GET /internal/v1/access-snapshots/11111111-1111-4111-8111-111111111111?tenant_id=anytoolai&region=ru
Authorization: Bearer <KERNEL_TO_PORTAL_SERVICE_CREDENTIAL>
```

```json
{
  "schema_version": 3,
  "consumer_id": "platform-kernel",
  "consumer_policy_revision": 1,
  "tenant_id": "anytoolai",
  "region": "ru",
  "user_id": "11111111-1111-4111-8111-111111111111",
  "access_revision": 7,
  "refresh_after": "2026-11-09T04:01:00Z",
  "expires_at": "2026-11-09T04:04:55Z",
  "grants": [{"product_id":"proposal_ai","valid_until":null}],
  "allowances": [{"allowance_id":"22222222-2222-4222-8222-222222222222","product_id":"proposal_ai","metric_key":"proposal_ai.generations","unit":"generation","quantity":1}]
}
```

Require exactly one tenant/region query; consumer comes from service auth.
Compare the complete response scope/user/consumer/current P before installing.
A second consumer uses its own key and code audience and receives only
`synthetic_summary` tuples. Changing a body/query consumer never grants access.
Q=1 is an isolated test value, not approved commercial terms.

## Policy, snapshots and durable backend enforcement

Portal's P/digest installation guard and introspection of current P are
implemented in Step 10. Step 12 implements V3 filtering, consumer/P cache
identity, independent durable policy/access floors and matching-P admission.
ANY-507 enforcement, execution ownership and accepted replay retain their meaning.

`access_revision` R remains the whole-user paid-state revision. P is a strictly
positive consumer policy version, initially 1 for migrated Kernel. Semantic
identity is `consumer/tenant/region/user/P/R`. Identical identity freezes grants
and full allowance tuples; only refresh/expiry timestamps may change. For digest
comparison, sort grants by product and allowances by allowance ID; include grant
valid_until and every tuple field, exclude only envelope refresh_after/expires_at.
A same-P/R content conflict refuses installation; it is not an empty entitlement.

Persist P/digest in a small consumer-scoped configuration guard owned by Portal
settings/composition (implemented in Step 10; absent in Step 8). Policy digest is
`sha256:<lowercase hex>` of UTF-8 JSON with sorted keys, compact separators and
ASCII escaping over `consumer_id`, `tenant_id`, `region`, `allowed_products`;
the last is a sorted distinct list. Product/snapshot-scope changes require a
higher configured P; changed digest at reused P and rollback are refused.
A higher P may retain the same digest. Secret rotation/callback changes are
outside this digest; operation permissions are checked on every call. Configuration
must be validated before serving, never silently replaced by the persisted old
policy. This is a guard, not an editable policy service.

Backend cache identity includes consumer and scoped user; its existing coherence
lock serializes monotonic policy/access floor observation, install, invalidation
and admission. A candidate must match current introspected P, not be below either
floor, and carry R at/above the durable R floor. Policy change without paid
transition is valid and never lowers R. An old-P response racing a new observation
cannot restore old authority. Eviction deletes only the cached document.

Filter authorized products **and supporting provenance/deadlines before**
completeness/expiry checks. An unrelated overdue product cannot deny this consumer;
an included overdue fact returns `503` until the existing writer commits reduction.
Each included allowance's saved technical source and backend owner must match the
authenticated consumer. Historical terms use the compatible Kernel ownership view;
their stored documents remain unchanged. A conflict refuses the entire snapshot
with `503 paid_access_owner_conflict`, preserving the allowance, R and usage history.
Raising P or moving a product into another scope cannot transfer old authority;
an owner transfer requires a separate explicit continuity procedure.
Do not run whole-user require_current first or silently omit an overdue tuple at
unchanged P/R. Preserve whole-user writer and cabinet semantics. Snapshot GET is
local/read-only, with no peer/LBX I/O or rows created for a known empty R0 user.
Later empty states retain positive R. Future activation needs authoritative
reconciliation, even after its start boundary passes.

For DB time T and clock budget B=5s, expires_at is
min(T+300s, included raw effective source/grant/proven UTC deadlines)−B;
refresh_after=min(T+60s,expires_at). With no included facts, use T+300s only.
Apply B once, preserve separate LBX conservatism and at most six-hour source
trust. Refuse if no currently valid complete document exists. Calendar proof
stays Portal-internal; no guessed UTC cycle, period fields or local refill.
Valid cached authority may survive a refresh outage within expiry/floors and
all predicates; never extend it. `401/403` and unexpected `404` are integration
failures. Deployment clock support remains an operator requirement.

Quantity is the purchased ceiling, **not remaining capacity or an atomic execution
authorization**. Each backend must durably reserve with session/job acceptance,
finalize one accessible successful result once, release only terminal failure,
and preserve replay and recovery across instances/restarts. Unknown outcome
cannot release capacity while original work might finish. Kernel reuses ANY-507:
authenticate → accepted owner/hash replay → refresh outside SQL → coherence lock
and replay recheck → declared metric/exact allowance → reserve in caller Session
→ post-wait DB-time/principal/P/R/expiry/grant check → atomic commit or rollback.
No consumer/P/R field is added to ExecutionOwner, replay meaning, jobs or buckets.
Accepted results remain owner-readable after grant expiry; accepted jobs settle
their original bucket. Guest behavior and observational client events remain.

## Reverse endpoints and usage responsibilities

These are backend responsibilities, **not Portal reverse-endpoint routes**.
Kernel manifest and invalidation receivers already work. Generic source routing
is implemented in Step 11 and recipient fan-out in Step 13; usage/exhaustion
routes and cabinet reads remain Steps 14/15. The descriptions below specify their target behavior.
Kernel
owns the existing V1 manifest/usage/exhaustion wire schemas; other backends use
the same meanings with their own products. See the
[manifest V1 bundle](../kernel-capability-manifest/v1/README.md) and
[paid schemas/fixtures](../portal-kernel-paid/README.md).

- Portal → backend `GET /internal/v1/capability-manifest`, `manifest:read`:
  existing V1 complete product/metric/unit source validation. Kernel producer
  exists; a real external producer is its team's work. Source availability
  gates publication/new purchases, not historical consent replay.
- Portal → backend `POST /internal/v1/access-invalidations`, `access:invalidate`:
  unchanged V1 scope/user/R payload. Destination authentication selects recipient.
  ACK `204` only after durable floor raise/eviction; lower/repeated R also ACK.
  Portal captures N before HTTP; ACK affects only that recipient through N,
  preserving N+1, new generations and every other recipient. Atomic paid-writer
  fan-out includes consumers whose last grant was removed. Bounded existing
  workers retry transport/429/5xx, park permanent faults and repair on restart.
- Portal → owner backend `GET /internal/v1/usage/{user_id}`, `usage:read`:
  tenant/region plus 1–100 distinct allowance_id query values. V1 returns one
  ordered item per ID. Observed items include the complete immutable tuple,
  successful_used/reserved/remaining/available and UTC read_at. Unknown/foreign
  items contain only allowance_id/status=unobserved. Failure is unavailable/503,
  never invented zero; reads create no buckets. remaining=max(Q-used,0),
  available=max(Q-used-reserved,0). Busy reservation is not final exhaustion.
  Kernel's public product-scoped paid-usage route uses introspected owner.
- Backend → Portal `POST /internal/v1/allowance-exhaustions`,
  `allowance-exhaustion:write`: unchanged V1 full tuple/event. Authenticate the
  sending consumer and product owner before tuple acceptance. Foreign product
  authority is `403`; an authorized sender's unknown/conflicting issued tuple
  is `409`. Backend persists one immutable outbox event with successful
  finalization on became_exhausted, including recovery. Portal ACKs `204` only
  after committing one immutable hint; identical duplicate/historical hints
  ACK without revival. Dedup key is scoped user/allowance/event type. Historical
  hints never change the current cycle. No financial command, grant revocation,
  subscription termination or refill follows from a hint.

Portal routes cabinet usage by each allowance's persisted source/backend owner,
with own bounded HTTP resources outside SQL, tuple validation and a post-I/O
local revision check (`503 paid_usage_state_changed`). Preserve isolated local
paid-access capacity and verified-email session guard. Historical eligibility
requires proven CONFIGURED_SOURCE compatible terms; exclude SIMULATED, missing
unit/terms and future allowances awaiting authoritative activation. Select
latest eligible by created_at then allowance_id when no current item exists;
no eligible row means no item. Unknown/unavailable omit counters. Portal has no
usage ledger. Runtime usage/exhaustion/cabinet work remains Steps 14/15.

## Errors, retries and browser custody

Portal identity refusals are no-store and use safe `detail: {"code":"..."}`.
Its `401` includes WWW-Authenticate: Bearer. Implemented Portal identity codes
are `backend_session_code_invalid`,
`backend_delegation_expired`, `backend_parent_authority_invalid`,
`backend_session_forbidden`, `backend_session_request_invalid` and
`backend_session_unavailable`. Invalid service credentials use `service_unauthorized`.
Kernel's local API retains its `error.code` envelope: allowlisted identity `401`
codes are relayed, while upstream service-auth/permission, transport or malformed
response failures become `503 portal_identity_unavailable`. An unsupported Portal
response version also becomes that safe dependency failure, not a user `422`.
Invalid/used code, wrong audience or PKCE is `401`; expired token and invalid
parent are distinct `401` meanings. Authenticated scope/permission refusal is
`403`; invalid shape/unsupported version is `422`; unknown scoped snapshot user
is `404`; unavailable identity/source/storage or no complete valid snapshot is
`503`. Contract index lists per-operation statuses. Never include secret input
in validation errors or treat service refusal as empty paid access.

Retry safe GETs within a bounded deadline. Lost code-exchange response starts a
new authorization, not code reuse. A paid execution retry preserves its exact
prepared request/key; HTTP timeout alone cannot prove rejection. Every internal
response is checked against requested identity, IDs/order, product and full tuple.

Keep primary bearer at Portal and delegated token/owner in tab sessionStorage,
never URL queries/localStorage/telemetry/product inputs. Persist owner-bound
prepared request/key before new paid send; storage refusal blocks that send.
Acceptance stores session reference/removes inputs; if replacement storage
fails, retain accepted response and same pending key. Same-owner reauthorization
restores continuation/pending request. Owner change/logout/proven parent
revocation clears private custody/recovery; ordinary expiry/unavailability
preserves pending work. Compare custody epochs/state across awaits/restores,
ignore old-generation responses and never fall back to a guest in paid mode.

## Bounded replacement and migration inventory

This inventory records current owners and the remaining work. Items 1–2 were
implemented in Step 10 and item 3 in Step 11; item 4 is implemented in Step 12; items 5–6 remain planned. Step 9
itself changed only the specification. Existing Kernel execution/product behavior is preserved.

1. **Service config/principals — implemented Step 10, Portal composition.**
   `app/core/backend_consumers.py`, `app/core/settings.py`,
   `app/http/backend_auth.py`, `app/composition/backend_consumers.py` and
   `app/infrastructure/queries/backend_policies.py` own the configured registry,
   trusted principal and transactional P/digest guard. Kernel API settings and
   `portal_session.py` own expected consumer/scope and V2 validation. Focused
   checks cover two identities, explicit permissions, key-slot/scope isolation,
   version reuse/rollback and stale installations. Source/destination composition
   uses the source seam in Step 11; Step 13 routes delivery through the same registry.
2. **Delegation/audience/callback — implemented Step 10, Portal identity and both browsers.**
   `app/domains/identity/backend_router.py`,
   `app/domains/identity/services/backend_delegation.py`,
   `app/models/backend_delegation.py`, query/persistence helpers and
   `app/http/backend_session_policy.py` own common routes, hashes and consumer
   binding. Portal web `app/[locale]/backend/authorize/page.tsx`, Kernel API
   `portal_session.py`/router and CE-kit `identity/portalSession.ts` implement
   configured callback selection and V2 transport/custody. Forward migration
   preserves platform-kernel, parent FK, hashes, PKCE, expiry, exchanged_at and
   single-use state. Incompatible browser envelopes require fresh authorization;
   same-owner frozen request/key, ExecutionOwner and accepted replay survive.
   Focused API/PostgreSQL/component/browser checks cover consumer isolation,
   single-use races, parent revocation, callback tampering and uncertain-start
   recovery. The active Kernel adapters remain in place.
3. **Source/owner serialization — implemented Step 11, Portal catalog/purchases.**
   `app/composition/sources.py::technical_source`, catalog, mapping_operator and
   purchase_offer compose product-owned V1 manifest reads. ProductLinkDocument,
   AcceptedTechnicalTerms and AcceptedPurchase own versioned identity and a
   separate legacy ownership read view. Existing allowance materialization
   consumes the unchanged historical representation. The
   [source/history rules above](#implemented-step-11-technical-sources-and-history)
   define v4/v3/v4 and selected-consent v2, provenance and reader compatibility.
   Focused tests cover independent configured sources, selected capability/unit,
   both old v2 consent variants, populated old terms/allowances, original IDs,
   renewal quantities and owner-transfer refusal.
4. **Snapshot/filtering/P/R — implemented Step 12, Portal paid reads and Kernel coherence.**
   Portal `paid_read.py::read_committed_state` selects authorized products before
   supporting provenance/deadline checks. The whole-user cabinet and writer keep
   their existing rules. The reserved read lane checks the persisted P/digest
   without policy writes or peer calls and serves V3, including known empty R0.
   Kernel `paid_access.py` validates consumer/scope/P/R; Core
   `quotas/access_coherence.py` owns one lock per consumer/scoped user and independent
   durable P/R floors. A new introspected P is committed before HTTP, evicts only
   cached authority and never lowers R. Installs/admission require matching P;
   stale P/R cannot replace newer authority. Same-P/R semantics remain immutable
   across eviction. Post-wait expiry/floor checks remain in both acceptance paths.
   Migration `0020` forward-binds old rows to platform-kernel/P1, retains R and
   clears incompatible V2 cache/digest metadata. Buckets, usage, active reservations,
   jobs, ownership and replay do not acquire consumer/P dimensions or reset.
5. **Recipient outbox/work — Step 13, Portal paid writer/embedded worker.**
   `app/models/billing_access.py::AccessInvalidationOutbox`,
   `app/domains/billing/paid_access.py`, `access_invalidation.py`, `work.py`,
   `app/jobs/billing.py`, work queries/persistence and existing CLI own delivery.
   The [implemented recipient checkpoint](#implemented-step-13-recipient-delivery)
   records behavior, migration and evidence. The
   [delivery runbook](../../engineering/billing-background-operations.md#any-766-step-7--durable-kernel-invalidations)
   owns cutover, resource bounds, diagnostics and recipient-specific CLI retry.
6. **Usage/exhaustion — Steps 14/15, backend finalizer and Portal reads.**
   Kernel Core `quotas/finalization.py`, `execution_service.py`, `readback.py`
   and existing worker/work storage own result/debit/recovery. Attach V1
   usage/exhaustion there; add no second debit or meter. Portal issued allowances
   own source/backend routing and exhaustion tuple proof. Resolve historical
   Kernel owner without changing stored terms. Test full-tuple rollback/replay,
   unknown/foreign usage, authorized synthetic exhaustion versus foreign owner,
   old-cycle hints and usage timeout/cancellation preserving local access.
   Step 16 adds the synthetic backend and populated-state HTTP/browser acceptance.

**Replacement inventory:** Step 10 replaced the Kernel-named Portal identity
routes/modules/settings after moving their active callers to the common
contract. Old identity routes/settings are no longer supported. Active Kernel
adapters remain; source routing was generalized in Step 11 and consumer/P/R
coherence in Step 12 and recipient delivery in Step 13. No unrelated runtime
purge is authorized. Existing inert source-projection
models are retained schema history, not evidence authorizing a purge here.
Kernel scenarios/products, guest paths and ANY-507 execution semantics stay owned
by Kernel; a non-Kernel product requires no Kernel scenario registration.

**Cutover:** Step 13 advances Portal to `20261111_0010`; Kernel remains at
Step 12's `0020`. Later steps extend the resulting actual heads; never
edit applied migrations. First test forward migrations against populated isolated
local databases. Quiesce both APIs/workers; migrate identity/policy, source-owner
read compatibility, coherence and recipient scheduling in owning-step order;
update Portal, Kernel and browser configuration together, then restart compatible
binaries/workers and verify repair. No concurrent old wire/translation layer is
required. Exclude old delegation/snapshot/outbox binaries and old purchased-term
readers from installation/recovery even when a migration head happens to match.
Keep retained data, original purchases/digests, pending browser starts, allowance
IDs, usage, floors and undelivered work. No owner transfer or bulk JSON rewrite.
Step 17 must specify the reviewed pair and compatible recovery procedure.

## OpenAPI and handoff checkpoint

The actual [generated Portal schema](../../generated/openapi.json) comes from
FastAPI/Pydantic via the existing generation pipeline, with Swagger at
`<PORTAL_ORIGIN>/docs` and live schema at `<PORTAL_ORIGIN>/openapi.json` when
those standard FastAPI routes are enabled. These are locations, not a claim of
an available external server. Step 10 regenerated the schema with common V2
identity routes, PortalUserBearer/BackendServiceBearer and identity operation
security/descriptions/examples/errors. Introspection documents the secret user
body token separately from the service Authorization header. Step 12 regenerates the consumer-filtered V3 snapshot schema with its named
BackendServiceBearer security, example, finite authority and enforcement duties.
Swagger retains internal browser restrictions. Reverse backend endpoints remain
owned/documented by their backends, not invented Portal OpenAPI operations.

The six requirements have explicit producers/consumers and local acceptance:
service identity and delegation (Portal → backend principal, Step 10 two-consumer
security/migration checks); scoped P/R snapshots (Portal → backend, Step 12
filtered-expiry/coherence races and real TCP auth/access); technical ownership
(configured manifest source → Portal purchase/allowance, Step 11 history/replay);
recipient delivery (Portal writer → backend floor, Step 13 isolated ACK/retry);
neutral usage/exhaustion (backend readback/finalizer ↔ Portal, Steps 14/15
full-tuple routing/dedup and cabinet isolation). Step 16 verifies the assembled
pair plus a synthetic second identity locally. Real external backend adoption
remains its team's work.

For the 2026-11-13 working checkpoint, deliver guide, generated schema/Swagger
location, implemented versions and actual local auth/access evidence for both
identities. Label delivery/usage runtime status honestly. Missing external server,
real purchase, registry or third-party acceptance does not block that checkpoint.
Missing local identity/access behavior does. Remaining full-check/install,
commercial and operational gates stay in the plan.


## Step 12 local auth/access checkpoint

The wire versions are delegation **2**, access snapshot **3**, manifest **1** and
invalidation **1**. The Step 12 checkpoint used Portal `20261111_0009` and
Kernel `0020`; Step 13 advances only Portal to `20261111_0010`.
Use the paired [schema/fixture checksums](../portal-kernel-paid/SHA256SUMS).
Swagger is `<PORTAL_ORIGIN>/docs`, live OpenAPI is
`<PORTAL_ORIGIN>/openapi.json`, and the checked-in generated schema is linked above.
Internal operations reject browser Origin even when the Swagger page is visible;
perform service calls from a backend, never paste real service keys into a browser.

Snapshot `503` codes include `paid_access_deadline_pending` for an included overdue
fact, `paid_access_state_pending` for incompatible provenance/start state,
`paid_access_owner_conflict` for a retained source/backend owner mismatch,
`paid_access_policy_unavailable` for a stale/missing configured policy,
`paid_access_clock_unavailable`, `paid_access_busy` and `paid_access_unavailable`.
An unrelated product's deadline/provenance/owner does not affect this consumer's complete
view. Changes to P may change contents at the same R; matching consumer/scope/P/R
freezes semantic contents. Rotation alone changes neither. Quantity remains the
purchased ceiling, not available capacity. A backend must atomically reserve,
finalize or release under its durable execution/replay rules, preserve both floors
on eviction/restart and reject expired or mismatching authority after lock waits.

For synchronized local cutover, stop both APIs/workers, retain backups, migrate
Kernel to `0020`, configure the matching consumer registry/service credentials and
start only the paired V3-capable binaries. Portal needs the Step 11 purchased-term
reader even though its migration head is unchanged. Old V2 readers are excluded;
there is no concurrent translation route. Do not downgrade the consumer-scoped
coherence schema; recover with a compatible retained backup and matching binaries.
Step 13 now partitions the existing invalidation sender by recipient; the Kernel
V1 receiver remains compatible. Generic usage/exhaustion and cabinet
usage are still Steps 14/15 and are not implemented by this auth/access handoff.

The focused local regression targets are Portal
`test_access_snapshot_postgres.py`, `test_kernel_session_delegation.py`,
`test_kernel_session_delegation_postgres.py`, `test_any766_contracts.py` and
`test_any766_auth_access_http_postgres.py`, and Kernel
`test_paid_access_admission_postgresql.py`, `test_access_snapshot_client.py`,
`test_portal_session_api.py` and `test_paid_contract_fixtures.py`.
The TCP case runs real Portal and Kernel exchange endpoints, Portal introspection
and V3 snapshot clients, plus durable P/R installation in separate disposable
PostgreSQL databases. It uses a confirmed persisted test purchase derived through
application paths with synthetic LBX/manifest responses and a second configured
synthetic identity. No transport or trusted identity is replaced between services.
It does not claim the Step 16 full paid-execution/browser journey, live LBX/AI,
third-party adoption or deployed acceptance.


## Implemented Step 13 recipient delivery

Portal migration `20261111_0010` partitions outbox/work by recipient/scoped user
and preserves Kernel's queued history. Stop both local APIs/workers before the
forward migration and registry installation; start only Step 13-capable Portal
binaries and the compatible Kernel V3/P/R receiver (`0020`). Pending, parked,
in-flight and N+1 migration are tested on disposable PostgreSQL. Old claims
cannot settle migrated or repaired work. Recovery requires compatible backups
and binaries; downgrade is refused when non-Kernel recipient history exists.

Registry consumers with `access-snapshot:read` receive each material whole-user
R in the writer transaction, even after their last grant is removed. Policy-only
changes still use introspected P, without another delivery protocol. Semantic
no-ops preserve retry backoff and enqueue generations. A `204` acknowledges
only that recipient's captured N, preserving N+1 and every other recipient.
Each configured recipient has independent bounded HTTP admission, cleanup and
DB thread slots. Missing/completed scheduling is repaired; parking and unresolved
history survive restart. Removed entries retain history and receive no new R.

Use `--recipient-id <consumer-id>` with `inspect-invalidation` or
`retry-invalidation`; the [runbook](../../engineering/billing-background-operations.md#any-766-step-7--durable-kernel-invalidations)
records exact commands, resource bounds and safe classifications. Local tests
use synthetic backend HTTP responses with independent service keys; they do not
claim real external-backend adoption, live billing or assembled Step 16 acceptance.
Generic usage/exhaustion and cabinet usage remain Steps 14/15.
