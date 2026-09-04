# Portal-Managed Payment Provider Boundary

Status: authoritative for the direct-provider boundary; CloudPayments is the only implemented adapter
Last verified: 2026-09-04

This document covers only the **Portal-managed direct payment-provider flow**:
Payment Portal orchestrates billing and calls a payment or acquiring provider
through `PaymentProviderAdapter`. CloudPayments is the adapter in the current
`ru` implementation.

An **external billing system** owns its own external customer, invoice, payment,
and subscription lifecycle. It is a separate authority boundary, is not a
payment-provider adapter, and must not be registered in
`PaymentProviderRegistry`. The normative distinction and target flow are in
[Billing Authority and Consistency](billing-authority.md).

Provider-neutral modules must not import provider integrations and must not
branch on provider-specific literals. Checkout selects enabled rows from
`payment_provider_accounts` and calls the registered checkout adapter contract.

Adapters own request validation, signature or authenticity checks, payload
redaction, idempotency keys, provider response formatting, and translation
into billing operations.

## Implemented

CloudPayments is registered in the current `ru` implementation. Browser
checkout uses the CloudPayments widget. Notifications arrive at CloudPayments
HTTP paths on the `ru` API. Those paths are adapter surface, not a billing
invariant. Payment Portal is not yet a production billing service, and there
are no production CloudPayments subscribers or subscriptions.

The implemented shared adapter contract currently covers checkout preparation.
CloudPayments webhook normalization and responses remain on the concrete
CloudPayments router and adapter while the provider boundary is under active
development. Verified initial payment and refund outcomes enter the
provider-neutral subscription lifecycle through internal order, payment, refund,
and webhook identifiers.

Card data is handled by the contour's provider and is never collected or stored
by this service.

## Current Subscription and Entitlement Lifecycle

In the current Portal-managed flow, the subscription lifecycle is
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

ANY-168 owns the CloudPayments recurrent integration boundary after ANY-78:
consume the verified initial token only inside the adapter boundary, call the
provider recurrent APIs, attach the opaque provider reference on success, and
translate later provider renewal notifications or API results into the
provider-neutral lifecycle commands. The token must not be persisted, logged,
stored in normalized safe payloads, or exposed to domain code.

## Planned

Contour enablement or deployment configuration may select one concrete active
billing model and integration for the deployed product. If the selected model
is Portal-managed, it may configure provider accounts and register a direct-
provider adapter. If the selected model is external-billing-managed, it uses
the integration defined by its own implementation ticket, not this adapter
boundary. The selection does not make the contour the owner of subscription
billing lifecycles and does not require multiple simultaneously active billing
owners or production integrations. The first-install seed names `paddle` as
`default_payment_provider` for DE and ES; that value is not an accepted
Merchant of Record, active billing model, or EU-provider decision.

Under ANY-407, the CloudPayments implementation remains as transitional code
until separately approved work determines whether it is still needed. It must
not be removed or refactored here, and no production migration or coexistence
mechanism is required while there are no production CloudPayments
subscriptions.

Do not add a second production adapter without an explicit contour-enablement
ticket.

Define the smallest shared webhook contract only when the active Linear provider
work or a second provider needs it. Do not treat the current checkout protocol
as an already complete webhook plug-in boundary.

## Direct-provider authority

- Payment success comes only from verified provider state, never from a browser
  return URL.
- Duplicate provider deliveries must not duplicate domain mutations.
- A late failure must not downgrade a confirmed paid order or successful
  payment.
- Webhooks hit the local contour API directly. Region Resolver is not a proxy.

Current CloudPayments landing work is described by ANY-165, ANY-166, and
ANY-167. Those plans describe the current Portal-managed implementation; they
do not make CloudPayments the only possible direct provider or make this
adapter contract the universal billing architecture.
