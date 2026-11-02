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

**Dated ANY-709 decisions:** C1-C4 in **"Accepted ANY-709 contract decisions
— 2026-10-31"** in [ANY-504](https://linear.app/paveldik/issue/ANY-504) override the
baseline clauses they explicitly identify. That section owns exact scope,
rationale, retained guarantees and evidence limits; the accepted specification
bodies are preserved. Ownership above and every other clause remain in force.
[ANY-709](https://linear.app/paveldik/issue/ANY-709), section **"ANY-709 result and
contract deviations — 2026-10-31"**, owns results and verification. Ordinary issue
text, reports, passing tests and checkboxes do not create further exceptions.
The additional owner decision below has only the stated point-read scope.

### Accepted point-resource identity decision - 2026-11-01

The owner explicitly accepts authenticated LBX point endpoints as the resource
selection boundary for `GET /users/{id}`, `/tariffs/{id}`, `/agreements/{id}`
and `/subscriptions/{id}`. Portal validates the wire schema once in the
Integration and relies on the point URL to select the requested canonical
resource. A second comparison of the response's self-ID with the URL ID is not
required and must not be restored solely to defend against a hypothetical
violation of that endpoint's resource-selection contract.

This resolves the P1 discussion in [PR #150](https://github.com/gushinets/payments-portal/pull/150#discussion_r4434768469).
No observed LBX response, documented provider limitation or independently
reachable Portal scenario has established such a selection violation. A mock
returning an unrelated resource demonstrates that injected assumption, not a
required production guard. This is an accepted integration assumption, not a
new claim that provider conformance was tested.

Precise precedence: the September design's Phase 0 E canonical
`users.user_id == provider_customer_id` proof and canonical subscription
readback requirements are satisfied by the authenticated canonical point lookup
together with the retained identity/relationship proof. They do not require a
separate returned-self-ID-versus-requested-ID assertion. The same selection
rule applies to tariff and agreement point reads. The accepted specification
bodies remain unchanged.

Original customer-key proof, retained canonical bindings, ambiguity handling,
customer/agreement ownership, seller, subscription agreement/tariff/composition,
effective terms, session/email/contour checks, Client readiness and final
session/fence admission remain required. Discovery and CREATE receipts remain
candidates until point proof; an existing binding cannot be replaced by a
different canonical ID. This decision does not remove relationship checks or
permit financial replay, paid access or production launch. Concrete evidence
that a supported point endpoint selects another resource requires a targeted
reassessment of this assumption.

## Implementation status

The former direct-provider runtime has been physically removed. ANY-709 adds
direct product links, live offers, account Widget and accepted-purchase
preparation/recovery. ANY-765 implements local paid projection, deadlines,
revision/outbox commits and authenticated cabinet reads; Kernel HTTP delivery
remains later work. Current boundaries are in
[ARCHITECTURE](../../../ARCHITECTURE.md); paid-access scope and acceptance
criteria are in the [ANY-765 plan](../../exec-plans/active/ANY-765-implementation-plan.md).
The original context above records transition history.

## Consequences

- Target billing work has one authority chain: this ADR and the two accepted
  implementation baselines, narrowly superseded by the accepted live-source
  amendment for source reads/admission only.
- Historical direct-provider behavior remains characterizable without becoming a
  target architecture option.
- Unverified provider-dependent assumptions remain explicit Phase 0 gates and
  cannot grant production authority.
- ADR 0001's contour isolation and Region Resolver decisions remain accepted.
