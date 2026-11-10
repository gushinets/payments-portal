# Platform Kernel integration map

Status: navigation and implementation snapshot; normative contracts are delegated below.
Last source inspection: 2026-11-09; pinned snapshots below, not a deployment check.

## Ownership and sources

Portal owns identity, sessions, legal acceptance, public discovery and the
cabinet, approved commercial-to-technical mappings, local paid grants/allowances,
access revisions and outbox production. Kernel delivery remains future work.
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

Inspected source snapshots: Portal `ac8743ff35c5cfaf0fdaf108fa89ad5e71bf49cd`
plus its local review corrections; Kernel
`72ff15bc0b77903c87aa39f7b10186dccc556d09` from the local `origin/main` ref.
These are read-only source observations, not a fresh remote-ref, joint deployment
or producer-conformance check. Dated runtime evidence remains separate.

| Operation / request direction | Payload producer | Payload consumer / receiver | Verification status |
| --- | --- | --- | --- |
| `GET /internal/v1/capability-manifest`: Portal -> Kernel | Service-authenticated Kernel endpoint implemented; separate Portal development mock remains optional | Portal typed HTTP client implemented | Source inspected; local fixture evidence does not establish current joint conformance |
| `GET /internal/v1/access-snapshots/{user_id}`: Kernel -> Portal | Local paid projection and cabinet read implemented; internal snapshot HTTP producer remains ANY-766 | Kernel internal metering exists; snapshot HTTP client/cache integration remains ANY-766 | Target wire only; `/api/paid-access` is a separate customer contract |
| `POST /internal/v1/access-invalidations`: Portal -> Kernel | Durable coalesced outbox implemented; HTTP delivery remains ANY-766 | Kernel HTTP invalidation receiver remains ANY-766 | Target wire only; no delivery PASS claimed |

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

The [server configuration and limits](../contracts/portal-kernel-paid/README.md#step-4-server-implementation)
include independent directional credentials, explicit receiver permissions,
rotation, fixed audience, parent revocation, finite deadlines, no-store and
secret-safe refusals. Local PostgreSQL tests cover migration/cascade/single-use
races; Kernel HTTP is intercepted in focused boundary tests. This is not real
two-service HTTP or deployed acceptance. Browser launch/recovery remains Step 8;
paid runtime wiring and ownership enforcement remain Step 6. Existing guest
routes are unchanged. Snapshot, usage and delivery retain their later gates.

## Dependencies before real integration

- **Identity:** paid access uses Portal's authenticated UUID under
  `(tenant_id, region, user_id)`. Browser identity delegation and authenticated
  paid HTTP integration remain ANY-766. Guest quota or an internal metering test
  is not proof of Portal authentication.
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
  usage/exhaustion and authenticated cross-app launch; runtime delivery remains
  later ANY-766 work. Kernel product-to-product handoff is not Portal
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
