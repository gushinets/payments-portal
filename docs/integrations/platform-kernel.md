# Platform Kernel integration map

Status: navigation and implementation snapshot; normative contracts are delegated below.
Last observed: 2026-10-23.

## Ownership and sources

Portal owns identity, sessions, legal acceptance, public discovery and the
cabinet. Its target owns approved commercial-to-technical mappings, paid
grants/allowances, access revisions and delivery. External Billing owns
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
Platform `79a2ada5b790f959a40b3e08451ef9ed8d97da5b`.
These identify inspected source snapshots, not a verified joint deployment.

| Operation / request direction | Payload producer | Payload consumer / receiver | Verification status |
| --- | --- | --- | --- |
| `GET /internal/v1/capability-manifest`: Portal -> Kernel | Real Kernel endpoint not implemented; optional separate development HTTP mock exists in Portal | Portal typed HTTP client implemented | Local mock/client CI PASS; real producer deferred |
| `GET /internal/v1/access-snapshots/{user_id}`: Kernel -> Portal | Portal paid-access producer not implemented | Kernel snapshot client/cache/revision floor not implemented | Target contract only |
| `POST /internal/v1/access-invalidations`: Portal -> Kernel | Portal invalidation producer/delivery not implemented | Kernel receiver endpoint not implemented | Target contract only |

ANY-664 implemented restricted v1 publication and DB-only browsing. ANY-709
Step 1 now implements direct versioned links, one current product pointer,
enabled-product discovery and current selected LBX offers. Kernel wire semantics
and the pinned peer observation above are unchanged; no fresh peer inspection
or real producer conformance is claimed. Source projection slots remain inert. Purchase orchestration,
subscription reconciliation, paid-access derivation and actual cabinet usage
remain later work; stored approved terms do not promise current sellability.

Evidence: [publication](https://github.com/gushinets/payments-portal/blob/79dc3f4d204aec4ac9552e3d1da3481553cc8aef/apps/api/app/domains/catalog/publication.py),
[typed client](https://github.com/gushinets/payments-portal/blob/79dc3f4d204aec4ac9552e3d1da3481553cc8aef/apps/api/app/integrations/kernel/client.py),
[Kernel routes](https://github.com/gushinets/anytoolai-platform/blob/79a2ada5b790f959a40b3e08451ef9ed8d97da5b/apps/platform-api/src/anytoolai_platform_api/main.py)
and [Step 8 handoff](../contracts/kernel-capability-manifest/v1/step-8-handoff.md).
The handoff records `LOCAL_SPEC_CONFORMANCE=PASS` for historical CI and
`REAL_KERNEL_CONFORMANCE=DEFERRED_NOT_IMPLEMENTED`. It does not claim a fresh
run, completion of every manual procedure or real producer compatibility.

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
- **Producer delivery:** Kernel API owners supply the actual endpoint,
  producer-owned schema and fixtures, approved paid metrics/units/releases and
  service-authenticated tenant/region deployment. Portal integration owners pin
  and reconcile those artifacts and run real consumer-versus-producer checks.
  Until then [provisional artifacts](../contracts/kernel-capability-manifest/v1/README.md)
  retain their historical pins and SIMULATED status; no shared runtime SDK.
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

## ANY-765 Step 1 consumer alignment

Producer-owned ANY-711 contract and error models were inspected read-only at
`e627bf296a6476efcca839a0328cf1a5683555e2`; see the
[producer contract](https://github.com/gushinets/anytoolai-platform/blob/e627bf296a6476efcca839a0328cf1a5683555e2/docs/contracts/kernel-capability-manifest/v1/README.md).
The existing positive fixture/digest are retained. The local mock adds the
all-disabled inventory and safe 500/503 producer-shaped error envelope. This
source inspection does not claim a new real Kernel HTTP run.

Portal review/new confirmation validate the two test metrics' current owner,
unit and enabled flags. Quantities 100/300 belong exclusively to the separate
explicitly enabled development purchase dataset and accepted v2 history; the
manifest and commercial link carry no technical quantity. SIMULATED provenance
survives configuration changes. No peer edit, shared runtime package, access
delivery, usage or production metric approval is introduced by this step.
