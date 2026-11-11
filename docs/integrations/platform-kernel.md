# Platform Kernel integration map

Status: navigation and implementation snapshot; normative contracts are delegated below.
Last source inspection: 2026-11-11; local source state, not a deployment check.

## Ownership and sources

Portal owns identity, sessions, legal acceptance, public discovery and the
cabinet, approved commercial-to-technical mappings, local paid grants/allowances,
access revisions, outbox production and durable invalidation delivery.
External Billing owns commercial billing truth and lifecycle. The separate
[Platform Kernel repository](https://github.com/gushinets/anytoolai-platform)
owns execution, artifacts, technical product/metric vocabulary, actual usage
and runtime quota enforcement.

Read the peer's current [AGENTS](https://github.com/gushinets/anytoolai-platform/blob/main/AGENTS.md),
[architecture](https://github.com/gushinets/anytoolai-platform/blob/main/ARCHITECTURE.md)
and [knowledge index](https://github.com/gushinets/anytoolai-platform/blob/main/docs/index.md).
Target contract authority remains:

1. [ADR 0005](../architecture/decisions/0005-external-billing-boundary.md).
2. [External Billing Boundary Design](../superpowers/specs/2026-09-15-external-billing-boundary-design.md).
3. [Portal-Kernel Access Contract Design](../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md).
4. [Accepted live-source amendment](../superpowers/specs/2026-10-15-live-source-commercial-admission-design-amendment.md),
   narrowly superseding source-catalog mirroring/new-sale TTL only.

This map does not redefine those contracts. Local implementation is described
by [architecture](../../ARCHITECTURE.md), [product scope](../PRODUCT.md) and
[contours](../architecture/contours.md). Superseded contracts and historical
plans do not override accepted sources.

## Observed implementation

Historical Steps 14/15 source inspection: Portal `9632ec4ce440fa17d8463f230b98df7cccccc934`
and Kernel `36be7fa3c3147b032b97f050a898a97423db2070`, plus the then-uncommitted
paired changes. These pins identify that checkpoint, not current branch tips.
The [active plan](../exec-plans/active/ANY-766-implementation-plan.md) records
completed Steps 1–17 in the agreed local scope: common identity V2, configured
consumer callbacks and the policy guard, consumer-filtered V3 paid admission with independent durable P/R
floors, and V1 invalidation. Step 11 adds configured technical sources and
immutable source/owner history.
Step 13 partitions delivery by recipient; Step 14 adds usage readback and durable
exhaustion hints. Step 15 adds isolated cabinet usage reads and current/historical
presentation. Steps 16/17 supply focused assembled local acceptance and build/install
preparation; the full matrix and remote/live acceptance remain ANY-767 work.
Current identity configuration is in the
[common guide](../contracts/product-backend-api/README.md#implemented-step-10-settings-and-cutover).

| Operation / request direction | Payload producer | Payload consumer / receiver | Verification status |
| --- | --- | --- | --- |
| `GET /internal/v1/capability-manifest`: Portal -> Kernel | Service-authenticated Kernel endpoint implemented; separate Portal development mock remains optional | Portal typed HTTP client implemented | Focused Step 16 real-app local acceptance with explicit external substitutes; no live/deployed acceptance claimed |
| `GET /internal/v1/access-snapshots/{user_id}`: Kernel -> Portal | Step 12 serves consumer-filtered read-only V3 | Step 12 adds durable consumer/P/R coherence while retaining ANY-507 admission | Focused Step 16 paired local HTTP/PostgreSQL acceptance; full matrix deferred |
| `POST /internal/v1/access-invalidations`: Portal -> Kernel | ANY-766 Step 7 implements bounded claimed delivery, exact-N ACK, restart repair and parked-work CLI | Kernel Step 6 implements the durable receiver; permission is disabled by default | Focused PostgreSQL delivery checks and Step 16 paired HTTP acceptance; full matrix deferred |

Portal's enabled embedded worker now selects each snapshot recipient's origin
and outgoing credential from `BACKEND_CONSUMERS`; legacy Kernel connection
settings no longer select delivery destinations. Step 13 adds independent
bounded delivery lanes and exact-N ACK/repair per recipient. Stop affected
APIs/workers before migrating the Step 14 pair to Portal `20261111_0011` and
Kernel `0021`. The historical Step 13 heads were Portal `20261111_0010` and
Kernel `0020`. Configure the compatible invalidation receiver and its permission first; the
[delivery runbook](../engineering/billing-background-operations.md#any-766-step-7--durable-kernel-invalidations)
describes migration order, parking and recipient-specific CLI retry. The
[Step 14 guide](../contracts/product-backend-api/README.md#implemented-step-14-usage-and-exhaustion)
records usage/exhaustion settings and migration requirements. Step 8 implements
browser custody/recovery; Step 15 implements cabinet usage. No deployed or live-provider
acceptance is inferred from implemented transport.

## ANY-766 Step 9 common backend specification — 2026-11-10

Inspected local sources: Portal `119d3d86175f35006d2ef90259bb43e19a9ef82f`
and Kernel `6697b9f5c271eb1c77f507e037661fd92a048b74`, plus the Step 9
documentation/test-only diff. The
[Portal-owned common guide](https://github.com/gushinets/payments-portal/blob/main/docs/contracts/product-backend-api/README.md)
now specifies independent consumers, audience-bound V2 delegation, V3/P/R
snapshots, immutable source/owner history and recipient/usage routing. The
[paired bundle](../contracts/portal-kernel-paid/README.md) retains exact baseline
schemas/fixture payloads and independently checked target additions.

At this historical Step 9 checkpoint, runtime, migrations and generated OpenAPI
were unchanged (Kernel identity V1/snapshot V2). Step 10 subsequently implemented
common identity V2/security while retaining the then-current Kernel-only V2
snapshot. Step 12 now supersedes that wire with consumer-filtered V3/P/R. The guide records
actual owning modules, minimal replacements, populated-state forward migration
requirements and focused acceptance cases; active Kernel code is not a purge
target. Common identity is Step 10, technical-source ownership Step 11, working
auth/access with documented generated Swagger Step 12 (2026-11-13 priority),
recipient delivery Step 13, usage/cabinet Steps 14/15, assembled local acceptance
Step 16 and build/install preparation Step 17. Real external backend adoption
belongs to its owning team; remote/live acceptance remains ANY-767.

## Historical implementation observations

The following observations retain their original source pins and scope. The
current local state above supersedes their statements about remaining runtime work.

ANY-664 implemented restricted v1 publication and DB-only browsing. ANY-709
Step 1 now implements direct versioned links, one current product pointer,
enabled-product discovery and current selected LBX offers. Source projection
slots remain inert.
ANY-709 implements purchase orchestration; ANY-715 implements subscription
reconciliation and GET-only recovery without Kernel calls. ANY-765 implements
local paid projection, stable allowances, revisions/outbox, deadlines and the
authenticated cabinet read. Actual usage/remaining and paid HTTP execution remain
ANY-766. See the [Step 10 handoff](../engineering/billing-background-operations.md#step-10-handoff--any-765)
for producer semantics, B10 and current acceptance limits. This source refresh
changes no wire contract or conformance status.

ANY-766 Step 3 adds Portal-owned immutable quantity publication and purchase
acceptance: `product-link-v3`, `purchased-technical-terms:v2` and
`accepted-purchase:v3`. The protected CLI validates the enabled selected
product/metric/unit through the existing manifest client. It retains LBX
commercial quantity separately, selected-consent versus full audit digests,
historical v1/v2 replay and accepted renewal quantities. See the
[operator and compatibility details](../engineering/ANY-709-billing-runbook.md).
The peer's Step 2 production declarations were inspected locally at
`b9b6c78bf524a613496f1053278c074c4c4554cc`; they remain commercially disabled.
This Portal-only change requires no new Kernel API/schema. Kernel paid identity,
production derivation, transport and real joint acceptance remain later steps;
synthetic configured-source tests are not live-source or sales approval.

Evidence: [Portal paid writer](https://github.com/gushinets/payments-portal/blob/ac8743ff35c5cfaf0fdaf108fa89ad5e71bf49cd/apps/api/app/domains/billing/paid_access.py),
[typed client](https://github.com/gushinets/payments-portal/blob/ac8743ff35c5cfaf0fdaf108fa89ad5e71bf49cd/apps/api/app/integrations/kernel/client.py),
[Kernel routes](https://github.com/gushinets/anytoolai-platform/blob/72ff15bc0b77903c87aa39f7b10186dccc556d09/apps/platform-api/src/anytoolai_platform_api/main.py)
and [Manifest producer](https://github.com/gushinets/anytoolai-platform/blob/72ff15bc0b77903c87aa39f7b10186dccc556d09/apps/platform-api/src/anytoolai_platform_api/routers/capability_manifest.py).
The retained [ANY-664 Step 8 handoff](../contracts/kernel-capability-manifest/v1/step-8-handoff.md)
records historical `LOCAL_SPEC_CONFORMANCE=PASS` and
`REAL_KERNEL_CONFORMANCE=DEFERRED_NOT_IMPLEMENTED`; the latter describes that
earlier checkpoint, not today's endpoint availability.

## ANY-766 Step 4 identity checkpoint — 2026-11-10

Portal `4a34948eb02d034b46871d739bbf066ffc67d48a` and Kernel
`89296ddce3c7b187881cb1730bf7fbacf3ffd302` were inspected locally, plus the
paired uncommitted Step 4 change. Portal now issues hash-only one-use S256 codes
and serves scoped exchange/introspection. Kernel exposes code exchange and a
request-by-request identity dependency returning the existing Core
`ExecutionOwner` for a canonical Portal UUID, without local identity matching.
The original Portal bearer stays at Portal.

The [historical Step 4 configuration and limits](../contracts/portal-kernel-paid/README.md#step-4-server-implementation)
included independent directional credentials, explicit receiver permissions,
rotation, fixed audience, parent revocation, finite deadlines, no-store and
secret-safe refusals. Local PostgreSQL tests cover migration/cascade/single-use
races; Kernel HTTP is intercepted in focused boundary tests. This is not real
two-service HTTP or deployed acceptance. This checkpoint describes Step 4;
the current local summary above records the subsequent snapshot/admission/delivery
implementation. Browser launch/recovery remains Step 8. Existing guest routes
are unchanged.

## Dependencies before real integration

ANY-766 Step 12 serves consumer-filtered snapshot V3 through each backend's
reverse-direction service credential with explicit `access-snapshot:read`
permission. Scope is required in the query; known empty users retain revision
zero without writes. The producer shares the reserved local paid-read resources
and filters authorized products/supporting facts before completeness/deadline
checks, without peer/source I/O or identity bookkeeping. The cabinet and writer
retain whole-user guarantees. Production metering
requires accepted `CONFIGURED_SOURCE` terms; SIMULATED history stays labelled
and can supply no production allowance. See the [as-built serving rules](../engineering/billing-background-operations.md#any-766-step-5--production-allowances-and-snapshot-serving).
Quiesce both APIs/workers and migrate Kernel to `0020` before starting the
compatible V3 pair. Old V2 readers are excluded; this local checkpoint changes
no commercial flags or deployed configuration.

- **Identity:** paid access uses Portal's authenticated UUID under
  `(tenant_id, region, user_id)`, verified through Step 10 common delegation V2
  and per-request introspection. Step 8 browser recovery remains, with Step 10
  configured callbacks and token-envelope migration. Guest
  quota or an internal metering test is not proof of Portal authentication.
- **Scope:** Portal uses its configured `anytoolai/ru` deployment scope and rejects
  mismatched manifest responses. Kernel service principals and deployment must
  authorize that exact scope. Real deployment alignment is separate work; locale
  and country do not select authenticated scope.
- **Producer conformance:** Kernel owns the implemented endpoint, schema,
  fixtures and technical vocabulary. Portal integration owners must reconcile
  endpoint/schema/hash/auth/scope and record actual consumer-versus-producer
  checks and sales approval. [Provisional artifacts](../contracts/kernel-capability-manifest/v1/README.md)
  retain historical pins and SIMULATED status; no shared runtime SDK or automatic
  promotion of test quantities is introduced.
- **Enablement:** ANY-709 Step 1 accepts ordinary configured HTTPS Kernel/LBX
  connections without a blanket production refusal. Explicit Kernel mock mode
  remains development/test-only and SIMULATED, including after URL changes.
  A non-mock endpoint is CONFIGURED_SOURCE, never proof of producer conformance
  or production sales approval. ANY-711 remains Done for its delivered manifest
  producer/conformance and TEST-ONLY vocabulary. The
  [2026-11-09 ANY-766 scope clarification](https://linear.app/paveldik/issue/ANY-766)
  assigns selected production metric/unit declarations and scenario bindings to
  ANY-766. Commercial quantities, exact LBX associations and sales enablement
  still require separate owner approval. Portal can start without Kernel config.
- **Usage and launch:** the three operations above do not define an actual
  usage/remaining API for the cabinet. The
  [ANY-766 target bundle](../contracts/portal-kernel-paid/README.md) now specifies
  usage/exhaustion and authenticated cross-app launch. Step 8 implements browser
  launch; usage/exhaustion is implemented in Step 14; cabinet usage remains Step 15. Paired local
  acceptance remains Step 16. Kernel product-to-product handoff is not Portal
  login handoff; common product IDs do not imply common origins or sessions.
- **Commercial meaning:** Kernel product configs and guest quotas do not
  approve a paid registry. `proposal_ai.test_generations` is TEST-ONLY. Live
  source reads gate publication/new purchase; subscription trust and bounded
  AccessSnapshot caching retain distinct policies. Invalidation fences a
  revision; it does not deliver grants or usage.

## Change and verification workflow

For changes to identity, scope, product/metric identity, paid access or cross-app
journeys, inspect the peer's current sources and record their SHA. Update the
owning contract and affected map sections; PR **Peer impact** links peer work
or states `None` with a reason. The implementing side supplies evidence; the
consuming side verifies it. Keep delivery and enablement ownership explicit.

Use `main` links for navigation and pinned links for evidence. An older SHA is
the last observation, not automatic incompatibility. Do not bump both maps
after unrelated or documentation-only commits. If peer sources are unavailable,
record that limitation without claiming a fresh check. Use HTTPS peer links;
local links stay inside this repository. No machine-specific paths are required.

Run `npm run docs:check` and the repository-doc tests for this map. They check
navigation, not semantic or API compatibility. The existing local manifest
checker remains in Portal CI. The owner removed external source monitoring on
2026-10-19; no replacement monitor is introduced. The historical
[real producer gate](../contracts/kernel-capability-manifest/v1/step-8-handoff.md#real-producer-delivery-gate-separate-integration-activity)
separates producer delivery from consumer conformance. Producer code now exists;
the current joint contract/enablement checks must still be recorded separately.


## ANY-766 Step 8 browser checkpoint — 2026-11-10

The paired frontend now implements fixed PKCE launch/authorization/callback,
tab token custody, same-owner frozen-request replay and accepted-session/mode
restoration. Identity generations guard runtime, events and handoff state. See
[the browser implementation/configuration notes](../contracts/portal-kernel-paid/README.md#step-8-browser-implementation).
This is local synthetic/component evidence; real paid interservice/browser
acceptance remains Step 16. The historical observations above remain historical.


## ANY-766 Step 10 consumer identity checkpoint — 2026-11-11

Inspected peer: Kernel `5aaa0a5fc9f0fdce977dd671727cd5957c13fb39`, plus this paired Step 10 working-tree change.
Portal now serves common backend-session code/exchange/introspection endpoints
with consumer-bound V2 identity, independent credentials/permissions, monotonic
persisted policy guard and generated named Bearer security. Kernel validates
consumer/P and keeps per-request introspection and the original Core owner/replay
partition. The localized authorization page resolves configured fixed callbacks.
Version-1 browser token envelopes require authorization while separate same-owner
pending requests retain their exact request/key. See the
[common configuration/cutover guide](../contracts/product-backend-api/README.md#implemented-step-10-settings-and-cutover).

Portal migration 20261111_0009 preserves populated delegation parent links,
hashes, TTLs and single-use state while binding historical audience to Kernel.
Step 10 needs no Kernel migration or usage reset. Snapshot remains Kernel-only
V2; another consumer cannot read that unfiltered baseline. At this Step 10
checkpoint, source routing and recipient delivery remained Steps 11/13.
The Step 11 checkpoint below supersedes source selection; V3/filtering/coherence
and recipient delivery remain Steps 12/13.
Local synthetic/API/component and disposable PostgreSQL checks are distinct from
Step 16's assembled real HTTP acceptance and ANY-767 remote/live acceptance.


## ANY-766 Step 11 technical-source checkpoint — 2026-11-11

Peer inspected: Kernel `192f4cb2ebf19a697f9fb1298147d26221a0a6a0`.
Portal base: `b346f0e90c9745f942847734bc06d0d3f5b0a73d`, plus the Step 11 diff.
The configured backend registry now selects each product's V1 manifest origin
and independent outbound key. New metered links/terms/purchases bind source and
backend owner; old serializers, saved consent, quantities and allowance IDs are
preserved. Kernel's producer and execution remain unchanged; no new Kernel
scenario or real external product is registered. See the
[source/history guide](../contracts/product-backend-api/README.md#implemented-step-11-technical-sources-and-history).
Synthetic HTTP fixtures with disposable PostgreSQL prove source selection and
history compatibility, not live LBX, real third-party adoption or paired HTTP
acceptance. Generic snapshot/delivery/usage remain later steps.


## ANY-766 Step 12 auth/access checkpoint — 2026-11-11

Peer inspected: Kernel `952a6337a17136cd9d1f3c38cb32d8fa5766a41d`, plus the paired Step 12 working diff.
Portal now serves consumer-filtered V3, selecting products before provenance and
deadline/completeness checks; its cabinet/writer retain whole-user rules. Kernel
migration `0020` preserves R, usage, active reservations and replay while binding
old coherence rows to platform-kernel/P1 and evicting incompatible V2 cache
metadata. Independent durable policy/access floors fence stale response/admission;
P changes do not require a paid R transition. The Portal-owned common API guide
and generated OpenAPI/Swagger document actual identity V2/access V3 security,
schemas, examples, errors, cutover and backend enforcement duties.
Focused real PostgreSQL and local TCP auth/access evidence is separate from the
Step 16 assembled browser/execution journey. The second identity and external
LBX/manifest sources are synthetic; generic recipients/usage remain Steps 13–15.
No real third-party, live payment or deployed acceptance is claimed.


## ANY-766 Step 14 — usage and exhaustion

Kernel now serves authenticated internal and delegated-user product usage V1,
using actual ANY-507 counters and indistinguishable unknown/foreign results.
The API permission `ANYTOOLAI_PORTAL_USAGE_READ_ENABLED` defaults off. Successful
normal/recovery finalization writes one immutable exhaustion edge in the same
transaction. A separately bounded worker task delivers with live-lease ACK,
retry/parking and crash redelivery. Portal validates consumer/product, saved
source/backend owner and full tuple before durably acknowledging one immutable
hint; current hints schedule GET-only reconciliation, historical hints are inert.
Portal's V1 client and retained-owner resolver supply Step 15 cabinet
composition. Kernel `0021` and Portal `20261111_0011` extend previous heads without
resetting usage, purchases or queue history. V1 wire/fixture bytes are unchanged.
See the common backend guide's implemented Step 14 section for settings, errors,
lease/recovery and enablement. Local PostgreSQL and synthetic reverse transport
are covered. Step 16 below supplies focused paired local browser/HTTP acceptance;
the full matrix and live/deployed acceptance remain deferred to ANY-767.

## ANY-766 Step 16 — focused local acceptance

The Portal-owned [joint harness](../../tools/joint_paid_runtime/README.md) composes
the real Portal API/embedded worker and Kernel API/worker over TCP, with separate
disposable PostgreSQL databases and ordinary session/service authentication.
It prepares persisted test purchases through existing publication, consent and
reconciliation paths. LBX/AI responses and the second backend are explicitly
synthetic; no Portal/Kernel endpoint or trusted identity is replaced.

The 2026-11-11 user amendment limits verification to the common backend API and
main paid journeys, including desktop/mobile launch/result/usage and accessibility
checks on Portal surfaces. The synchronized plan owns the actual completion
status and deferred matrix. This is not real third-party adoption or a live
payment/deployed acceptance. Build/install preparation remains Step 17.
