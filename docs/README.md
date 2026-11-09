# Documentation Index

Status: authoritative index
Last updated: 2026-11-10

Start with the smallest document that matches the task.

## Knowledge-source roles

- Architecture decision records capture durable architectural decisions.
- New billing development follows ADR 0005, then the accepted external-billing
  boundary design, then the accepted Portal-Kernel access-contract design.
  The accepted live-source amendment narrowly supersedes their source-catalog
  mirroring/new-sale TTL requirements; paid-access rules are unchanged.
  Apply the accepted dated owner decisions recorded in or explicitly linked by
  ADR 0005 before the affected baseline rules, within each decision's stated
  scope. These include C1-C4, point-resource identity, payment-Widget admission,
  UNKNOWN recovery and lifecycle metadata. Implementation results are evidence,
  not additional contract exceptions.
  Retained billing documents cannot override that target authority chain.
- `ARCHITECTURE.md` is the factual current-state map and records clearly
  labelled target or transitional constraints where needed.
- Topic architecture documents provide detailed rules under the ADRs.
- The data-model document defines persistence meaning and local model
  invariants.
- `PRODUCT.md`, `SECURITY.md`, and `RELIABILITY.md` are authoritative for their
  respective dimensions.
- `CODING_CONVENTIONS.md` is the ratchet for new and changed code.
  Its internal-contract rules own concrete consumed structures, finite
  vocabularies, boundary validation, compatibility and bounded exceptions;
  architecture and data-model references distinguish existing debt from policy.
- `AGENTS.md` files provide concise working instructions and navigation; their
  instruction precedence is defined by the root guide.
- Ordinary Linear issue text and execution plans define implementation scope.
  Only accepted dated owner decisions recorded in or explicitly linked by
  ADR 0005 supply billing contract exceptions; reports and checkboxes do not.

## Product and design

- [AnyToolAI Portal product scope](PRODUCT.md)
- [As-built RU Portal 4F handoff and ANY-504 Steps 6–10 ownership](product/ru-mvp.md)
- [Design entry point](DESIGN.md)
- [Bundle 3 reference](design-system/bundle3/README.md)

## Architecture

- [AnyToolAI Portal repository architecture](../ARCHITECTURE.md)
- [Platform Kernel integration map](integrations/platform-kernel.md) — current/target interfaces, peer evidence and change workflow

### Target billing architecture (follow in order)

1. [ADR 0005: External billing boundary](architecture/decisions/0005-external-billing-boundary.md)
2. [External Billing Boundary Design](superpowers/specs/2026-09-15-external-billing-boundary-design.md)
3. [Portal ↔ Kernel Access Contract Design](superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md)
4. [Accepted live-source commercial admission amendment](superpowers/specs/2026-10-15-live-source-commercial-admission-design-amendment.md) — owner confirmation on 2026-10-20 in ANY-664 / PR #139; narrow source-read/admission supersession, paid trust unchanged. Both specification bodies retain their PR-base content.

### Implementation handoffs and references

- [ANY-709 implementation plan and delivery record](exec-plans/completed/ANY-709-implementation-plan.md)
  — Steps 1-4 DONE as implementation milestones; dated source/verification
  evidence, the accepted cabinet layout and open final-review follow-ups.
  The original proposal remains in Git. Normative dated C1-C4 decisions are in
  [ANY-504](https://linear.app/paveldik/issue/ANY-504); ticket acceptance remains in
  [ANY-709](https://linear.app/paveldik/issue/ANY-709).
- [ANY-765 paid producer and Step 10 handoff](engineering/billing-background-operations.md#step-10-handoff--any-765)
  — implemented local projection/allowance/revision/outbox semantics, B10 boundary
  and acceptance limits; verification history is in the linked porting plan.
- [ANY-765 completed porting plan](exec-plans/completed/ANY-765-implementation-plan-refactor.md)
  — DONE and archived by owner request on 2026-11-09; verification and live-evidence limits retained.
- [ANY-664 completed implementation plan](exec-plans/completed/ANY-664-implementation-plan.md)
  — all eight Portal steps DONE; implementation-commit CI evidence, retained
  real-enablement gates and handoff to ANY-504 program Step 7
- [ANY-766 paid integration target contracts](contracts/portal-kernel-paid/README.md)
  — reviewed target schemas, producer/consumer copies and offline fixtures for
  snapshot V2, identity, invalidation, usage/exhaustion and cabinet contracts;
  runtime implementation remains pending.
- [Provisional Kernel Capability Manifest v1](contracts/kernel-capability-manifest/v1/README.md)
  — ANY-664 specification-derived schema, independent SIMULATED fixtures,
  standalone development HTTP mock and human verification commands; actual
  Kernel producer conformance remains a future enablement gate
- [ANY-664 Step 8 local conformance handoff](contracts/kernel-capability-manifest/v1/step-8-handoff.md)
  — historical local CI PASS and 2026-10-19 real-API deferral; current producer
  availability is in the integration map, with joint conformance still unverified
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
  authoritative current as-built 27-table schema reference
- [Platform Kernel contract boundary](architecture/platform-kernel-contract.md)
  — superseded planned contract; retained historical context

### Other architecture

- [Contours](architecture/contours.md)
- [Region Resolver contract](architecture/region-resolver-contract.md)
- [Deployment](architecture/deployment.md)
- [Architecture decisions](architecture/decisions/README.md)

## Engineering

- [Development](engineering/DEVELOPMENT.md)
- [Billing operations](engineering/ANY-709-billing-runbook.md) — current configuration, commands, migration transitions, diagnosis and recovery.
- [Testing](engineering/TESTING.md)
- [Agent workflow](engineering/AGENT_WORKFLOW.md)
- [Coding conventions](engineering/CODING_CONVENTIONS.md)
- [Internal contracts and proportionate exceptions](engineering/CODING_CONVENTIONS.md#internal-contracts)
- [Correctness review checklist](engineering/review-checklists/correctness.md) — always included by the AI-review configuration
- [Reliability](RELIABILITY.md)
- [Security](SECURITY.md)
- [Quality score](QUALITY_SCORE.md)
- [Execution plans](exec-plans/README.md)
- [ANY-766 active implementation plan](exec-plans/active/ANY-766-implementation-plan.md) — authoritative Portal–Kernel plan for the runtime-research workspace; repository preparation and materialization complete, implementation subject to its gates.
- [ANY-715 completed MVP rebuild plan](exec-plans/completed/ANY-715-mvp-rebuild-plan.md) — Stages 0–6 closed by owner decision; verification evidence, limitations and follow-ups under ANY-820 are retained.
- [Background billing operations](engineering/billing-background-operations.md) — worker settings, scheduling, polling-only operation, retained inbox history, operator commands and diagnostics.

## Legal

- [Legal source workflow](legal/README.md)
- Current RU legal source version: `2026-07-11`.

## Generated references

- [Database schema](generated/db-schema.md)
- [OpenAPI snapshot](generated/openapi.json)
