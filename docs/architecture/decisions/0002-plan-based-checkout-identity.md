# 0002. Plan-based checkout identity

Status: accepted
Date: 2026-09-02

## Context

The backend catalog returns persisted Product data together with the exact
currently sellable Plan for each product. The frontend is product-oriented for
navigation and presentation, but checkout must identify the commercial offer
that the customer selected. A Product can have multiple versioned Plans, and
two Plan versions can retain the same human-readable code while having
different persisted identities.

The previous checkout contract repeated commercial identity through a
`product` field and `plan_code`. Those values were overloaded across Product,
Bundle, Plan, and the synthetic `all-access` sentinel. Entrypoint provenance
was also at risk of being treated as a purchase selector. This made the
checkout identity ambiguous and could select a different Plan version from
the one shown in the catalog.

## Decision

- `Plan.id` is the exact commercial purchase identity. The checkout client
  submits the persisted `plan_id` UUID received in the selected catalog
  Product's Plan data.
- The checkout request's commercial identity is exactly:

  ```python
  plan_id: uuid.UUID
  ```

  The request does not use `Product.code`, `Bundle.code`, `Plan.code`, or
  `scope_type` as a purchase selector.
- `Product` is the catalog and access entity. `Product.code` remains useful
  for product navigation and catalog presentation, but it is not purchase
  authority. Current product navigation may continue to use
  `?product=<Product.code>` for UI selection.
- `product` and `plan_code` are removed from `CheckoutIntentRequest` after
  migration. No compatibility aliases or alternate parsing paths are
  retained.
- The backend resolves the exact Plan by ID and derives
  `SubscriptionScopeType` from the persisted `Plan.scope_type`. The client
  does not submit scope to select a purchase.
- `all_access` remains the canonical persisted access-scope value. It may
  appear in backend-derived subscription, entitlement, and other access/read
  models, but the checkout client never submits it as purchase authority.
- The synthetic string `all-access` is removed from the checkout runtime
  contract. It is not a valid purchase identifier, Plan alias, or scope alias.
  No fake Product or Bundle row is created for all-access scope.
- Entrypoint fields are provenance only. `entrypoint_type` and
  `entrypoint_value` record where checkout started and never participate in
  Plan resolution. An `EntrypointSession` is not the purchased object.
- Recurring consent binds to the exact `plan_id` together with the existing
  user, contour, legal-document, acceptance-kind/time, and entrypoint
  dimensions. A consent for one Plan ID does not authorize another Plan ID,
  including when both Plans have the same `Plan.code`. Selecting the new Plan
  provides a fresh append-only consent path.
- Provider merchant and invoice identifiers are opaque. They contain no
  Product, Bundle, Plan, scope, or entrypoint strings.
- Checkout responses are purchase- and Plan-oriented. They preserve the
  provider-neutral payment envelope:

  ```text
  checkout.amount
  checkout.currency
  checkout.action
  ```

- The final ANY-370 ownership semantics remain independent from purchase
  selection. Direct Product, containing Bundle, and `all_access` entitlements
  may block buying a selected Product, but none of those access scopes becomes
  a checkout identifier.
- ANY-323 must preserve this contract after rebase: exact `plan_id` purchase
  authority, backend-derived scope, explicit entrypoint provenance,
  exact-Plan recurring consent, opaque invoice IDs, no `product` plus
  `plan_code` request identity, no synthetic `all-access` alias, and no
  branch-local duplicate scope enum.

## Consequences

- Checkout can select the exact versioned commercial Plan displayed by the
  backend catalog instead of resolving an overloaded string.
- Product, Bundle, and access-scope relationships are backend-derived facts
  of the resolved Plan and can be validated before an order is created.
- Removing the legacy selector fields is an intentional contract migration;
  old checkout payloads fail rather than silently selecting a different offer.
- The current product navigation URL remains useful without becoming payment
  authority.
- Runtime checkout, legal, and lifecycle code must be migrated to this ADR in
  the follow-up implementation steps. This ADR records the accepted boundary;
  it does not itself change application code.
