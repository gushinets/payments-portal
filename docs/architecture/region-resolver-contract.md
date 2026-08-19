# Region Resolver Contract

Status: architecture-stage external interface; API contract not yet defined
Last verified: 2026-08-18

Region Resolver is a separate service and repository. Payment Portal does not
own or implement it.

The resolver is the only component that knows the registry of **deployed**
contours and the public ISO country-to-contour routing map. For each contour it
stores three public base URLs:

| Role | Consumer |
|---|---|
| Payment portal | Payment Portal web entry of that contour |
| Application portal | Product UI entry of that contour |
| Platform Kernel API | Scenario and product execution API of that contour |

Its job is to resolve the client's ISO country to a suggested deployed contour
and return that URL set so frontends talk to Platform Kernel and Payment Portal
**directly**. Geo is a suggestion; the user confirms the contour.

## Contract maturity

This document fixes ownership and consumer constraints, not an endpoint schema.
Before implementation, the Resolver repository must define versioned request and
response fields, HTTPS URL validation, CORS, cache lifetime, redirect safety,
outage behavior, and handling of client IP data. Do not invent those details in
this repository.

## Non-responsibilities

- No HTML UI.
- No proxying of client, API, or webhook traffic.
- No storage of customer personal data.
- No payment, legal, or identity records.

## Payment Portal consumer rules

This instance may know one non-contour origin: the Region Resolver. The
environment variable name is not defined yet. Add it to runtime configuration
and `.env.example` only when the client is implemented; do not invent a name
in application code before that change.

The Payment Portal backend must not persist other contours' base URLs and must
not call another contour's API.

The Payment Portal web app, at login and registration, may query the resolver
**from the browser** and render:

- the suggested contour from geo;
- the list of currently deployed contours.

The Resolver suggestion comes from its public ISO country-to-contour map. A
local contour validates only its own country membership and does not import the
global map.

Do not hardcode `ru`, `eu`, and `us` as that list. Undeployed contours must not
appear. Server-side calls from the Payment Portal API would see the data-center
IP and must not be used for geo suggestion.

Contour confirmation happens before email and password are submitted to the
local API.

- User confirms **this** contour: local login or registration. The instance
  contour is server-side; the client does not choose a foreign `region` on
  this API.
- User chooses **another** contour: leave this instance through the resolver
  (HTTP redirect to the chosen contour's payment portal). Do not create a
  local user.

`region_mismatch` on entrypoint or order records is a reason to send the
browser back through the resolver, not a reason to write another contour into
this database.

## Application Portal

Application Portal is a peer frontend, not part of this repository. It may
call the same resolver API, render the same deployed-contour list, and then
use the returned Application Portal, Payment Portal, and Platform Kernel API
base URLs directly. Each frontend keeps its own local backend configuration;
the Resolver does not publish Payment Portal FastAPI topology.

## Provider webhooks

Provider notifications target the contour API URL. They never pass through
Region Resolver.

## Isolation reminder

After the resolver response, the browser speaks to one contour. That contour
still does not know the others exist.
