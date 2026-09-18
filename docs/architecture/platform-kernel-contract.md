# Platform Kernel Contract Boundary

Status: superseded planned contract; retained historical context only
Last verified: 2026-08-18

> **SUPERSEDED CONTRACT NOTICE**
>
> This document preserves the earlier planned Portal-Kernel interaction for
> historical context and is not the target access contract. New development
> follows [ADR 0005](decisions/0005-external-billing-boundary.md) and the
> accepted
> [Portal-Kernel access-contract design](../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md).
> Current repository facts below remain useful until future `ANY-504` work
> implements the accepted contract and performs separately controlled cleanup.

Platform Kernel lives in
[`gushinets/anytoolai-platform`](https://github.com/gushinets/anytoolai-platform).
Payment Portal does not own or modify that code.

Kernel and Payment Portal of the same contour communicate directly after Region
Resolver has given the browser that contour's base URLs. Neither service calls
a foreign contour.

## Ownership

Payment Portal owns purchased access and plan limits. Platform Kernel owns
workflow execution and actual usage. The shared verified identity key is planned
as `tenant_id + region + user_id`, where `region` is the local contour.

Historically, ANY-71 was expected to define and implement the Payment Portal
side of this access contract. That statement is retained as superseded context,
not current execution direction. ADR 0005, the accepted Portal-Kernel
access-contract design, and ANY-504 define the current target and implementation
sequence. The historical contract still records why agents must not invent
cross-service tables, copy raw profiles, or treat email as a runtime identity.

## Planned interaction

1. A trusted identity token yields tenant, contour, and user ID.
2. Platform Kernel asks Payment Portal whether the user has active product,
   containing-bundle, or all-access entitlement.
3. Payment Portal returns purchased limits and validity.
4. Platform Kernel atomically evaluates and records actual usage.

No Platform Kernel implementation is part of this repository transition.
