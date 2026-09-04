# Billing Authority and Consistency

Status: normative architecture
Last verified: 2026-09-04

This document expands the decision in
[ADR 0004](decisions/0004-billing-authority-and-consistency.md). It preserves
[ADR 0001](decisions/0001-multi-contour-billing.md) contour isolation,
[ADR 0002](decisions/0002-plan-based-checkout-identity.md) purchase identity,
and [ADR 0003](decisions/0003-canonical-persisted-model-layer.md) persisted
model ownership.

## Architecture states

### CURRENT

Payment Portal is under development and is not running as a production billing
service. The implemented `ru` code contains a Portal-managed direct-provider
flow: Payment Portal orchestrates checkout and the local billing lifecycle,
uses the CloudPayments widget and direct API, accepts verified CloudPayments
webhooks, and derives and persists local entitlements. There are no production
CloudPayments subscribers or subscriptions to migrate. The private regional
entitlement/access API for Platform Kernel is still planned under ANY-79.

### TARGET

The target architecture supports an external-billing-managed flow. In that
flow, the external billing system owns its external lifecycle, Payment Portal
projects verified facts into normalized local billing records, and Payment
Portal applies its entitlement rules. The architecture also permits a Portal-
managed direct-provider flow when that is the selected active model. Platform
Kernel is the intended consumer of Payment Portal's local entitlements through
the planned private entitlement/access API.

The durable ownership invariant is: **each subscription and its billing
lifecycle has exactly one billing owner: either Payment Portal in a
Portal-managed direct-provider flow, or one external billing system in an
external-billing-managed flow.** Billing ownership belongs to the managed
lifecycle, not to the contour. Contour enablement or deployment configuration
may select one concrete active billing model and integration for the deployed
product; this does not require multiple simultaneously active billing owners or
production billing integrations.

This target meaning does not assert current persistence readiness. The
implemented `Order` and `Payment` schema still requires direct-provider account
references and other provider-oriented fields and constraints. `Subscription`
allows nullable provider references, but there is no general external-billing
ownership or external-ID mapping representation. As detailed in the
[data-model persistence clarification](payment-portal-data-model.md#persistence-readiness-for-external-billing),
a concrete external-billing integration may require separately approved minimal
schema adaptation; ANY-411 does not decide it.

### TRANSITIONAL

Under ANY-407, the current direct CloudPayments implementation remains as a
transitional Portal-managed capability until separately approved architecture
or refactoring work determines whether it is still needed. Transitional code
describes what exists; it does not imply production use, must not be copied as
the target external-billing design, and is not removed or refactored by this
decision. Because there are no production CloudPayments subscriptions, this
document defines no CloudPayments-to-external-billing migration or coexistence
mechanism.

## Terminology

- **Payment provider:** a direct payment or acquiring provider used by a
  Portal-managed flow. CloudPayments is the current example. It may be hidden
  behind `PaymentProviderAdapter`.
- **External billing system:** a system authoritative for its external
  customer, invoice, payment, and subscription lifecycle. It is not a
  `PaymentProviderAdapter`.
- **Portal-managed flow:** Payment Portal orchestrates the billing lifecycle
  and uses a direct payment provider for payment operations and facts.
- **External-billing-managed flow:** an external billing system owns the
  external lifecycle; Payment Portal sends commands and projects authoritative
  facts locally.
- **Billing owner:** the single authority allowed to manage one subscription
  and its billing lifecycle. This document does not choose its persisted
  representation.
- **Command:** an outbound request or intention. A successful call is not final
  billing-state authority.
- **Authoritative fact:** an authenticated and validated fact from the owning
  billing source, normally a verified webhook or a verified reconciliation
  result.
- **Normalized local projection:** Payment Portal's local representation of
  externally authoritative billing state. It is not a bidirectional
  synchronization peer.
- **Reconciliation:** recovery or verification of authoritative external state
  through the same local transition path used for webhook facts.
- **Entitlement:** Payment Portal's local access authority consumed by Platform
  Kernel.
- **Internal identity:** a Portal-owned UUID identity.
- **External mapping:** persisted correlation between internal records and
  opaque external identifiers. Email is not an identity mapping.

## Authority matrix

| Concern | Authority |
| --- | --- |
| Anytool user identity | Payment Portal |
| Catalog, Product, and Plan semantics | Payment Portal |
| Exact purchase identity | Payment Portal `Plan.id` |
| Local entitlement rules | Payment Portal |
| Local entitlements | Payment Portal |
| Runtime access decision | Payment Portal entitlements consumed by Platform Kernel |
| Workflow execution and usage consumption | Platform Kernel |
| Direct CloudPayments orchestration | Payment Portal while the transitional Portal-managed flow exists |
| External customer lifecycle | Owning external billing system |
| External invoice lifecycle | Owning external billing system |
| External payment lifecycle | Owning external billing system |
| External subscription lifecycle | Owning external billing system |
| Local `Order`, `Payment`, and `Subscription` under external billing | Normalized Payment Portal projections |
| Raw vendor HTTP schemas and status vocabularies | Owning Integration only |

## Billing flows

### Portal-managed direct-provider flow

```text
Payment Portal
    -> PaymentProviderAdapter
    -> direct payment provider
    -> verified provider fact
    -> local billing transition
    -> Payment Portal entitlement rules
    -> local entitlement
```

Payment Portal owns and orchestrates this billing lifecycle. The current
CloudPayments integration is this kind of flow.

### External-billing-managed flow

```text
Payment Portal Application
    -> command
external billing system
    -> verified webhook or reconciliation fact
Integration normalization
    -> shared local transition path
local Order / Payment / Subscription projection
    -> Payment Portal entitlement rules
    -> local entitlement
```

The external system owns the external lifecycle. It does not write
entitlements, and Platform Kernel does not query it. `PaymentProviderAdapter`
and `PaymentProviderRegistry` do not represent or register this flow.

## Authoritative facts and consistency

An outbound command and its HTTP result report that a request was attempted or
accepted. They do not confirm payment, subscription activation, or entitlement
activation. Local intent and external mappings must be idempotent, but the
authoritative transition follows a verified fact from the billing owner.

Verified webhooks are the primary asynchronous facts. Reconciliation recovers
from missing, delayed, or uncertain delivery. Both sources must normalize into
the same future local transition rules so retries and reordered delivery
converge. Reconciliation must not create a parallel state machine.

There is no last-write-wins billing state. A stale, duplicate, or conflicting
fact is rejected or ignored according to explicit transition and idempotency
rules, or it triggers reconciliation. It does not blindly downgrade or
overwrite newer confirmed local state.

## Identity and correlation

Billing correlation uses the strongest validated evidence available, in this
order of relationship:

```text
local operation or order <-> known external invoice/subscription mapping
                         -> known external customer mapping
                         -> recorded internal UUID in a verified external fact
```

An internal UUID carried by an external payload becomes correlation evidence
only after the payload's authenticity and context are validated. Opaque
external identifiers remain opaque, as required by ADR-0002.

Email may be customer or contact data, but it is not billing identity and
cannot be the sole correlation key. The current CloudPayments use of
`AccountId=email` is transitional legacy behavior. It remains unchanged in the
current runtime and must not be copied into an external-billing design.

## Trust boundary

All provider and external-billing input follows this boundary:

```text
untrusted input
    -> authentication or authenticity verification
    -> validation and decoding
    -> redaction as needed
    -> normalized typed internal contract
    -> Application
    -> Domain transition
```

Raw provider or vendor payloads and status strings stay at the Integration
edge. Application and Domain logic consume normalized internal contracts, not
vendor DTOs or `dict[str, Any]`. Sensitive raw payloads must not enter logs or
traces. Browser return URLs are informational and never authoritative for paid
access.

## Logical layer responsibilities

| Layer | Owns | Must not own or depend on |
| --- | --- | --- |
| Presentation | HTTP, webhook, CLI and job entrypoints; request/response contracts; authentication context; boundary decoding and error mapping; invoking Application use cases | Billing state machines, transaction orchestration, arbitrary ORM mutation, concrete external workflows |
| Application | Use cases, commands and queries, orchestration, transaction boundaries, idempotency and recovery, normalized internal contracts, calls to required persistence and integration capabilities | FastAPI, routers, raw payloads, vendor DTOs or vendor status strings |
| Domain | Business invariants, valid transitions, and entitlement rules independent of transport and vendor protocol | FastAPI, HTTP, provider clients, vendor schemas, SQLAlchemy sessions, observability SDKs |
| Persistence / Infrastructure | SQLAlchemy queries, loading and saving, locking, and other persistence mechanics used by Application | Payment lifecycle, entitlement, or billing-ownership decisions |
| Integrations | External protocols and clients, authentication/signature verification, parsing, redaction, vendor DTOs, normalization, and command mapping | A second local state machine, arbitrary local ORM mutation, or entitlement decisions |
| Core | Configuration, session factories, logging, tracing and metrics infrastructure, generic security helpers, time and infrastructure utilities | Shared business logic or inward dependencies on billing domains and integrations |
| Composition / Wiring | Constructing concrete adapters and clients, lifecycle wiring, and binding implementations to capabilities | Business decisions or a deep runtime service locator |

The normative logical dependency direction is:

```text
Presentation -> Application -> Domain

Application -> required persistence and integration capabilities
Persistence / Integrations -> implementations of those capabilities
Composition -> concrete wiring
```

The target logical model does not require speculative package creation or one
repository per ORM model. `app.models` remains the canonical persisted model
contract established by ADR-0003; no second pure-domain entity model is
introduced.

## Current package mapping

| Current package or module | Logical role and status |
| --- | --- |
| `app.main` | Composition root that constructs CloudPayments and the provider registry, wires routers, and owns application lifespan. |
| `app.models` | Canonical persisted model contract. It remains in place and must not be duplicated. |
| `app.infrastructure.queries` | Useful persistence extraction for repeated or query-specific access; it does not require repositories for every table. |
| `app.integrations.cloudpayments` | Current external boundary for CloudPayments parsing, signature verification, redaction, validation, and normalization. Some processing responsibilities remain transitional. |
| `app.payment_providers` | Current direct-provider contract. Its target meaning is limited to Portal-managed direct-provider flows. |
| `app.domains.identity.router` | Presentation entrypoint with known transitional checkout orchestration responsibilities. |

Existing architecture guards that prevent reverse dependencies and
CloudPayments-specific leakage into provider-neutral modules remain useful.
This step neither replaces them nor claims that the current physical tree fully
implements the target logical layers.

## Known transitional exceptions

- `domains/identity/router.py` resolves plans, legal state, provider account and
  adapter, and manages order/session work inside the checkout HTTP route. It
  also supplies `user.email` as CloudPayments `account_id`. Future work may
  establish an Application boundary; this step does not move the code.
- `integrations/cloudpayments/processing.py` both interprets provider input and
  performs SQLAlchemy queries, direct `Order` and `Payment` mutation, and
  subscription transitions. This is known mixed responsibility and is not
  refactored here.
- `payment_providers` exposes a broad direct-provider contract covering
  checkout, transaction lookup, refunds, and recurring operations. It remains
  the Portal-managed boundary and is not generalized into an external-billing
  adapter.
- `app.state` provides current adapter lookup and may remain as transitional
  wiring. This document does not select a replacement dependency-injection
  architecture.
- CloudPayments `AccountId=email` is current transitional correlation behavior,
  not a target identity pattern.

These exceptions describe the current implementation and do not authorize
their removal in this step.

## Deliberate non-decisions

This architecture decision does not introduce a `BillingSystemAdapter`, a
provider capability hierarchy, an external-customer table, an external-
subscription table, a billing-owner field or enum, a vendor DTO, or a
persistence representation for ownership. It does not select a future vendor,
move packages, change FastAPI dependency injection, remove `app.state`, remove
CloudPayments, require multiple active billing integrations for one contour,
create fake payment-provider accounts for external billing, or define migration
or coexistence rules. Concrete interfaces and schemas must follow an actual
consumer and separately approved implementation scope.
