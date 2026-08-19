# Platform Kernel Contract Boundary

Status: planned interface context; not implemented by ANY-108
Last verified: 2026-08-18

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

ANY-71 will define and implement the Payment Portal side of the access contract.
Until then, this document prevents agents from inventing cross-service tables,
copying raw profiles, or treating email as a runtime identity.

## Planned interaction

1. A trusted identity token yields tenant, contour, and user ID.
2. Platform Kernel asks Payment Portal whether the user has active product,
   containing-bundle, or all-access entitlement.
3. Payment Portal returns purchased limits and validity.
4. Platform Kernel atomically evaluates and records actual usage.

No Platform Kernel implementation is part of this repository transition.
