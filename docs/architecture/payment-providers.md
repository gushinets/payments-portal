# Payment Provider Boundary History

Status: historical boundary reference; direct-provider runtime removed
Last verified: 2026-09-24

> **REMOVED DIRECT-PROVIDER REFERENCE — NOT TARGET ARCHITECTURE**

The Portal-managed direct payment-provider architecture has been physically
removed. The repository no longer contains `PaymentProviderAdapter`,
`PaymentProviderRegistry`, CloudPayments integration/runtime, provider account
models, direct-payment webhook handling, or provider lifecycle commands.

This document preserves the boundary distinction needed to prevent that
architecture from being mistaken for the target.

## Current implementation

There is no active or retained executable direct-provider implementation.
Current API composition exposes identity, password-reset, legal, health and
metrics routes only. The web product snapshot remains presentational and
checkout remains unavailable; it does not invoke a provider or create local
commercial state.

The clean schema contains provider-neutral persistence slots for the approved
external-billing boundary. It contains no Portal-owned `products`, `plans`,
`orders`, `payments`, `refunds`, `subscriptions`, `entitlements`,
`payment_provider_accounts`, or `payment_webhook_events` tables.

## External Billing is a distinct boundary

An external billing system owns its external customer, invoice, payment,
refund, agreement and subscription lifecycle. It is not a payment-provider
adapter and must never be registered in a provider registry. Target ownership
and behavior follow, in precedence order:

1. [ADR 0005](decisions/0005-external-billing-boundary.md);
2. [External Billing Boundary Design](../superpowers/specs/2026-09-15-external-billing-boundary-design.md);
3. [Portal <-> Kernel Access Contract Design](../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md).

Payment Portal owns AnyToolAI identity and legal evidence, the
external-billing anti-corruption/projection/reconciliation/recovery boundary,
and provider-neutral paid-access projection and delivery. Platform Kernel owns
technical product/metric vocabulary, usage, and quota enforcement.

The presence of the target persistence graph does not mean its runtime exists.
Provider-dependent LBX semantics, Widget behavior, authoritative-fact
normalization, reconciliation, access derivation, and launch remain gated by
the applicable `ANY-504` steps and Phase 0 evidence.

## Guardrails

- Do not recreate a generic direct-provider framework for External Billing.
- Do not add External Billing to `PaymentProviderAdapter` or
  `PaymentProviderRegistry`; both abstractions are removed.
- Do not restore CloudPayments source, settings, routes, scripts, schema, or
  environment contracts as compatibility evidence.
- Do not recreate Portal-owned commercial catalog/order/payment or local
  entitlement/trial authority.
- `external_billing_account_id` is opaque configuration scope. There is no
  `external_billing_accounts` ORM entity or table.
- Browser return state, webhook receipt, outbound request success, or payment
  state alone never grants paid access.
- Webhook evidence must be authenticated, bounded and redacted; raw provider
  payloads, secrets, authorization material, and card/payment fields are
  forbidden.

Repository architecture checks enforce the removed runtime/module names,
legacy ORM/table inventory, and forbidden account table without requiring any
deleted implementation file to exist.

## Historical context

Historical CloudPayments delivery is recorded in the superseded ADRs and
execution plans for the work that implemented and later deactivated it. Those
artifacts remain historical evidence only. They do not make CloudPayments an
active provider, a retained implementation, the only possible direct provider,
or a template for External Billing.

Reintroducing Portal-managed direct-provider billing would require a new
explicit architecture decision and a contour-enablement ticket. It is not part
of the approved external-billing target.
