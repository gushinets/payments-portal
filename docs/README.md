# Documentation Index

Status: authoritative index
Last verified: 2026-09-21

Start with the smallest document that matches the task.

## Knowledge-source roles

- Architecture decision records capture durable architectural decisions.
- New billing development follows ADR 0005, then the accepted external-billing
  boundary design, then the accepted Portal-Kernel access-contract design.
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

- [Product scope](PRODUCT.md)
- [Verified `ru` MVP journey](product/ru-mvp.md)
- [Design entry point](DESIGN.md)
- [Bundle 3 reference](design-system/bundle3/README.md)

## Architecture

- [Repository architecture](../ARCHITECTURE.md)

### Target billing architecture (follow in order)

1. [ADR 0005: External billing boundary](architecture/decisions/0005-external-billing-boundary.md)
2. [External Billing Boundary Design](superpowers/specs/2026-09-15-external-billing-boundary-design.md)
3. [Portal ↔ Kernel Access Contract Design](superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md)

### Implementation handoffs and references

- [External Billing Persistence Reset](architecture/external-billing-persistence-reset.md)
  — reviewed `ANY-504` Step 2 persistence/reset implementation handoff,
  subordinate to ADR 0005 and both accepted design baselines above

### Current-state and retained references

- [Payment providers](architecture/payment-providers.md) — retained
  direct-provider characterization; not target external-billing guidance
- [Billing authority](architecture/billing-authority.md) — superseded target
  design retained for current-state and historical context
- [Payment Portal data model](architecture/payment-portal-data-model.md) —
  authoritative current-state schema reference; not the target persistence
  design
- [Platform Kernel contract boundary](architecture/platform-kernel-contract.md)
  — superseded planned contract; retained historical context

### Other architecture

- [Contours](architecture/contours.md)
- [Region Resolver contract](architecture/region-resolver-contract.md)
- [Deployment](architecture/deployment.md)
- [Architecture decisions](architecture/decisions/README.md)
- [DDD-lite audit and safe remediation](architecture/ddd-lite-audit.md) —
  smell catalog and two billing slices; not current-state authority

## Engineering

- [Development](engineering/DEVELOPMENT.md)
- [Testing](engineering/TESTING.md)
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
