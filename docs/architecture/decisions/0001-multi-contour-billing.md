# 0001. Multi-contour billing platform

Status: accepted
Date: 2026-08-18

Amendment: [ADR 0004](0004-billing-authority-and-consistency.md) supersedes
only the assumption that every contour registers a payment-provider adapter.
The contour-isolation and Region Resolver decisions in this ADR remain in
force.

## Context

The implemented product is the `ru` contour with CloudPayments. Billing, provider
integrations, and identity now need an architecture that can serve additional
compliance zones without turning CloudPayments or `ru` into domain invariants.

A contour is the compliance zone where this Payment Portal is deployed. One
contour serves every country assigned to it. Production instances must not share
customers, legal records, or payment data with another contour.

Frontends need a way to reach the correct contour without this repository owning
a global URL map.

## Decision

- This repository is a multi-contour billing platform. The first enabled contour
  is `ru`. Planned contours are `eu` and `us`.
- `regions.code` is the contour code. `country_region_rules` lists countries that
  belong to the local contour. Locale and URL prefixes are not contours.
- Target production architecture is one contour per instance. The instance does
  not know that other contours exist in data, configuration, or server-side
  calls.
- Region Resolver is a separate UI-less service. It owns the registry of
  deployed contours, the public ISO country-to-contour map, and three public
  base URLs for each contour: Payment Portal, Application Portal, and Platform
  Kernel API. This repository does not implement it.
- Payment Portal and Application Portal frontends may query the resolver and
  render the deployed-contour list at login and registration. Switching contour
  leaves this instance through the resolver. Provider webhooks never go through
  the resolver.
- Billing domain code stays provider-neutral. Each contour registers its own
  payment-provider adapter. CloudPayments is the current `ru` adapter, not the
  system boundary.

## Consequences

- Architecture and agent rules describe implemented `ru` behavior separately
  from target multi-contour invariants.
- Seed rows for `eu` in the shared first-install migration are not a production
  `ru` instance serving Europe.
- Current client-supplied `region` fields and the shared `ru`/`eu` seed do not
  enforce the target isolation invariant. Server-side instance-contour
  enforcement is required before enabling another contour.
- Merchant of Record, legal trees, and providers for `eu` and `us` remain
  product decisions. They are not implied by this ADR.
- The Payment Portal may store only one non-contour service origin: the Region
  Resolver. Other contours' base URLs must not be persisted here.
