# RU MVP User Journey and Pages

Status: authoritative implemented-product specification
Last verified: 2026-09-24

This is the implemented journey for contour `ru`. Multi-contour architecture is
defined in [contours](../architecture/contours.md). Login/registration contour
confirmation through Region Resolver is planned and is not part of this
journey.

## Goal

A user can understand the two currently presented AnytoolAI products, create or
enter an account, recover a password, accept current RU legal documents, and
see that checkout and billing/account details remain unavailable until the
approved external-billing runtime is implemented.

## Current routes

| Route | Purpose | Status |
| --- | --- | --- |
| `/ru` | RU landing and product snapshot | Implemented |
| `/ru/products` | Presentational product snapshot | Implemented |
| `/ru/auth-checkout` | Authentication and unavailable-checkout shell | Implemented |
| `/ru/forgot-password` | Password-reset email request | Implemented |
| `/ru/reset-password` | Password replacement from emailed reset link | Implemented |
| `/ru/account` | Authenticated account shell; billing details unavailable | Implemented |
| `/ru/payment-result` | Informational unavailable-payment state | Implemented |
| `/ru/privacy` | Personal-data policy | Implemented |
| `/ru/consent-personal-data` | Personal-data consent | Implemented |
| `/ru/offer` | Public offer | Implemented |
| `/ru/cancellation` | Cancellation and refund terms | Implemented |
| `/ru/cookies` | Cookie policy | Implemented |
| `/ru/security` | Information security policy | Implemented |
| `/en/**` | Locale experiment, not a contour | Out of current scope |

## Primary journey

1. The user opens `/ru/auth-checkout` from a product presentation or navigation.
2. An unauthenticated user registers or signs in.
3. A returning user can request a password-reset email and set a new password.
4. Registration requires explicit personal-data and offer confirmation.
5. The checkout surface reports that purchases and billing are temporarily
   unavailable while the new billing system is being implemented.
6. The unavailable action does not call a catalog, checkout-intent,
   payment-status, subscription, Widget, callback, or provider API and does not
   populate any target billing table.
7. The payment-result route remains informational and never declares success
   from browser state.

## Returning user

An authenticated user with current required acceptances skips repeated legal
steps. A new active legal version requires a new explicit acceptance. The
account page shows identity/session information and an explicit unavailable
billing state; it does not infer paid, pending, subscription, entitlement, or
quota state locally.

## Product presentation

The web snapshot contains:

- `document-summary`;
- `prompt-optimizer`.

This is static presentation content, not a Portal database catalog or
commercial offer authority. Target technical product and metric identity comes
from Platform Kernel capability projection; target commercial offers come from
External Billing. Their import/publication runtimes are not implemented.

## Legal and compliance UX

- Legal links and operator details appear in the site footer.
- Forms collecting account data link to relevant legal documents.
- Required acceptance checkboxes are never preselected.
- The cookie banner stores only the user's local choice in the current MVP.
- Payment-method marks are shown only when configured; the current configured
  list is empty.
- Legal pages remain drafts and are not presented as counsel-approved.

## Page states

The implemented UI uses component state rather than a persisted page state
machine:

```text
product introduction
authentication
missing legal acceptances
authenticated account
checkout unavailable
informational payment-result state
```

## Acceptance criteria

- Authentication errors are actionable and do not expose sensitive detail.
- Checkout and account billing details are explicitly unavailable and cannot
  initiate payment preparation or billing persistence.
- A browser return never activates access or substitutes for authoritative
  billing facts.
- No card data, provider payload, authorization material, or billing secret is
  collected or logged.
- Desktop and mobile routes pass browser smoke and accessibility checks.
