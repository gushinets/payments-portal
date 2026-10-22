# 0005. External billing boundary

Status: accepted
Date: 2026-09-18

Supersedes for new billing development:
[ADR 0002](0002-plan-based-checkout-identity.md),
[ADR 0004](0004-billing-authority-and-consistency.md), and conflicting target
semantics in related legacy documentation.

## Context

The target external-billing architecture needs one explicit ownership and
documentation-precedence decision. Retained Portal-managed billing code and its
documentation remain useful current-state context, but they must not define the
target or turn External Billing into a direct payment-provider integration.

## Decision

- External Billing owns commercial billing truth and lifecycle.
- Payment Portal owns AnyToolAI identity and legal acceptance; the external-
  billing anti-corruption, projection, reconciliation, and recovery boundary;
  and provider-neutral paid-access projection and delivery.
- Platform Kernel owns technical product and metric vocabulary, durable actual
  usage, and quota enforcement.
- External Billing is not a `PaymentProviderAdapter` and is never registered in
  `PaymentProviderRegistry`. Payment Portal is not the target payment
  orchestrator.
- The accepted
  [external-billing boundary design](../../superpowers/specs/2026-09-15-external-billing-boundary-design.md)
  and
  [Portal-Kernel access-contract design](../../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md)
  are the normative implementation baselines, with the accepted
  [live-source commercial admission amendment](../../superpowers/specs/2026-10-15-live-source-commercial-admission-design-amendment.md)
  taking precedence only for source-catalog reads and new-operation admission
  (owner confirmation, 2026-10-20). Publication and each new purchase require
  live Kernel/LBX evidence; approved immutable terms are stored and browsed in
  PostgreSQL. There is no periodic source-catalog mirror or catalog-age sale
  permission. Subscription reconciliation/trust, paid-access derivation and
  AccessSnapshot are unchanged. New target development follows this ADR and
  those specifications with that narrow supersession.
- Conflicting target semantics in ADR 0002, ADR 0004, and related legacy
  documentation are superseded. Retained legacy implementation and its
  current-state documentation remain available until later controlled,
  separately gated cleanup.
- `ANY-504` controls implementation sequence. Provider-independent
  pre-production cleanup may precede Phase 0 PASS. Phase 0 remains the hard gate
  for provider-dependent production semantics, Widget/LBX production behavior,
  and launch.

## Implementation status, 2026-10-23

The retained implementation described in the original context and decision
has since been physically removed. ANY-664 now supplies restricted immutable
mapping publication and DB-only catalog browsing; purchases and paid access
remain future work. See the current [architecture](../../../ARCHITECTURE.md).
The retained wording records the decision's transition history and does not
assert that executable direct-provider code still exists.

## Consequences

- Target billing work has one authority chain: this ADR and the two accepted
  implementation baselines, narrowly superseded by the accepted live-source
  amendment for source reads/admission only.
- Historical direct-provider behavior remains characterizable without becoming a
  target architecture option.
- Unverified provider-dependent assumptions remain explicit Phase 0 gates and
  cannot grant production authority.
- ADR 0001's contour isolation and Region Resolver decisions remain accepted.
