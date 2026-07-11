# Product Scope

Status: authoritative
Last verified: 2026-07-11

The current product is the RU Payment Portal MVP for two AnytoolAI products:
Document Summary and Prompt Optimizer.

## Implemented

- RU landing, product catalog, account, checkout, payment-result, and legal pages.
- Password-based demo registration and sessions.
- Versioned RU legal-document metadata and append-only acceptance records.
- Checkout sessions, orders, order items, payment attempts, refunds, and a
  CloudPayments webhook inbox.
- CloudPayments signature checking, payload redaction, and idempotent processing.
- PostgreSQL first-install schema and legal metadata seed.

## Planned elsewhere

- Catalog, plans, subscriptions, entitlements, and the Payment Portal access API
  are tracked by Linear ANY-71 and its subtickets.
- Workflow execution, scenario runtime, artifacts, and usage accounting belong to
  the separate Platform Kernel repository.
- EU/Global routes, providers, and legal content are not part of the RU MVP.

## Product invariants

- A browser return URL never confirms payment or activates access.
- Only verified provider webhooks may advance payment state.
- This service never collects or stores card data.
- Legal drafts are not represented as counsel-approved documents.
- Product and plan identifiers must remain stable across web, payment metadata,
  and future Platform Kernel integration.
