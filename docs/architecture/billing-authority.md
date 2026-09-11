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
service. The retained `ru` code contains a Portal-managed direct-provider
implementation and persistence source, but normal backend and frontend runtime
does not initialize, register, load, or invoke CloudPayments. The checkout is
temporarily unavailable, generic checkout fails closed when no direct provider
is registered, and the normal application composition does not expose the
CloudPayments callback path. There are no production CloudPayments subscribers
or subscriptions to migrate. The private regional entitlement/access API for
Platform Kernel is still planned under ANY-79.

### TARGET

The sole long-term production target is the external-billing-managed flow. In
that flow, Payment Portal durably persists and commits a local operation or
purchase intent, as applicable, before sending an external command. For a
Portal-initiated commercial purchase or change, Payment Portal creates and owns
the local purchase intent / commercial order after validating the exact
`Plan.id`, user, legal, entrypoint, and commercial context and before sending the
external commercial command. The external billing system owns its external
customer, invoice, payment, and subscription lifecycle; Payment Portal projects
authoritative payment and subscription facts into normalized local records and
applies its entitlement rules. Platform Kernel is the intended consumer of
Payment Portal's local entitlements through the planned private
entitlement/access API.

The commercial `Order` rule is not universal to every external billing
operation. External customer provisioning for an existing Portal `User` may
correlate through that user, a durable local operation, and an external mapping
without inventing an `Order`. An externally initiated or scheduled renewal is
projected or reconciled from authoritative external facts without a prerequisite
Portal `Order`. ANY-411 does not choose a persistence representation for generic
operations or future projection provenance.

The durable ownership invariant is: **a `Subscription` that participates in a
billing lifecycle has exactly one billing owner at a time.** In the long-term
target, that billing lifecycle is owned by one external billing system. The
retained direct-provider source models Payment Portal as its billing owner
only if that flow is explicitly reactivated. A Portal-only access lifecycle,
such as a locally granted free trial without an external billing lifecycle,
remains Portal-owned and does not require an external billing owner. Delegating
such an access-only lifecycle to an external billing system would require a
separate explicit product/integration decision. Billing ownership belongs to
the billing lifecycle, not to the contour. Deployment configuration selects
the concrete target external-billing integration; it does not freely choose
Portal-managed direct-provider billing as a co-equal long-term model.

This target meaning does not assert current persistence readiness. The
implemented `Order` and `Payment` schema still requires direct-provider account
references and other provider-oriented fields and constraints. `Subscription`
allows nullable provider references, but there is no general external-billing
ownership or external-ID mapping representation. As detailed in the
[data-model persistence clarification](payment-portal-data-model.md#persistence-readiness-for-external-billing),
a concrete external-billing integration may require separately approved minimal
schema adaptation, including adaptation of the current direct-provider-shaped
`Order` representation; ANY-411 does not decide it.

### TRANSITIONAL

Under ANY-407, the direct CloudPayments implementation, persistence schema, and
local development/test records remain as retained transitional source for
later evidence-based cleanup. Transitional code describes what remains in the
repository; it does not imply active runtime or production use, must not be
copied as the target external-billing design, and is not removed or refactored
by this decision.
ANY-455 must evaluate active generic persistence separately from retained legacy
CloudPayments persistence and schema, which have no normal-runtime consumer.
Reintroducing Portal-managed direct-provider billing as a future production
model requires a new explicit architecture decision. Because there are no
production CloudPayments subscriptions, this document defines no CloudPayments-
to-external-billing migration or coexistence mechanism.

## Terminology

- **Payment provider:** a direct payment or acquiring provider used by a
  Portal-managed flow. CloudPayments is the retained example. It may be hidden
  behind `PaymentProviderAdapter`.
- **External billing system:** a system authoritative for its external
  customer, invoice, payment, and subscription lifecycle. It is not a
  `PaymentProviderAdapter`.
- **Portal-managed flow:** Payment Portal orchestrates the billing lifecycle
  and uses a direct payment provider for payment operations and facts.
- **External-billing-managed flow:** an external billing system owns the
  external lifecycle; Payment Portal owns any Portal-initiated commercial
  purchase intent / order, sends commands from a committed local operation or
  purchase intent as applicable, and projects authoritative payment and
  subscription facts locally.
- **Billing owner:** the single authority allowed to manage a subscription's
  billing lifecycle when that subscription participates in one. A Portal-only
  access lifecycle is not required to have an external billing owner. This
  document does not choose a persisted representation.
- **Command:** an outbound request or intention. A successful call is not final
  billing-state authority, and the external command is not assumed to be
  idempotent.
- **Authoritative fact:** a normalized fact backed by the owning billing source.
  An authenticated webhook payload is sufficient only when integration policy
  confirms that authenticity plus the integration's semantic completeness and
  currentness guarantees are adequate; otherwise verified server-side
  reconciliation state is required.
- **Normalized local projection:** Payment Portal's local representation of
  externally authoritative billing state. It is not a bidirectional
  synchronization peer.
- **Reconciliation:** recovery or verification of authoritative external state
  through the same local transition path used for webhook facts.
- **Unknown external outcome:** a command outcome that is neither confirmed
  success nor confirmed failure, including a timeout or lost response. It must
  be reconciled before another external command is considered.
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
| Direct CloudPayments orchestration | None in normal runtime; retained source only |
| Local purchase intent / commercial `Order` | Payment Portal |
| External customer lifecycle | Owning external billing system |
| External invoice lifecycle | Owning external billing system |
| External payment lifecycle | Owning external billing system |
| External subscription lifecycle | Owning external billing system |
| Local `Payment` and `Subscription` under external billing | Normalized Payment Portal projections |
| Raw vendor HTTP schemas and status vocabularies | Owning Integration only |

## Billing flows

### Retained Portal-managed direct-provider flow (not active in normal runtime)

```text
Payment Portal
    -> PaymentProviderAdapter
    -> direct payment provider
    -> verified provider fact
    -> local billing transition
    -> Payment Portal entitlement rules
    -> local entitlement
```

The retained CloudPayments source models this Portal-managed lifecycle. It is
not initialized, registered, mounted, or invoked by normal runtime. A future
active direct-provider flow would require a separate explicit architecture and
implementation decision.

### External-billing-managed commercial purchase or change

```text
Payment Portal Application
    -> resolve and validate exact Plan.id, user, legal, entrypoint, and local commercial context
    -> create and persist local purchase intent / commercial order
    -> external billing command
external billing system
    -> authenticated webhook notification
Integration boundary
    -> authenticity verification
    -> validation and normalization
Integration policy
    -> sufficient payload: authoritative normalized fact
    -> insufficient payload: point reconciliation -> verified server-side state -> authoritative normalized fact
    -> shared local transition path
local Payment / Subscription projection correlated with Portal-owned order
    -> Payment Portal entitlement rules
    -> local entitlement
```

The external system owns the external lifecycle. It does not write
entitlements, and Platform Kernel does not query it. `PaymentProviderAdapter`
and `PaymentProviderRegistry` do not represent or register this flow.

Other external billing operations use the same general command invariant:

```text
durable local operation or purchase intent, as applicable
    -> commit
    -> external command
```

They do not require a commercial `Order` unless they are a genuine Portal-
initiated commercial purchase or change.

## Authoritative facts and consistency

An outbound command and its HTTP result report that a request was attempted or
accepted. They do not confirm payment, subscription activation, or entitlement
activation. Payment Portal cannot require every external API command to be
idempotent. Instead, Application must provide retry-safe orchestration and use
provider or vendor idempotency features when they exist. Local intent and
external mappings remain idempotent, and the authoritative transition follows
an authoritative normalized fact backed by the billing owner.

External subscription or service state, confirmed financial or payment state,
and local entitlement are distinct:

```text
external subscription/service state
!= confirmed payment/financial state
!= local entitlement
```

No single vendor field or status, including `active`, `unblocked`, a payment
status, or an account balance, may directly grant access. The Integration
boundary normalizes authoritative external facts without leaking vendor
vocabulary inward. Payment Portal's entitlement policy evaluates the normalized
facts required for the applicable access decision and decides whether local
access is granted, retained, changed, or revoked. This architecture does not
prescribe a fixed set of vendor fields or a concrete future entitlement
algorithm.

Application owns orchestration of the database transaction boundaries around
external commands. External HTTP or other network calls must not execute while
a database transaction is open. When a flow requires local intent or
idempotency state before an external command, that state must be durably
persisted before the call; the external result and any resulting mapping must
be persisted using an appropriate subsequent transaction boundary. This is an
architectural invariant and does not require transaction-handling runtime
changes in this decision.

A timeout or lost response is not confirmed success and not confirmed failure;
it leaves an unknown external outcome. Application must not blindly retry the
command or automatically issue another create. It must reconcile before deciding
whether another external command is safe. Recovery has three architectural
outcomes:

- exactly one unambiguous correlated external object is recovered;
- no unambiguous external match remains unknown for later reconciliation or an
  approved safe recovery policy;
- multiple plausible matches are ambiguous and fail closed for manual review or
  repair, without another automatic create.

The concrete integration owns its lookup fields, timing, eventual-consistency
handling, and matching strategy. This decision does not choose persisted
unknown/ambiguous states or a universal vendor lookup algorithm.

Authenticated webhooks are the primary asynchronous notification mechanism, but
authenticity alone is not semantic authority. After authenticity verification,
validation, and normalization, integration policy determines whether a webhook
payload's completeness and currentness guarantees are sufficient to treat it as
an authoritative normalized fact. Otherwise the webhook
triggers point reconciliation, and verified server-side external state supplies
the authoritative fact. Webhook-derived and reconciliation-derived facts must
normalize into the same future local transition rules so retries and reordered
delivery converge. Reconciliation must not create a parallel state machine.

Every external-billing integration must define a recovery or reconciliation
path for externally authoritative state changes whose notifications are
completely missed. System correctness must not depend solely on webhook
delivery. The concrete integration may later use periodic or incremental scans,
full scans, point recovery, or another vendor-supported mechanism; ANY-411 does
not choose a cadence, cursor, pagination model, scheduler, or storage.

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
cannot be the sole correlation key. The retained CloudPayments use of
`AccountId=email` is transitional legacy source behavior and is not a current
runtime contract. It must not be copied into an external-billing design.

## Trust boundary

All provider and external-billing input follows this boundary:

```text
untrusted input
    -> authentication or authenticity verification
    -> validation and decoding
    -> redaction as needed
    -> normalized typed internal contract
    -> integration policy decides whether the payload is sufficient or point reconciliation is required
    -> authoritative normalized fact
    -> Application
    -> Domain transition
```

Raw provider or vendor payloads and status strings stay at the Integration
edge. Application and Domain logic consume normalized internal contracts, not
vendor DTOs or `dict[str, Any]`. Sensitive raw payloads must not enter logs or
traces. Browser return URLs are informational and never authoritative for paid
access.

Valid webhook receipt follows this architectural sequence:

```text
receive webhook
    -> authenticate and minimally validate
    -> whitelist or redact and durably persist an inbox record
    -> acknowledge the external request according to integration policy
    -> process, retry, or reconcile locally
```

Once a valid notification has been durably received, correctness must not depend
on the external billing system retrying an application-level HTTP failure.
Payment Portal owns subsequent processing, retry, and recovery. Concrete HTTP
acknowledgement codes and external retry policies remain integration-specific.

This generic sequence applies only to an explicitly active integration. The
retained CloudPayments callback source is not mounted in normal runtime.

Durable webhook receipt does not mean persisting the complete raw HTTP request.
Before persistence, the Integration boundary whitelists or redacts the metadata
and normalized fields required for inbox processing, idempotency, correlation,
reconciliation, and processing audit. Raw query-string secrets, unrestricted
headers, authorization or webhook secrets, and unrestricted sensitive payloads
must not be persisted merely for durability. Additional payload persistence
requires a separately approved integration-specific need, security treatment,
and retention rule.

## Logical layer responsibilities

| Layer | Owns | Must not own or depend on |
| --- | --- | --- |
| Presentation | HTTP, webhook, CLI and job entrypoints; request/response contracts; authentication context; boundary decoding and error mapping; invoking Application use cases; generic unexpected-failure conversion | Billing state machines, transaction orchestration, arbitrary ORM mutation, concrete external workflows |
| Application | Use cases, commands and queries, orchestration, transaction boundaries, idempotency and recovery, normalized internal contracts, calls to required persistence and integration capabilities; business failure meaning | FastAPI, routers, HTTP status codes, raw payloads, vendor DTOs or vendor status strings |
| Domain | Business invariants, valid transitions, and entitlement rules independent of transport and vendor protocol; domain failure meaning | FastAPI, HTTP, provider clients, vendor schemas, SQLAlchemy sessions, observability SDKs |
| Persistence / Infrastructure | SQLAlchemy queries, loading and saving, locking, and other persistence mechanics used by Application | Payment lifecycle, entitlement, or billing-ownership decisions |
| Integrations | External protocols and clients, authentication/signature verification, parsing, redaction, vendor DTOs, normalization, and command mapping | A second local state machine, arbitrary local ORM mutation, or entitlement decisions |
| Core | Configuration, session factories, logging, tracing and metrics infrastructure, generic security helpers, time and infrastructure utilities, neutral shared error primitives | Feature-specific error vocabularies, shared business logic, or inward dependencies on billing domains and integrations |
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

## Error contracts and unexpected failures

Application and Domain exceptions are transport-neutral. They may carry stable
internal codes and safe diagnostics where justified, but never FastAPI types,
HTTP status codes, or vendor response semantics. Integrations normalize
provider failures at their boundary and preserve retryability, idempotency, and
unknown or ambiguous-outcome semantics; raw vendor responses and status
vocabularies do not become Application/Domain contracts.

Presentation maps internal failures to HTTP statuses and public response
bodies. Only explicitly allowlisted safe fields are serialized, and changed
public errors use structured `detail.code`. Frontend consumers branch on
`ApiError.status` and structured `detail.code`, not serialized exception text.

An unexpected application failure is converted by the Presentation middleware
to a generic structured HTTP 500 response. While request-ID context is active,
the boundary emits one bounded application-level diagnostic. It may include
the request ID from logging context, HTTP method, matched route template,
exception type, and one application-owned failure-location fingerprint with
only a repository-relative module/file identifier, function name, and line
number. It must not include source text, locals, arguments, exception
messages, raw traceback text, request inputs, provider payloads, secrets, or
card/token/payment values. New monitoring or Sentry is outside this boundary.

## Current package mapping

| Current package or module | Logical role and status |
| --- | --- |
| `app.main` | Composition root that owns normal application lifespan and the empty direct-provider registry; retained CloudPayments source is not wired into normal runtime. |
| `app.models` | Canonical persisted model contract. It remains in place and must not be duplicated. |
| `app.infrastructure.queries` | Useful persistence extraction for repeated or query-specific access; it does not require repositories for every table. |
| `app.integrations.cloudpayments` | Retained external boundary for CloudPayments parsing, signature verification, redaction, validation, and normalization; it is not a normal-runtime callback path. |
| `app.payment_providers` | Retained direct-provider contract. Its meaning is limited to Portal-managed direct-provider flows and it is not part of the long-term target or active normal runtime. |
| `app.domains.identity.router` | Presentation entrypoint with known transitional checkout orchestration responsibilities. |

Existing architecture guards that prevent reverse dependencies and
CloudPayments-specific leakage into provider-neutral modules remain useful.
This step neither replaces them nor claims that the current physical tree fully
implements the target logical layers.

## Known transitional exceptions

- `domains/identity/router.py` retains checkout and provider-neutral commercial
  orchestration responsibilities, but normal runtime fails closed when no
  provider is registered. Retained source supplies `user.email` as the legacy
  CloudPayments `account_id`; future work may establish an Application
  boundary, but this step does not move the code.
- `integrations/cloudpayments/processing.py` both interprets provider input and
  performs SQLAlchemy queries, direct `Order` and `Payment` mutation, and
  subscription transitions. This is known mixed responsibility and is not
  refactored here.
- `payment_providers` exposes a broad direct-provider contract covering
  checkout, transaction lookup, refunds, and recurring operations. It remains
  the Portal-managed boundary and is not generalized into an external-billing
  adapter.
- `app.state` may retain adapter lookup as transitional wiring, but normal
  runtime has no registered direct provider. This document does not select a
  replacement dependency-injection architecture.
- CloudPayments `AccountId=email` is retained transitional source behavior, not
  a current runtime contract or target identity pattern.

These exceptions describe retained implementation source and do not authorize
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
