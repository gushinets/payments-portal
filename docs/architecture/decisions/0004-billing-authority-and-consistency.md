# 0004. Billing authority and consistency

Status: accepted
Date: 2026-09-04

Amends: [ADR 0001](0001-multi-contour-billing.md), only where it assumes that
every contour registers a payment-provider adapter.

Preserves: [ADR 0002](0002-plan-based-checkout-identity.md) and
[ADR 0003](0003-canonical-persisted-model-layer.md).

## Context

Payment Portal is under development and is not running as a production billing
service. The current `ru` implementation contains a Portal-managed billing
flow: Payment Portal orchestrates billing and reaches CloudPayments through a
direct payment provider adapter. There are no production CloudPayments
subscribers or subscriptions to migrate. Current product planning anticipates
an external-billing-managed launch, but that is planning context rather than an
architectural invariant. The existing implementation does not define the
architecture for a system that owns its own customer, invoice, payment, and
subscription lifecycle.

Treating such an external billing system as another `PaymentProviderAdapter`
would obscure which system is authoritative, create competing lifecycle state,
and allow a command response or an arbitrary update order to grant access.
Payment Portal needs one authority and consistency model that supports both
billing flows while retaining local control of access.

## Decision

Payment Portal owns Anytool user identity, catalog and Plan semantics,
entitlement rules, and local entitlements. Platform Kernel consumes those local
entitlements only; it does not derive access from provider or external billing
state.

The two billing flows are distinct:

- In a **Portal-managed direct-provider flow**, Payment Portal orchestrates the
  billing lifecycle and uses a payment provider for payment operations and
  facts. `PaymentProviderAdapter` and `PaymentProviderRegistry` apply only to
  this flow.
- In an **external-billing-managed flow**, the external billing system is
  authoritative for its external customer, invoice, payment, and subscription
  lifecycle. It is not a `PaymentProviderAdapter` and must not be registered in
  `PaymentProviderRegistry`. Local `Order`, `Payment`, and `Subscription`
  records are normalized projections used by Payment Portal, not a competing
  source of truth. This is a target semantic decision, not a claim that the
  current direct-provider-shaped physical schema can represent an arbitrary
  external billing system without separately approved persistence adaptation.

Each subscription and its billing lifecycle has exactly one billing owner:
either Payment Portal in a Portal-managed direct-provider flow, or one external
billing system in an external-billing-managed flow. Ownership is never
last-write-wins. This invariant applies to the managed lifecycle, not to the
contour, and this ADR does not choose a database representation, field, enum,
or external-customer schema for it.

An outbound REST command records intent; a successful response does not confirm
payment, subscription activation, or entitlement activation. For an external
billing owner, a verified webhook is the primary asynchronous authoritative
fact. Reconciliation recovers missing or uncertain delivery and must feed the
same normalized local transition path as webhook processing. It is not a
second state machine. Stale or conflicting facts are handled by explicit
transition rules or trigger reconciliation rather than overwriting confirmed
state.

Billing identity and correlation do not rely on email alone. Correlation uses
validated mappings between local operations or records and opaque external
identifiers. An internal UUID received from an external source is evidence only
after authenticity and context validation. Email remains contact data, not a
billing identity key.

Raw HTTP payloads, vendor DTOs, and vendor-specific statuses stop at the
Integration boundary. Authentication or authenticity verification, decoding,
validation, and necessary redaction precede normalization into typed internal
contracts consumed by Application and Domain logic.

Under ANY-407, the existing direct CloudPayments implementation remains a
transitional Portal-managed capability until separately approved architecture
or refactoring work determines whether it is still needed. Its presence does
not imply production use, and it is not removed, refactored, or decommissioned
by this decision. With no production CloudPayments subscriptions to migrate,
this ADR defines no CloudPayments-to-external-billing migration or coexistence
mechanism.

## Relationship to existing decisions

This ADR amends only ADR-0001's universal assumption that each contour
registers a payment-provider adapter. ADR-0001's one-contour-per-production-
instance isolation, local data-plane boundaries, and separate Region Resolver
remain authoritative. Contour enablement or deployment configuration may
select one concrete active billing model and integration for the deployed
product. That selection does not make the contour the billing owner, does not
make one owner a permanent property of the contour, and does not require
multiple simultaneously active billing owners or production integrations.

ADR-0002 remains unchanged: exact persisted `Plan.id` is purchase identity,
access scope is backend-derived, and external/provider identifiers are opaque.
ADR-0003 remains unchanged: `app.models` owns the canonical persisted model
contract and its closed persisted vocabularies.

## Consequences

- Future external-billing work must preserve exactly one billing owner for each
  subscription and its billing lifecycle, and normalize authoritative external
  facts before local transitions.
- Payment Portal remains the only billing-side authority for entitlements, so
  Platform Kernel has one local access contract regardless of billing owner.
- Direct-provider and external-billing capabilities may evolve independently;
  neither is generalized into a speculative common adapter by this ADR.
- Webhook and reconciliation delivery can converge idempotently without
  competing state machines or last-write-wins updates.
- No runtime behavior, persistence schema, vendor selection, or external-
  billing interface is introduced by this decision.
- Any future migration or coexistence requirement needs separate explicit
  approval; this ADR does not design one.

The detailed authority, terminology, trust-boundary, and transitional package
mapping are documented in
[Billing Authority and Consistency](../billing-authority.md).

## Superseded decisions

The universal payment-provider-adapter assumption in ADR-0001 is superseded.
No other decision is superseded.
