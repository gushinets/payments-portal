# Agent Delivery Workflow

Status: authoritative
Last verified: 2026-07-11

1. Confirm the Linear issue and required PR title.
2. Read the root and subtree `AGENTS.md` files plus the relevant source of truth.
3. Reproduce the failure or record a measurable baseline.
4. Create or update the checked-in execution plan for substantial work.
5. Implement the smallest coherent change.
6. Run focused checks while iterating.
7. Drive affected application journeys and collect evidence.
8. Query logs, metrics, and traces for unexpected behavior.
9. Inspect the diff for unrelated, generated, sensitive, or suspicious changes.
10. Apply the relevant independent review checklists.
11. Resolve feedback and rerun affected checks.
12. Run the broadest supported canonical check.
13. Open the PR as `ANY-<number> - <summary>` and include the Linear URL.
14. Leave merge approval to a human.

When an agent struggles, identify the missing fixture, command, documentation,
guardrail, or runtime signal and improve the harness rather than repeating an
underspecified prompt.
