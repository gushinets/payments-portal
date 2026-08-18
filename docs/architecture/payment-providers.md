# Payment Provider Boundary

Status: authoritative for domain rules; CloudPayments is the only implemented adapter
Last verified: 2026-08-18

Billing owns checkout, orders, payments, refunds, and contour-local access
state. A payment provider is an adapter registered for the local contour.

Provider-neutral modules must not import provider integrations and must not
branch on provider-specific literals. Checkout selects enabled rows from
`payment_provider_accounts` and calls the registered checkout adapter contract.

Adapters own request validation, signature or authenticity checks, payload
redaction, idempotency keys, provider response formatting, and translation
into billing operations.

## Implemented

CloudPayments is the registered adapter for the `ru` contour. Browser checkout
uses the CloudPayments widget. Notifications arrive at CloudPayments HTTP
paths on the `ru` API. Those paths are adapter surface, not a billing invariant.

The implemented shared adapter contract currently covers checkout preparation.
CloudPayments webhook normalization and responses remain on the concrete
CloudPayments router and adapter while the provider boundary is under active
development.

Card data is handled by the contour's provider and is never collected or stored
by this service.

## Planned

`eu` and `us` will register their own adapters when those contours are enabled.
The first-install seed names `paddle` as `default_payment_provider` for DE and
ES. That value is not an accepted Merchant of Record or EU-provider decision.

Do not add a second production adapter without an explicit contour-enablement
ticket.

Define the smallest shared webhook contract only when the active Linear provider
work or a second provider needs it. Do not treat the current checkout protocol
as an already complete webhook plug-in boundary.

## Authority

- Payment success comes only from verified provider state, never from a browser
  return URL.
- Duplicate provider deliveries must not duplicate domain mutations.
- A late failure must not downgrade a confirmed paid order or successful
  payment.
- Webhooks hit the local contour API directly. Region Resolver is not a proxy.

Current CloudPayments landing work is described by ANY-165, ANY-166, and
ANY-167. Those plans do not make CloudPayments the only provider the domain
may ever use.
