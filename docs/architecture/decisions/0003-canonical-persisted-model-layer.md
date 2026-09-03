# 0003. Canonical persisted model layer

Status: accepted  
Date: 2026-09-03

## Context

Payment Portal persisted model vocabularies were previously reachable through
domain compatibility modules, while SQLAlchemy fields were typed as text-like
values. This allowed duplicate ownership and made the Python model contract
less explicit. The model layer needs a durable boundary before the next
ANY-407 architecture stage.

## Decision

- `app.models` owns the canonical SQLAlchemy models and confirmed closed
  persisted vocabularies. Model modules import canonical enums directly from
  `app.models.enums`; callers outside the package use explicit `app.models`
  exports.
- Persisted Python enums are `StrEnum` values. `PersistedEnumType` stores their
  `.value` through the existing `TEXT`/`VARCHAR` columns, does not introduce
  PostgreSQL native `ENUM`, and rejects plain raw strings at the final ORM bind
  boundary.
- Provider contract enums remain distinct from local persisted enums. Open,
  provider, configuration, and identifier namespaces remain strings.
- `SubscriptionScopeType` and `SubscriptionRenewalMode` retain their public
  names to avoid incidental OpenAPI changes.
- `region_mismatch_status` remains a string until a complete closed vocabulary
  is defined. Single-value enums are allowed only for confirmed,
  application-owned closed model vocabularies, not merely because one default
  value is currently observed.
- The raw-string binding path was staged for the ANY-326 migration and is not
  part of the final model contract. External/provider strings must be mapped or
  validated into canonical enums before assignment.
- Checkout purchase identity remains the exact `Plan.id`, and `all_access`
  remains an internal access scope, as defined by
  [ADR 0002](0002-plan-based-checkout-identity.md). This decision does not
  change checkout behavior.

## Consequences

- ORM reads return canonical enum members and unknown stored values fail closed.
- Existing physical text storage and historical Alembic revisions remain
  unchanged; no migration is required for this Python typing boundary.
- Billing and legal enum compatibility façades are removed, and the billing ORM
  re-export façade is not a supported import path.
- Future provider or model vocabulary changes must be mapped at the owning
  boundary and must explicitly expand the canonical model contract when needed.

## Status

Accepted as part of ANY-326.

## Superseded decisions

None.
