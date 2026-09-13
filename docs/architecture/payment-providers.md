# Portal-Managed Payment Provider Boundary

Status: authoritative for the retained direct-provider boundary; no provider is active in normal runtime
Last verified: 2026-09-04

This document covers only the **Portal-managed direct payment-provider flow**:
Payment Portal orchestrates billing and calls a payment or acquiring provider
through `PaymentProviderAdapter`. CloudPayments is the retained implementation
source for the `ru` contour. This flow is TRANSITIONAL and deactivated in
normal runtime: no adapter is registered, checkout fails closed, and the
frontend does not load or invoke a provider. It is not a co-equal long-term
production target.

An **external billing system** owns its own external customer, invoice, payment,
and subscription lifecycle. It is a separate authority boundary, is not a
payment-provider adapter, and must not be registered in
`PaymentProviderRegistry`. The normative distinction and target flow are in
[Billing Authority and Consistency](billing-authority.md).

Provider-neutral modules must not import provider integrations and must not
branch on provider-specific literals. When a direct provider is explicitly
enabled, checkout selects its enabled account and calls the registered adapter
contract; normal runtime currently has no registered provider and fails closed.

Adapters own request validation, signature or authenticity checks, payload
redaction, idempotency keys, provider response formatting, and translation
into billing operations.

## Retained implementation source

The CloudPayments adapter, router, persistence schema, and migration source are
retained for later evidence-based cleanup. They are not registered, mounted,
loaded, or invoked by normal backend or frontend runtime. The normal checkout
registry is empty, generic checkout fails closed, and no CloudPayments HTTP
callback path is exposed by normal application composition. Payment Portal is
not yet a production billing service, and there are no production CloudPayments
subscribers or subscriptions.

The retained shared adapter contract covers the historical direct-provider
checkout and lifecycle source. The retained CloudPayments webhook
normalization and response code is not a current billing-fact path. Any future
active integration must define its own authenticated, validated authoritative
fact and local transition contract.

Card data is handled by the contour's provider and is never collected or stored
by this service.

## Retained Subscription and Entitlement Lifecycle

In the retained Portal-managed source, the subscription lifecycle is
provider-neutral domain code. It owns trial creation, paid-period activation,
automatic-renewal attachment, renewal success or failure, normalized provider
subscription state, cancellation requests, refund effects, and expiration.
Domain code accepts only internal identifiers, local operation idempotency keys,
and normalized provider states; it must not import provider integrations or
branch on provider-specific statuses.

Every successful initial or renewal payment must enter the lifecycle with a
persisted internal order, payment, and processed webhook event. The domain
service rechecks those links before creating access. A paid period creates a new
entitlement whose source order is not rewritten by later renewals.

Refund effects are provenance-scoped. A full refund revokes only entitlements
funded by the refunded order/payment and leaves later paid current or future
entitlements intact. A partial refund records lifecycle audit only, unless a
future business rule explicitly defines an access reduction.

Automatic renewal is manual until the provider adapter has successfully created
the provider subscription and the domain service attaches the provider account,
provider subscription reference, and recurring-consent acceptance. Failed
provider setup does not revoke paid access.

The retained CloudPayments recurrent integration source is not an active normal
runtime path. Any future recurrent integration must consume credentials only
inside its own integration boundary and translate authenticated authoritative
facts into provider-neutral lifecycle commands. Tokens must not be persisted,
logged, stored in normalized safe payloads, or exposed to domain code.

## Planned

The sole long-term production target is external-billing-managed and uses the
integration defined by its own implementation ticket, not this adapter
boundary. Deployment configuration selects the concrete external-billing
integration; it does not freely choose Portal-managed direct-provider billing
as a co-equal target. Provider accounts and direct-provider adapter registration
remain relevant only to retained source and a separately approved active
flow. The selection does not make the contour the owner of subscription
billing lifecycles and does not require multiple simultaneously active billing
owners or production integrations. The first-install seed names `paddle` as
`default_payment_provider` for DE and ES; that value is not an accepted Merchant
of Record, active billing model, or EU-provider decision.

Under ANY-407, the CloudPayments implementation remains as retained
transitional code for later evidence-based cleanup. It must not be removed or
refactored here, and no production migration or coexistence mechanism is
required while there are no production CloudPayments subscriptions.
Reintroducing Portal-managed direct-provider billing as a future production
model requires a new explicit architecture decision.

Do not add a future production direct-provider adapter without both a new
explicit architecture decision and a contour-enablement ticket.

Define the smallest shared webhook contract only when the active Linear provider
work or a second provider needs it. Do not treat the current checkout protocol
as an already complete webhook plug-in boundary.

## Retained direct-provider authority

- Payment success comes only from verified provider state, never from a browser
  return URL.
- Duplicate provider deliveries must not duplicate domain mutations.
- A late failure must not downgrade a confirmed paid order or successful
  payment.
- In a separately active direct-provider flow, webhooks hit the local contour
  API directly; Region Resolver is not a proxy. The retained CloudPayments
  callback route is not mounted in normal runtime.

Historical CloudPayments landing work is described by ANY-165, ANY-166, and
ANY-167. Those plans describe retained source and do not make CloudPayments an
active runtime provider, the only possible direct provider, or this adapter
contract the universal billing architecture.
