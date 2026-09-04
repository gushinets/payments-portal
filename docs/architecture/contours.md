# Contours

Status: authoritative target architecture; implemented product remains `ru`
Last verified: 2026-09-04

A **contour** is the compliance zone in which this Payment Portal is deployed.
It may serve any number of countries assigned to that zone. It is not a locale,
not a URL prefix, and not a payment provider.

Persisted contour identity is `regions.code`. Country membership is
`country_region_rules`. Data residency is `regions.residency_zone`.

Region Resolver owns the public ISO country-to-deployed-contour map used before
the browser enters a data plane. Each contour keeps only its local country rules
for server-side validation and market configuration.

Normative decision: [ADR 0001](decisions/0001-multi-contour-billing.md).
Region routing: [Region Resolver contract](region-resolver-contract.md).
Billing ownership: [ADR 0004](decisions/0004-billing-authority-and-consistency.md)
and [Billing Authority and Consistency](billing-authority.md).

## Planned contours

| Contour | Compliance zone | Countries in product terms | Status |
|---|---|---|---|
| `ru` | Russian | Countries assigned to `ru` (currently `RU`) | Implemented product |
| `eu` | European | European countries assigned to `eu` | Planned; `eu` exists in schema seed |
| `us` | North American | United States, Canada, and any later assigned country | Planned; not in schema |

Exact ISO country lists for `eu` and `us` are product data, not code defaults.
A country belongs to at most one contour.

## Isolation

A production instance:

- enables exactly one contour;
- stores only that contour's users, legal versions, orders, and provider accounts;
- evaluates country membership only against local `country_region_rules`;
- does not store other contours' base URLs, users, or legal entities;
- does not call another contour's API.

The identity key remains `tenant_id + region + user_id`. On a production
instance `region` is always the local contour. The same email in `ru` and `eu`
is two accounts on two data planes.

No user or payment data may be silently replicated between contour data planes.

## Schema mapping

| Concept | Persistence |
|---|---|
| Contour | `regions.code` |
| Residency / data plane | `regions.residency_zone` |
| Countries in this contour | `country_region_rules.country_code` |
| Seller / operator | `legal_entities` keyed by contour |
| Legal pack | `document_versions` keyed by contour |
| Direct payment provider account | `payment_provider_accounts` keyed by contour for the Portal-managed flow |
| Customer-facing locale | `regions.default_locale` and web routes; not the contour key |

The first-install migration currently inserts both `ru` and `eu` plus DE/ES
country rules into one database. That is **not** the production invariant. A
`ru` instance must not serve `eu`. Treat extra seed rows as schema vocabulary
and follow-up debt, not as an enabled European market.

The current auth API also accepts a client-supplied `region`, defaulting to
`ru`. Therefore current code does not yet enforce one contour per instance.
This is implementation debt, not permission to deploy a shared data plane.

`us` is absent from the schema until an explicit enablement ticket adds it.

## Current vs planned product surface

Implemented today: `ru` web routes, `docs/legal/ru`, CloudPayments, and `ru`
defaults in the web and API. See [RU MVP journey](../product/ru-mvp.md).

Planned, not implemented:

- instance contour taken from deployment configuration rather than a `ru`
  literal;
- login/registration contour confirmation via Region Resolver;
- `eu` and `us` legal trees, operators, catalogs, and explicitly selected
  billing integrations/owners;
- per-contour data planes and residency.

Do not add `/en` or other locales as a substitute for a contour. Locale is
orthogonal. `/en/**` remains out of the implemented `ru` journey.

## Enablement checklist

Enabling a contour requires a dedicated ticket. Minimum set:

1. Server-side instance-contour configuration that rejects foreign client
   `region` values and prevents foreign seed data.
2. `regions` row, residency zone, and local `country_region_rules` for every
   assigned country.
3. A defined customer-country source for selecting country-specific provider
   and market configuration inside a multi-country contour.
4. Legal entity and one active legal pack per contour under the current model,
   with contour-aware source generation and web rendering. Add country,
   document-set, or locale variants only after ANY-71 defines the required
   dimension. The current pipeline and renderer are hardcoded to
   `docs/legal/ru`.
5. An explicitly configured billing owner and integration. For a
   Portal-managed direct-provider flow, this includes enabled
   `payment_provider_accounts`, adapter registration, credentials, and
   provider-specific webhook routes. For an external-billing-managed flow, the
   owning implementation ticket must define the integration; contour
   enablement does not invent it here.
6. Catalog and plans in the contour's supported currencies.
7. Contour locale and routes in the web application.
8. Isolated data plane and provider webhook URLs on that plane.
9. Region Resolver registry entry with the public ISO country mapping and the
   Payment Portal, Application Portal, and Platform Kernel API base URLs. At
   deployment, the Resolver country mappings for a contour must equal that
   contour's enabled local country rules.

## Billing ownership and integration

Checkout, orders, payments, and refunds belong to billing and are contour-local.
The current `ru` contour uses the Portal-managed direct CloudPayments flow: its
payment provider is selected from local `payment_provider_accounts`, and
provider-specific verification stays in the adapter. Other contours do not
inherently require a `PaymentProviderAdapter`; each must explicitly configure
either a Portal-managed direct-provider integration or an
external-billing-managed integration. In the latter model, the external system
owns its external lifecycle while this contour stores only normalized local
projections and remains authoritative for local entitlements. See
[payment providers](payment-providers.md) and
[billing authority](billing-authority.md).
