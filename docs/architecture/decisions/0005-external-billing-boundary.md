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
  are the normative implementation baselines. New target development follows
  this ADR and those specifications.
- Conflicting target semantics in ADR 0002, ADR 0004, and related legacy
  documentation are superseded. Retained legacy implementation and its
  current-state documentation remain available until later controlled,
  separately gated cleanup.
- `ANY-504` controls implementation sequence. Provider-independent
  pre-production cleanup may precede Phase 0 PASS. Phase 0 remains the hard gate
  for provider-dependent production semantics, Widget/LBX production behavior,
  and launch.

## Consequences

- Target billing work has one authority chain: this ADR and the two accepted
  implementation baselines.
- Current direct-provider behavior remains characterizable without becoming a
  target architecture option.
- Unverified provider-dependent assumptions remain explicit Phase 0 gates and
  cannot grant production authority.
- ADR 0001's contour isolation and Region Resolver decisions remain accepted.
