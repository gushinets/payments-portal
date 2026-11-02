# Platform Kernel integration map

Status: navigation and implementation snapshot; normative contracts are delegated below.
Last observed: 2026-11-02 for read-only local Kernel composition/contract inspection; historical evidence pins are retained below.

## Ownership and sources

Portal owns identity, sessions, legal acceptance, public discovery, the cabinet,
immutable commercial-to-technical mappings, local paid grants/allowances and
access revisions. Kernel HTTP delivery remains planned. External Billing owns
commercial billing truth and lifecycle. The separate
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

Evidence baselines: Portal `79dc3f4d204aec4ac9552e3d1da3481553cc8aef`;
Platform access-delivery snapshot `79a2ada5b790f959a40b3e08451ef9ed8d97da5b`.
ANY-765 Step 1 inspected the newer manifest producer/contract at
[`e627bf2`](https://github.com/gushinets/anytoolai-platform/blob/e627bf296a6476efcca839a0328cf1a5683555e2/docs/contracts/kernel-capability-manifest/v1/README.md).
These identify historical source evidence, not a verified joint deployment.
The 2026-11-02 local peer inspection is recorded below.

| Operation / request direction | Payload producer | Payload consumer / receiver | Verification status |
| --- | --- | --- | --- |
| `GET /internal/v1/capability-manifest`: Portal -> Kernel | Kernel producer implemented at inspected `e627bf2`; Portal retains a separate development mock | Portal typed HTTP client implemented | Source alignment and local mock/client CI PASS; new deployed conformance NOT_RUN |
| `GET /internal/v1/access-snapshots/{user_id}`: Kernel -> Portal | Local paid projection implemented; snapshot HTTP endpoint not implemented | Kernel snapshot client/cache/revision floor not implemented | Target wire contract only |
| `POST /internal/v1/access-invalidations`: Portal -> Kernel | Atomic outbox producer implemented; HTTP delivery not implemented | Kernel receiver endpoint not implemented | Local outbox implemented; HTTP integration deferred |

ANY-664 implemented restricted v1 publication and DB-only browsing. ANY-709
Step 1 now implements direct versioned links, one current product pointer,
enabled-product discovery and current selected LBX offers. Kernel wire semantics
and the historical pinned peer observation above are unchanged. The newer
source inspection below does not establish real producer HTTP conformance.
Source projection slots remain inert.
ANY-709 implements purchase orchestration; ANY-715 implements subscription
reconciliation and GET-only recovery without Kernel calls. ANY-765 Step 2 adds
local paid derivation. Step 4 adds authenticated `GET /api/paid-access` and
committed paid-state cabinet presentation. Kernel delivery and actual usage
remain later work. Stored accepted terms do not promise current sellability. See the
[billing operations guide](../engineering/billing-background-operations.md) for
current behavior and the Step 9/10 handoff; no Kernel wire contract or
peer-verification status changes with this implementation.

Evidence: [publication](https://github.com/gushinets/payments-portal/blob/79dc3f4d204aec4ac9552e3d1da3481553cc8aef/apps/api/app/domains/catalog/publication.py),
[typed client](https://github.com/gushinets/payments-portal/blob/79dc3f4d204aec4ac9552e3d1da3481553cc8aef/apps/api/app/integrations/kernel/client.py),
[Kernel routes](https://github.com/gushinets/anytoolai-platform/blob/79a2ada5b790f959a40b3e08451ef9ed8d97da5b/apps/platform-api/src/anytoolai_platform_api/main.py)
and [Step 8 handoff](../contracts/kernel-capability-manifest/v1/step-8-handoff.md).
The handoff records `LOCAL_SPEC_CONFORMANCE=PASS` for historical CI and
`REAL_KERNEL_CONFORMANCE=DEFERRED_NOT_IMPLEMENTED` at that historical checkpoint.
The newer producer source observation above does not turn it into a deployed
conformance PASS.

## Dependencies before real integration

- **Identity:** paid access uses Portal's authenticated UUID under
  `(tenant_id, region, user_id)`. Kernel currently accepts an unverified
  scenario `user_id` ([TD-013](https://github.com/gushinets/anytoolai-platform/blob/79a2ada5b790f959a40b3e08451ef9ed8d97da5b/docs/tech-debt-tracker.md)).
  Guest quota is not a paid allowance or proof of Portal authentication.
- **Scope:** [Kernel Settings](https://github.com/gushinets/anytoolai-platform/blob/79a2ada5b790f959a40b3e08451ef9ed8d97da5b/apps/platform-api/src/anytoolai_platform_api/settings.py)
  and [region config](https://github.com/gushinets/anytoolai-platform/blob/79a2ada5b790f959a40b3e08451ef9ed8d97da5b/configs/kernel/regions.yaml)
  use `anytoolai/default`; [Portal Settings](../../apps/api/app/core/settings.py)
  permits `anytoolai/ru`, and its client rejects mismatched response scope.
  Real deployment alignment is separate work. Locale and country do not select
  authenticated scope; do not rename existing scopes as a documentation fix.
- **Producer/deployment:** inspected ANY-711 supplies the manifest producer,
  schema and fixtures. Deployment conformance and production paid metric/quantity
  approval remain separate. Portal owns consumer verification; retained
  [development artifacts](../contracts/kernel-capability-manifest/v1/README.md)
  keep their historical pins and SIMULATED provenance. No shared runtime SDK.
- **Enablement:** ANY-709 Step 1 accepts ordinary configured HTTPS Kernel/LBX
  connections without a blanket production refusal. Explicit Kernel mock mode
  remains development/test-only and SIMULATED, including after URL changes.
  A non-mock endpoint is CONFIGURED_SOURCE, never proof of producer conformance
  or production sales approval. Real producer delivery/conformance remains
  ANY-711. Portal can start without Kernel config.
- **Usage and launch:** the three operations above do not define an actual
  usage/remaining API for the cabinet. That contract and authenticated cross-app
  launch remain separate work. Kernel product-to-product handoff is not Portal
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
2026-10-19; the [real producer gate](../contracts/kernel-capability-manifest/v1/step-8-handoff.md#real-producer-delivery-gate-separate-integration-activity)
remains future work. Delivery: [ANY-728](https://linear.app/paveldik/issue/ANY-728),
companion [ANY-727](https://linear.app/paveldik/issue/ANY-727).

## Development manifest alignment

The existing positive fixture/digest is retained. The mock adds all-disabled and
safe 500/503 producer-shaped errors based on the source inspection above; this
is not a new real-producer HTTP run. Portal confirmation validates metric owner,
unit and enablement. SIMULATED 100/300 quantities live only in explicit dev/test
accepted terms, never in the manifest; see the
[purchase runbook](../engineering/ANY-709-billing-runbook.md#development-purchase-metering-any-765-step-1).

## Customer paid-state contract

The Portal-only `GET /api/paid-access` exposes committed local paid state to the
ordinary authenticated cabinet. It is not the internal Kernel AccessSnapshot,
and changes no Kernel DTO, fixtures, hashes, authentication or networking.
Purchased SIMULATED quantities/provenance are shown without actual usage or
remaining. Deadline refusal and read-only behavior are described in the
[billing operations guide](../engineering/billing-background-operations.md#customer-paid-state-read-and-kernel-handoff).

Read-only peer refresh on 2026-11-02 inspected the clean local Kernel `main` at
`331e086ca9e0c72eb757aacc476bad5bacb5bae5`: architecture, API composition,
manifest router and producer contract still separate guest quota from future
paid integration. The manifest producer is present; the access snapshot and
invalidation routes are absent from that composition. Source inspection does
not establish deployed HTTP conformance. ANY-766 owns the
coordinated B10 specification/producer/consumer change and Kernel delivery;
actual usage/remaining and cross-app launch remain separate interfaces.
