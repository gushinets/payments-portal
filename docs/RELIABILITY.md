# Reliability Requirements

Status: authoritative
Last verified: 2026-07-11

## Critical paths

- API liveness must not depend on PostgreSQL; readiness must.
- Checkout creation must be idempotent at provider-facing boundaries.
- Webhook receipt must be stored before normalized processing completes.
- Duplicate provider events must not duplicate payment, refund, or order changes.
- A late failure must not downgrade a confirmed paid order.
- Return-page state is informational and never payment authority.

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
frozen. Recovery instructions must never suggest treating the return URL as a
substitute for provider reconciliation.
