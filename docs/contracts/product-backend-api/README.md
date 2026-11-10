# Common product backend API

Status: **TARGET SPECIFICATION — ANY-766 Step 9, 2026-11-10.**
The consumer-neutral endpoints, policy guard and migrations described here are
not implemented yet. Kernel-only delegation V1, snapshot V2, paid admission,
invalidation delivery and browser recovery are the implemented Steps 1–8
baseline. Offline fixtures prove contract consistency, not runtime isolation,
durability, TCP interoperability or a payment. The working auth/access handoff
is Step 12, prioritized for **2026-11-13**; delivery/usage follow in Steps 13–15,
assembled local acceptance in Step 16 and build/install preparation in Step 17.
Remote publication, installation and live acceptance belong to ANY-767.

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
approval to register, contact or implement another team's service.

Operator configuration defines a small explicit consumer set. The following is
a **logical target configuration**, not an accepted environment variable/file
format today. Step 10 wires it into existing settings/composition and protected
operator tooling. Secret references below are labels, never actual credentials.

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

This minimal example does not replace Kernel's full configured product set.
The migrated Kernel policy must include every intended existing product.
Technical source entries select an origin/client and provenance through the
existing manifest V1 validation seam. Validate unique consumer IDs, nonoverlapping
service secrets and a single source/backend owner for each product. Allowed
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

## Identity and complete auth/access example

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

5. Fetch the authorized purchased limits under `access-snapshot:read`:

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

`access_revision` R remains the whole-user paid-state revision. P is a strictly
positive consumer policy version, initially 1 for migrated Kernel. Semantic
identity is `consumer/tenant/region/user/P/R`. Identical identity freezes grants
and full allowance tuples; only refresh/expiry timestamps may change. For digest
comparison, sort grants by product and allowances by allowance ID; include grant
valid_until and every tuple field, exclude only envelope refresh_after/expires_at.
A same-P/R content conflict refuses installation; it is not an empty entitlement.

Persist P/digest in a small consumer-scoped configuration guard owned by Portal
settings/composition (no such guard exists in Step 8). Policy digest is
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

These are backend responsibilities, **not implemented Portal routes**. Kernel
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

All refusals are no-store and use safe `detail: {"code":"..."}`. `401` includes
WWW-Authenticate: Bearer. Target identity codes are `backend_session_code_invalid`,
`backend_delegation_expired`, `backend_parent_authority_invalid`,
`backend_session_forbidden`, `backend_session_request_invalid` and
`backend_session_unavailable`; Step 10 updates both peers and browser together.
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

Paths below name current owners, not a mandate to delete Kernel behavior.
Each item names its minimal replacement, preserved state and local check.
No runtime or migration is changed by Step 9.

1. **Service config/principals — Step 10, Portal composition.**
   `app/core/settings.py`, `app/http/kernel_auth.py`,
   `app/composition/sources.py` and Kernel API settings/service authentication
   currently own independent directional credentials and scope. Replace the
   single Kernel receiver principal with configured consumer/scope/products/
   operation permissions; persist the P/digest guard. Preserve current/previous
   rotation and reserved read admission. Check two identities, no permission
   implication, key-slot/scope isolation and version reuse/rollback refusal.
2. **Delegation/audience/callback — Step 10, Portal identity and both browsers.**
   `app/domains/identity/kernel_router.py`,
   `app/domains/identity/services/kernel_delegation.py`,
   `app/models/kernel_delegation.py`, query/persistence helpers and
   `app/http/kernel_session_policy.py` own current Kernel routes/hashes/audience.
   Portal web `app/[locale]/kernel/authorize/page.tsx`, Kernel API
   `portal_session.py`/router and CE-kit `identity/portalSession.ts` own transport
   and custody. Replace Portal paths with common paths, generalize the existing
   stored audience to the configured consumer and use V2 responses and configured
   callback. Forward-bind existing rows to platform-kernel, retaining parent FK,
   hashes, PKCE, expiry, exchanged_at and
   single-use state. Require new delegation for incompatible browser tokens;
   retain same-owner frozen request/key, ExecutionOwner and accepted replay.
   Extend existing session API/unit/PostgreSQL/component tests for cross-consumer
   exchange/introspection, single-use race, parent revocation, tampering and
   uncertain-start reauthorization. Do not delete the active Kernel adapters.
3. **Source/owner serialization — Step 11, Portal catalog/purchases.**
   `app/composition/sources.py::require_kernel`, catalog, mapping_operator and
   purchase_offer compose current live source reads. ProductLinkDocument,
   AcceptedTechnicalTerms, AcceptedPurchase and
   `app/domains/billing/paid_allowances.py::materialize_allowance` own immutable
   history/terms_document equality. Replace unconditional source selection with
   configured source/owner selection using manifest V1 validation. New versions
   are product-link-v4, purchased-technical-terms:v3, accepted-purchase:v4 and
   selected-technical-terms:v2; add technical_source_id/backend_consumer_id to
   new link/terms identity and selected-consent meaning. New source evidence
   uses manifest_version/manifest_provenance in place of Kernel-specific names.
   The new selected digest binds source/owner, selected offer, account, mapping
   revision, selection, commercial fingerprint and provenance; full manifest
   version/source audit changes for unrelated products remain outside it.
   accepted-purchase:v4 pins that selected-technical-terms:v2 digest. Retain every
   old serializer and hash input, including full-audit versus selected v2 consent. Legacy
   missing source/owner resolves to platform-kernel only in a separate in-memory
   view; do not add default fields to old model_dump or rewrite stored JSON.
   Preserve configured/simulated labels, quantity and same-cycle IDs/usage.
   Extend publication/purchase/replay/derivation tests with populated old links,
   both digest variants, terms_document equality and same-cycle renewal/recovery;
   compare exact serialized bytes and saved digests before/after migration.
4. **Snapshot/filtering/P/R — Step 12, Portal paid reads and Kernel coherence.**
   Portal `app/domains/billing/paid_read.py::CommittedPaidState` currently checks
   whole-user effective_until/require_current; `snapshot_router.py` and
   `app/composition/paid_reads.py` own V2/reserved resources. Add consumer-scoped
   relevance/completeness before deadline evaluation and serve V3. Keep sole
   whole-user writer and local cabinet guarantees. Kernel API `paid_access.py`
   and Core `quotas/access_coherence.py` own current snapshot/floor/lock; extend
   that row's key with consumer and add independent P observation/floor.
   Forward-migrate Kernel rows to platform-kernel/P1, retain R floor, discard
   incompatible cached snapshot/digest metadata only. Never reset ANY-507
   buckets, reservations, jobs or owners. Extend snapshot/PostgreSQL races for
   unrelated/included expiry, policy change without R, stale P/R installs,
   same-identity conflicts, eviction/restart and post-lock expiry. Step 12 adds
   actual local Portal–Kernel TCP auth/access proof and accurate Swagger.
5. **Recipient outbox/work — Step 13, Portal paid writer/embedded worker.**
   `app/models/billing_access.py::AccessInvalidationOutbox`,
   `app/domains/billing/paid_access.py`, `access_invalidation.py`, `work.py`,
   `app/jobs/billing.py`, work queries/persistence and existing CLI own delivery.
   Add recipient to uniqueness, coalescing/work keys, claim/destination,
   retry/parking/repair and delivered revision; fan out R atomically, including
   grant removal. Bind old outbox rows to Kernel with exact pending/delivered
   revisions. Stop workers before replacing work keys/retiring claims; retain
   unresolved work and let existing repair reschedule it. Test populated pending,
   parked, in-flight and N+1 migration, claim loss and independent ACK/failure
   without starving local deadlines. No new scheduler or policy-event protocol.
6. **Usage/exhaustion — Steps 14/15, backend finalizer and Portal reads.**
   Kernel Core `quotas/finalization.py`, `execution_service.py`, `readback.py`
   and existing worker/work storage own result/debit/recovery. Attach V1
   usage/exhaustion there; add no second debit or meter. Portal issued allowances
   own source/backend routing and exhaustion tuple proof. Resolve historical
   Kernel owner without changing stored terms. Test full-tuple rollback/replay,
   unknown/foreign usage, authorized synthetic exhaustion versus foreign owner,
   old-cycle hints and usage timeout/cancellation preserving local access.
   Step 16 adds the synthetic backend and populated-state HTTP/browser acceptance.

**Deletion inventory:** no runtime deletion is proven or proposed by this step.
The active Kernel auth/source/coherence/client code above must be generalized in
its owning step. Replaced Portal routes/settings may be removed only after all
active callers move in the synchronized cutover. Existing inert source-projection
models are retained schema history, not evidence authorizing a purge here.
Kernel scenarios/products, guest paths and ANY-507 execution semantics stay owned
by Kernel; a non-Kernel product requires no Kernel scenario registration.

**Cutover:** extend actual heads Portal `20261110_0008` and Kernel `0019`, never
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
an available external server. Step 9 preserves generated artifacts: they still
describe Kernel-named V1 identity and V2 snapshot, without named security schemes,
per-operation security or useful auth/access descriptions. The target guide
cannot be used as proof those replacement routes work today.

Step 10 adds named PortalUserBearer/BackendServiceBearer schemes, correct
operation security, schemas, safe examples/errors/no-store descriptions for
implemented identity routes and regenerates artifacts. Step 12 does the same
for implemented V3 access routes and completes the common handoff. Introspection
must describe the body token separately from service Authorization. Swagger
retains internal browser restrictions; reverse backend endpoints are documented
here/by their owning bundles, not invented Portal OpenAPI operations.

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
