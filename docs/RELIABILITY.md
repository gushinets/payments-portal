# Reliability Requirements

Status: authoritative
Last verified: 2026-09-04

## Critical paths

- API liveness must not depend on PostgreSQL; readiness must.
- Checkout creation and outbound billing commands must be idempotent at
  external boundaries.
- Webhook receipt must be durably stored before normalized processing completes.
- Duplicate authoritative billing facts must not duplicate payment, refund,
  subscription, order, or entitlement changes.
- Stale, duplicate, reordered, or conflicting authoritative billing facts must
  not blindly overwrite newer confirmed state. Explicit transition and
  idempotency rules must reject or ignore them, or trigger reconciliation.
- Valid later lifecycle facts, including refunds, disputes, cancellations, and
  expirations, must remain able to perform their legitimate transitions.
- Verified webhook and future reconciliation facts must feed the same local
  transition path; reconciliation must not become a competing state machine.
- Browser return-page state is informational and never billing authority.
- In the current CloudPayments flow, authoritative facts arrive through verified
  webhooks.

## Agent-verifiable signals

- Every request receives an `X-Request-ID` response header.
- API logs are structured JSON and include request and trace identifiers.
- Metrics expose request latency/errors and billing/legal outcome counters.
- Traces cover HTTP, checkout, legal acceptance, database, and webhook work.
- Critical browser journeys fail on unexpected console errors, failed application
  requests, or error spans.

## Recovery

Development environments must be isolated by worktree and safely disposable.
Production migrations are forward-only after the corrected initial baseline is
frozen. Recovery instructions must never suggest treating the return URL as an
authoritative billing fact or as a substitute for verified webhook processing
or reconciliation.
