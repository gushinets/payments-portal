# Documentation Index

Status: authoritative index
Last verified: 2026-09-04

Start with the smallest document that matches the task.

## Knowledge-source roles

- Architecture decision records capture durable architectural decisions.
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
- [Contours](architecture/contours.md)
- [Region Resolver contract](architecture/region-resolver-contract.md)
- [Payment providers](architecture/payment-providers.md)
- [Billing authority](architecture/billing-authority.md)
- [Payment Portal data model](architecture/payment-portal-data-model.md)
- [Deployment](architecture/deployment.md)
- [Platform Kernel contract boundary](architecture/platform-kernel-contract.md)
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
