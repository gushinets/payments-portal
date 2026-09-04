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
subscribers or subscriptions to migrate. The long-term production target is
external-billing-managed. The existing direct CloudPayments flow is current and
transitional only; it remains supported while required by current code,
operations, obligations, or a safe cutover. Reintroducing Portal-managed direct-
provider billing as a future production model would require a new explicit
architecture decision.

Treating such an external billing system as another `PaymentProviderAdapter`
would obscure which system is authoritative, create competing lifecycle state,
and allow a command response or an arbitrary update order to grant access.
Payment Portal needs one authority and consistency model for the target external
billing flow while retaining local control of commercial intent and access and
accurately documenting the transitional direct-provider implementation.

## Decision

Payment Portal owns Anytool user identity, catalog and Plan semantics,
entitlement rules, and local entitlements. Platform Kernel consumes those local
entitlements only; it does not derive access from provider or external billing
state.

The long-term production **TARGET** is the external-billing-managed flow. The
Portal-managed direct-provider flow is **CURRENT / TRANSITIONAL**, not a
co-equal future production target:

- In a **Portal-managed direct-provider flow**, Payment Portal orchestrates the
  billing lifecycle and uses a payment provider for payment operations and
  facts. `PaymentProviderAdapter` and `PaymentProviderRegistry` apply only to
  this flow.
- In an **external-billing-managed flow**, the external billing system is
  authoritative for its external customer, invoice, payment, and subscription
  lifecycle. It is not a `PaymentProviderAdapter` and must not be registered in
  `PaymentProviderRegistry`. Payment Portal creates and owns the local purchase
  intent / commercial `Order` after resolving the exact `Plan.id` and validating
  the user, legal, entrypoint, and local commercial context, before sending the
  external billing command. Local `Payment` and `Subscription` records are
  normalized projections of externally authoritative lifecycle state, not a
  competing source of truth; an external invoice identifier may be correlated
  with the Portal-owned order. This is a target semantic decision, not a claim
  that the current direct-provider-shaped physical `orders` schema can represent
  an arbitrary external billing system without separately approved persistence
  adaptation.

Each subscription and its billing lifecycle has exactly one billing owner:
either Payment Portal in a Portal-managed direct-provider flow, or one external
billing system in an external-billing-managed flow. Ownership is never
last-write-wins. This invariant applies to the managed lifecycle, not to the
contour, and this ADR does not choose a database representation, field, enum,
or external-customer schema for it.

An outbound REST command records intent; a successful response does not confirm
payment, subscription activation, or entitlement activation. External commands
are not assumed to be idempotent. Application provides retry-safe orchestration:
it persists and commits the local operation or purchase intent before the
external command, uses provider or vendor idempotency features when available,
and persists a reliable result or mapping afterward.

A timeout or lost response is neither confirmed success nor confirmed failure;
it creates an unknown external outcome. The command must not be blindly retried,
and an uncertain create must not cause another automatic create. Reconciliation
must precede any decision that another external command is safe. Exactly one
unambiguous correlated external object is recovered; no unambiguous match
remains unknown for later reconciliation or an approved safe recovery policy;
multiple plausible matches are ambiguous and fail closed for manual review or
repair. This ADR does not choose persisted unknown/ambiguous states, concrete
lookup fields, timing, or a universal matching algorithm.

An authenticated webhook is the primary asynchronous notification mechanism,
but authenticity is not by itself semantic authority. After authenticity
verification, validation, and normalization, integration policy decides whether
the payload, together with the integration's semantic completeness and
currentness guarantees, is sufficient to produce an authoritative normalized
fact. Otherwise the webhook triggers point reconciliation and verified
server-side external state produces the authoritative normalized fact.
Webhook-derived and reconciliation-derived facts must feed the same normalized
local transition path, not separate state machines. Stale or conflicting facts
are handled by explicit transition rules or trigger reconciliation rather than
overwriting confirmed state.

Billing identity and correlation do not rely on email alone. Correlation uses
validated mappings between local operations or records and opaque external
identifiers. An internal UUID received from an external source is evidence only
after authenticity and context validation. Email remains contact data, not a
billing identity key.

Raw HTTP payloads, vendor DTOs, and vendor-specific statuses stop at the
Integration boundary. Authentication or authenticity verification, decoding,
validation, and necessary redaction precede normalization into typed internal
contracts consumed by Application and Domain logic. Durable webhook receipt
persists only whitelisted or redacted metadata and safe normalized fields needed
for processing, idempotency, correlation, reconciliation, and audit; it does not
imply persistence of the complete raw HTTP request, raw query secrets,
unrestricted headers, authorization or webhook secrets, or unrestricted
sensitive payloads.

Under ANY-407, the existing direct CloudPayments implementation remains a
current/transitional Portal-managed capability while required by current code,
operations, obligations, or safe cutover. Its presence does not make direct-
provider billing part of the long-term target, and it is not removed,
refactored, or decommissioned by this decision. With no production
CloudPayments subscriptions to migrate, this ADR defines no CloudPayments-to-
external-billing migration or coexistence mechanism.

## Relationship to existing decisions

This ADR amends only ADR-0001's universal assumption that each contour
registers a payment-provider adapter. ADR-0001's one-contour-per-production-
instance isolation, local data-plane boundaries, and separate Region Resolver
remain authoritative. Contour enablement or deployment configuration selects
the concrete external-billing integration for the target deployed product. It
may retain the current/transitional direct-provider integration only where
required by current code, operations, obligations, or cutover. Configuration
does not make direct-provider billing a co-equal long-term target, make the
contour the billing owner, or require multiple simultaneously active billing
owners or production integrations.

ADR-0002 remains unchanged: exact persisted `Plan.id` is purchase identity,
access scope is backend-derived, and external/provider identifiers are opaque.
ADR-0003 remains unchanged: `app.models` owns the canonical persisted model
contract and its closed persisted vocabularies.

## Consequences

- Future external-billing work must preserve exactly one billing owner for each
  subscription and its billing lifecycle, and normalize authoritative external
  facts before local transitions.
- Future external-billing work must preserve the Portal-owned local purchase
  intent / commercial order created before the external billing command.
- Future command orchestration must remain retry-safe without assuming external
  command idempotency, and must reconcile unknown outcomes before retry.
- Ambiguous external identity must fail closed for manual review or repair.
- Payment Portal remains the only billing-side authority for entitlements, so
  Platform Kernel has one local access contract regardless of billing owner.
- Direct-provider and external-billing capabilities remain separate; the former
  is current/transitional and the latter is the sole long-term production
  target. Neither is generalized into a speculative common adapter by this ADR.
- Webhook and reconciliation delivery can converge idempotently without
  competing state machines or last-write-wins updates.
- No runtime behavior, persistence schema, vendor selection, or external-
  billing interface is introduced by this decision.
- Reintroducing Portal-managed direct-provider billing as a future production
  model requires a new explicit architecture decision.
- Any future migration or coexistence requirement needs separate explicit
  approval; this ADR does not design one.

The detailed authority, terminology, trust-boundary, and transitional package
mapping are documented in
[Billing Authority and Consistency](../billing-authority.md).

## Superseded decisions

The universal payment-provider-adapter assumption in ADR-0001 is superseded.
No other decision is superseded.
