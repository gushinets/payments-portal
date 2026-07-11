# RU MVP User Journey and Pages

Status: authoritative implemented-product specification
Last verified: 2026-07-11

## Goal

A user arriving from an AnytoolAI product can understand the relevant product,
create or enter an account, accept the current RU legal documents, initiate a
CloudPayments checkout, and see provider-confirmed payment state.

## Current routes

| Route | Purpose | Status |
|---|---|---|
| `/ru` | RU landing and catalog | Implemented |
| `/ru/products` | Product catalog | Implemented |
| `/ru/auth-checkout` | Product-aware authentication and checkout | Implemented |
| `/ru/account` | Current account and product state | Implemented |
| `/ru/payment-result` | Informational post-payment result | Implemented |
| `/ru/privacy` | Personal-data policy | Implemented |
| `/ru/consent-personal-data` | Personal-data consent | Implemented |
| `/ru/offer` | Public offer | Implemented |
| `/ru/cancellation` | Cancellation and refund terms | Implemented |
| `/ru/cookies` | Cookie policy | Implemented |
| `/ru/security` | Information security policy | Implemented |
| `/en/**` | Global experience | Out of current scope |

## Primary journey

1. The user opens `/ru/auth-checkout?product=<product-code>` from a product or
   selects a product from the catalog.
2. The page validates the product code and prioritizes that product.
3. An unauthenticated user registers or signs in.
4. Registration requires explicit personal-data and offer confirmation.
5. Checkout asks the API for a checkout intent.
6. If an active required legal version has not been accepted, the API returns
   each missing document and its acceptance text hash.
7. The user explicitly accepts every required version; the API writes append-only
   acceptance evidence.
8. The checkout intent creates pending commercial state.
9. In configured mode, the CloudPayments widget handles payment. Demo mode still
   produces only pending/informational browser state.
10. The payment-result page polls API state. It never declares payment success
    solely because the browser returned from the provider.
11. Verified webhook delivery updates order and payment state idempotently.

## Returning user

An authenticated user with current required acceptances skips repeated legal
steps. A new active legal version requires a new explicit acceptance. Existing
paid or pending state is displayed from the API rather than inferred locally.

## Product catalog

The current web snapshot contains:

- `document-summary`
- `prompt-optimizer`

The frontend catalog remains a temporary snapshot until ANY-71 introduces the
database catalog and plan model.

## Legal and compliance UX

- Legal links and operator details appear in the site footer.
- Forms that collect account data link to relevant legal documents.
- Required acceptance checkboxes are never preselected.
- Automatic-renewal consent is separate from general legal acceptance.
- The cookie banner stores only the user's local choice in the current MVP.
- Payment method marks are shown only for configured/represented methods.

## Page states

The implemented UI uses practical component state rather than a persisted page
state machine. These conceptual states remain useful for tests:

```text
product introduction
authentication
missing legal acceptances
account/product state
checkout preparation
pending provider confirmation
provider-confirmed result
```

Planned trial, subscription, entitlement, bundle, all-access, and Platform
Kernel handoff behavior belongs to ANY-71 or the external Platform Kernel repo.

## Acceptance criteria

- Invalid product codes do not produce checkout state.
- Authentication errors are actionable and do not expose sensitive detail.
- Checkout is blocked until every current required legal version is accepted.
- A changed active document version requires a new acceptance.
- Duplicate or late webhooks preserve valid terminal state.
- No card data is stored or logged.
- Desktop and mobile routes pass browser smoke and accessibility checks.
