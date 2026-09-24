# Contours

Status: authoritative target architecture; implemented product remains `ru`
Last verified: 2026-09-24

A **contour** is the compliance zone in which this Payment Portal is deployed.
It may serve any number of countries assigned to that zone. It is not a locale,
not a URL prefix, and not a payment provider.

Persisted contour identity is `regions.code`. Country membership is
`country_region_rules`. Data residency is `regions.residency_zone`.

Region Resolver owns the public ISO country-to-deployed-contour map used before
the browser enters a data plane. Each contour keeps only its local country rules
for server-side validation and market configuration.

The API's implemented data-plane authority is the required deployment pair
`INSTANCE_TENANT_ID` / `INSTANCE_REGION`. Registration, login, password reset,
required-document discovery, authenticated sessions, and legal writes derive
scope from that pair or from the authenticated canonical user. A client cannot
select another contour by supplying request or query fields.

Normative decision: [ADR 0001](decisions/0001-multi-contour-billing.md).
Region routing: [Region Resolver contract](region-resolver-contract.md).
Target billing ownership authority: [ADR 0005](decisions/0005-external-billing-boundary.md),
the accepted [External Billing Boundary Design](../superpowers/specs/2026-09-15-external-billing-boundary-design.md),
and the accepted [Portal ↔ Kernel Access Contract Design](../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md),
in that order.

## Planned contours

| Contour | Compliance zone | Countries in product terms | Status |
|---|---|---|---|
| `ru` | Russian | Countries assigned to `ru` (currently `RU`) | Implemented product |
| `eu` | European | European countries assigned to `eu` | Planned; not in schema |
| `us` | North American | United States, Canada, and any later assigned country | Planned; not in schema |

Exact ISO country lists for `eu` and `us` are product data, not code defaults.
A country belongs to at most one contour.

## Isolation

A production instance:

- enables exactly one contour;
- requires one explicit `INSTANCE_TENANT_ID` and `INSTANCE_REGION` pair;
- stores only that contour's identity, session, legal, and provider-neutral
  target persistence records;
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
| Canonical Portal user | `users.id`, scoped by explicit `tenant_id` and `region` |
| Seller / operator | `legal_entities` keyed by contour |
| Legal pack | `document_versions` keyed by contour |
| External billing account scope | Opaque deployment configuration referenced by `external_billing_account_id`; no Portal account table |
| Customer-facing locale | `regions.default_locale` and web routes; not the contour key |

The clean first-install migration currently supports exactly the configured
`anytoolai` / `ru` scope and its RU country rule. Any different configured
tenant/region pair fails instead of silently creating RU data. The configured
API scope is server-authoritative and a `ru` instance cannot create or
authenticate a foreign-contour user through the public identity/legal API.

`us` is absent from the schema until an explicit enablement ticket adds it.

## Current vs planned product surface

Implemented today: `ru` web routes, `docs/legal/ru`, identity/legal runtime,
and the clean provider-neutral persistence baseline. Direct-provider runtime
has been removed and target billing tables have no producer behavior. See
[RU MVP journey](../product/ru-mvp.md).

Planned, not implemented:

- login/registration contour confirmation via Region Resolver;
- `eu` and `us` legal trees, operators, catalogs, and explicitly selected
  billing integrations;
- per-contour data planes and residency.

Do not add `/en` or other locales as a substitute for a contour. Locale is
orthogonal. `/en/**` remains out of the implemented `ru` journey.

## Enablement checklist

Enabling a contour requires a dedicated ticket. Minimum set:

1. Explicit server-side `INSTANCE_TENANT_ID` / `INSTANCE_REGION`
   configuration, a contour-local clean bootstrap, and no foreign client scope
   authority.
2. `regions` row, residency zone, and local `country_region_rules` for every
   assigned country.
3. A defined customer-country source for selecting country-specific provider
   and market configuration inside a multi-country contour.
4. Legal entity and one active legal pack per contour under the current model,
   with contour-aware source generation and web rendering. Add country,
   document-set, or locale variants only after ANY-71 defines the required
   dimension. The current pipeline and renderer are hardcoded to
   `docs/legal/ru`.
5. One concrete external-billing integration selected for the deployed product,
   as required by the sole long-term production target. Its owning
   implementation ticket must define the integration; contour enablement does
   not invent it here. Direct-provider runtime is removed; reintroduction would
   require a separate explicit architecture decision.
6. External catalog projection and Platform capability mapping configured under
   the accepted billing designs; the Portal owns no catalog/plan authority.
7. Contour locale and routes in the web application.
8. Isolated data plane and billing-notification URLs on that plane.
9. Region Resolver registry entry with the public ISO country mapping and the
   Payment Portal, Application Portal, and Platform Kernel API base URLs. At
   deployment, the Resolver country mappings for a contour must equal that
   contour's enabled local country rules.

## Billing ownership and integration

The current `ru` implementation has no direct-provider runtime and no
Portal-owned checkout/order/payment/subscription/entitlement authority. The
clean target persistence baseline is contour-local but has no producer runtime.
Payment Portal is not yet a production billing service.

The long-term production target requires contour enablement/deployment
configuration to select one concrete external-billing integration. Target
commercial ownership, provider-neutral paid-access projection, and the Portal
<-> Kernel contract follow the ADR 0005 authority chain above.

For historical/superseded context only, see
[payment providers](payment-providers.md) and
[Billing Authority and Consistency](billing-authority.md). Neither describes
current state or target external-billing authority.
