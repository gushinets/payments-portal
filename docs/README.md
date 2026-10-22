# Documentation Index

Status: authoritative index
Last verified: 2026-09-25

Start with the smallest document that matches the task.

## Knowledge-source roles

- Architecture decision records capture durable architectural decisions.
- New billing development follows ADR 0005, then the accepted external-billing
  boundary design, then the accepted Portal-Kernel access-contract design.
  The accepted live-source amendment narrowly supersedes their source-catalog
  mirroring/new-sale TTL requirements; paid-access rules are unchanged.
  Retained billing documents cannot override that target authority chain.
- `ARCHITECTURE.md` is the factual current-state map and records clearly
  labelled target or transitional constraints where needed.
- Topic architecture documents provide detailed rules under the ADRs.
- The data-model document defines persistence meaning and local model
  invariants.
- `PRODUCT.md`, `SECURITY.md`, and `RELIABILITY.md` are authoritative for their
  respective dimensions.
- `CODING_CONVENTIONS.md` is the ratchet for new and changed code.
- `AGENTS.md` files provide concise working instructions and navigation; their
  instruction precedence is defined by the root guide.
- Linear issues and execution plans define temporary implementation scope, not
  permanent architecture authority.

## Product and design

- [AnyToolAI Portal product scope](PRODUCT.md)
- [As-built RU Portal 4F handoff and ANY-504 Steps 6–10 ownership](product/ru-mvp.md)
- [Design entry point](DESIGN.md)
- [Bundle 3 reference](design-system/bundle3/README.md)

## Architecture

- [AnyToolAI Portal repository architecture](../ARCHITECTURE.md)

### Target billing architecture (follow in order)

1. [ADR 0005: External billing boundary](architecture/decisions/0005-external-billing-boundary.md)
2. [External Billing Boundary Design](superpowers/specs/2026-09-15-external-billing-boundary-design.md)
3. [Portal ↔ Kernel Access Contract Design](superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md)
4. [Accepted live-source commercial admission amendment](superpowers/specs/2026-10-15-live-source-commercial-admission-design-amendment.md) — owner confirmation on 2026-10-20 in ANY-664 / PR #139; narrow source-read/admission supersession, paid trust unchanged.

### Implementation handoffs and references

- [ANY-709 purchase recovery and Step 8 handoff](engineering/ANY-709-unknown-recovery.md)
  — original accepted snapshot, durable preparation/fencing/UNKNOWN operations,
  guarded Widget eligibility, isolated development journey and human evidence
- [ANY-664 completed implementation plan](exec-plans/completed/ANY-664-implementation-plan.md)
  — all eight Portal steps DONE; implementation-commit CI evidence, retained
  real-enablement gates and handoff to ANY-504 program Step 7
- [Provisional Kernel Capability Manifest v1](contracts/kernel-capability-manifest/v1/README.md)
  — ANY-664 specification-derived schema, independent SIMULATED fixtures,
  standalone development HTTP mock and human verification commands; actual
  Kernel producer conformance remains a future enablement gate
- [ANY-664 Step 8 local conformance handoff](contracts/kernel-capability-manifest/v1/step-8-handoff.md)
  — local checker, deferred real Kernel API verification, separate evidence
  statuses and real producer delivery acceptance; local CI PASS, real API deferred
- [Portal identity, session, and legal baseline](architecture/portal-identity-session-legal-baseline.md)
  — as-built `ANY-504` Step 3 retained-schema contract and exact Step 4 handoff
- [External Billing Persistence Reset](architecture/external-billing-persistence-reset.md)
  — completed reviewed persistence/reset design handoff retained as
  implementation history; the executable runbook is in Deployment

### Current-state and retained historical references

- [Payment provider boundary history](architecture/payment-providers.md) —
  removed direct-provider characterization; not target authority
- [Billing authority](architecture/billing-authority.md) — historical/superseded
  reference only; not current-state or target authority
- [Payment Portal data model](architecture/payment-portal-data-model.md) —
  authoritative current as-built 25-table schema reference
- [Platform Kernel contract boundary](architecture/platform-kernel-contract.md)
  — superseded planned contract; retained historical context

### Other architecture

- [Contours](architecture/contours.md)
- [Region Resolver contract](architecture/region-resolver-contract.md)
- [Deployment](architecture/deployment.md)
- [Architecture decisions](architecture/decisions/README.md)

## Engineering

- [Development](engineering/DEVELOPMENT.md)
- [Testing](engineering/TESTING.md)
- [ANY-709 SIMULATED preparation and UNKNOWN recovery](engineering/ANY-709-unknown-recovery.md)
- [Agent workflow](engineering/AGENT_WORKFLOW.md)
- [Coding conventions](engineering/CODING_CONVENTIONS.md)
- [Reliability](RELIABILITY.md)
- [Security](SECURITY.md)
- [Quality score](QUALITY_SCORE.md)
- [Execution plans](exec-plans/README.md)

## Legal

- [Legal source workflow](legal/README.md)
- Current RU legal source version: `2026-07-11`.

## Generated references

- [Database schema](generated/db-schema.md)
- [OpenAPI snapshot](generated/openapi.json)
