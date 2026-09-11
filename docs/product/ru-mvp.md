# RU MVP User Journey and Pages

Status: authoritative implemented-product specification
Last verified: 2026-08-18

This is the implemented journey for contour `ru`. Multi-contour architecture is
defined in [contours](../architecture/contours.md). Login/registration contour
confirmation via Region Resolver is planned and is not part of this journey.

## Goal

A user arriving from an AnytoolAI product can understand the relevant product,
create or enter an account, accept the current RU legal documents, and see
that checkout is temporarily unavailable until a billing integration is
selected and implemented.

## Current routes

| Route | Purpose | Status |
|---|---|---|
| `/ru` | RU landing and catalog | Implemented |
| `/ru/products` | Product catalog | Implemented |
| `/ru/auth-checkout` | Product-aware authentication and checkout | Implemented |
| `/ru/forgot-password` | Password reset email request | Implemented |
| `/ru/reset-password` | Password replacement from emailed reset link | Implemented |
| `/ru/account` | Current account and product state | Implemented |
| `/ru/payment-result` | Informational post-payment result | Implemented |
| `/ru/privacy` | Personal-data policy | Implemented |
| `/ru/consent-personal-data` | Personal-data consent | Implemented |
| `/ru/offer` | Public offer | Implemented |
| `/ru/cancellation` | Cancellation and refund terms | Implemented |
| `/ru/cookies` | Cookie policy | Implemented |
| `/ru/security` | Information security policy | Implemented |
| `/en/**` | Locale experiment, not a contour | Out of current scope |

## Primary journey

1. The user opens `/ru/auth-checkout?product=<product-code>` from a product or
   selects a product from the catalog.
2. The page validates the product code and prioritizes that product.
3. An unauthenticated user registers or signs in.
4. A returning user who forgot their password can request an email reset link
   and set a new password from `/ru/reset-password`.
5. Registration requires explicit personal-data and offer confirmation.
6. The checkout surface reports that payment is temporarily unavailable because
   no direct payment provider is registered in normal runtime.
7. The disabled payment action does not request a checkout intent, write payment
   result state, load a provider widget, or start provider work.
8. The payment-result page remains informational and never declares payment
   success solely because the browser returned from a provider.

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
- Payment method marks are shown only for configured/represented methods; no
  payment method is active in the current checkout runtime.

## Page states

The implemented UI uses practical component state rather than a persisted page
state machine. These conceptual states remain useful for tests:

```text
product introduction
authentication
missing legal acceptances
account/product state
checkout unavailable
informational payment-result state
```

Planned trial, subscription, entitlement, bundle, all-access, and Platform
Kernel handoff behavior belongs to ANY-71 or the external Platform Kernel repo.

## Acceptance criteria

- Invalid product codes do not produce checkout state.
- Authentication errors are actionable and do not expose sensitive detail.
- Checkout is explicitly unavailable when no direct payment provider is
  registered, and its disabled action cannot initiate payment preparation.
- A browser return never activates access or substitutes for authoritative
  billing facts.
- No card data is stored or logged.
- Desktop and mobile routes pass browser smoke and accessibility checks.
