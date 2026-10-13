# Region Resolver Contract

Status: architecture-stage external interface; API contract not yet defined
Last updated: 2026-10-06

Region Resolver is a separate service and repository. AnyToolAI Portal does not
own or implement it.

The resolver is the only component that knows the registry of **deployed**
contours and the public ISO country-to-contour routing map. Its planned
destination topology distinguishes these conceptual boundaries:

| Boundary | Role |
|---|---|
| AnyToolAI Portal | User-facing product discovery and account/auth entry of the selected contour |
| Platform Kernel API | Separate scenario and product execution API/service boundary of that contour |

Its job is to resolve the client's ISO country to a suggested deployed contour
and identify the AnyToolAI Portal entry and Platform Kernel API boundary as
appropriate. Consumers talk to the selected contour's services **directly**;
the resolver is not a proxy. Geo is a suggestion; the user confirms the contour.
This is conceptual ownership/topology only, not a defined URL set or response
schema.

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

## AnyToolAI Portal consumer rules

These are planned consumer constraints; no Resolver client is implemented in
the current Portal.

This instance may know one non-contour origin: the Region Resolver. The
environment variable name is not defined yet. Add it to runtime configuration
and `.env.example` only when the client is implemented; do not invent a name
in application code before that change.

The AnyToolAI Portal backend must not persist other contours' base URLs and must
not call another contour's API.

The AnyToolAI Portal web app, at login and registration, may query the resolver
**from the browser** and render:

- the suggested contour from geo;
- the list of currently deployed contours.

The Resolver suggestion comes from its public ISO country-to-contour map. A
local contour validates only its own country membership and does not import the
global map.

Do not hardcode `ru`, `eu`, and `us` as that list. Undeployed contours must not
appear. Server-side calls from the Portal API would see the data-center
IP and must not be used for geo suggestion.

Contour confirmation happens before email and password are submitted to the
local API.

- User confirms **this** contour: local login or registration. The instance
  contour is server-side; the client does not choose a foreign `region` on
  this API.
- User chooses **another** contour: leave this instance for the chosen
  contour's AnyToolAI Portal entry. Do not create a local user. Navigation
  mechanics remain part of the undefined Resolver API/client contract.

Contour selection belongs to the planned resolver flow and must never write
another contour into this database.

## Portal and Kernel topology

This repository supplies the AnyToolAI Portal user-facing entry, including
public product discovery and the account cabinet. A separate Application
Portal peer frontend is not required. Platform Kernel remains a separately
owned API/service boundary in the same contour. Consumers keep their local
backend configuration; the Resolver does not publish the Portal's internal
FastAPI deployment topology. This change defines no endpoint fields, environment
variable names, URL schema, CORS, cache, or redirect behavior.

## Provider webhooks

Any future External Billing notifications target the contour's API boundary
and never pass through Region Resolver. Current 4F has no provider webhook
runtime or callback endpoint.

## Isolation reminder

After the resolver response, the browser speaks to one contour. That contour
still does not know the others exist.
