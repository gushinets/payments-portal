# Agent Delivery Workflow

Status: authoritative
Last verified: 2026-11-13

1. Confirm the Linear issue and required PR title.
2. Read the root and subtree `AGENTS.md` files plus the relevant source of truth.
3. Assess existing coverage before editing: identify the changed contract,
   affected producers/consumers, existing assertions and missing guarantees.
   For a bug, add and run a regression against unchanged behavior and record
   its expected failure before fixing it. For behavior-preserving changes,
   record a measurable baseline and characterization of the behavior retained.
4. Create or update the checked-in execution plan for substantial work.
5. Implement the smallest coherent change under the
   [internal-contract conventions](CODING_CONVENTIONS.md#internal-contracts).
   Preserve compatibility, existing ownership and intentional use-case
   differences; avoid speculative mechanisms or unrelated migrations.
6. Run the smallest relevant checks while iterating, using the
   [Testing Strategy](TESTING.md) to select the cheapest layer that protects the
   invariant. Before consolidating tests, record each old assertion/guarantee
   and its retained test owner in the execution plan; keep distinct integration
   guarantees and do not use test-count reduction as the success metric.
7. Drive affected application journeys and collect evidence.
8. Query logs, metrics, and traces for unexpected behavior.
9. Inspect the diff for unrelated, generated, sensitive, or suspicious changes.
10. Apply the relevant independent review checklists, including
    [correctness](review-checklists/correctness.md). Trace the affected contract
    through construction/defaults, writes, branches, queries/SQL, serialization
    and consumers. Separate new findings from existing debt and a rule gap from
    a reproduced runtime defect; do not infer guarantees from a green suite.
11. Resolve feedback and rerun affected checks.
12. Run the broadest supported canonical check on the final source state.
    Reuse still-valid evidence when code, environment and scope are unchanged;
    do not routinely run complete partitions again immediately before `check`.
    Use `--coverage` when coverage is required so API-fast and components run
    once each. Record any skipped or blocked check and its reason.
13. Open the PR as `ANY-<number> - <summary>` and include the Linear URL.
14. Leave merge approval to a human.

For each applicable journey, runtime signal and check, record passed, failed,
blocked, skipped or unreached against the actual revision. Explain a
not-applicable browser/provider journey for tooling/documentation changes;
do not invent runtime evidence. Reuse valid results when code, environment and
scope are unchanged. Resolve routine reversible choices autonomously; use the
conventions' bounded-exception and owner-escalation guidance for unresolved
behavior, compatibility, trust, authorization, ownership or unavoidable scope
decisions. An existing explicit decision does not need approval again.

Keep compact commands, actual revision, outcomes, timings and limitations in
the plan. Detailed logs, manifests, JUnit and browser artifacts stay under
ignored `.harness/` paths or in CI artifacts. For performance work, preserve
controlled inputs and repeated measurements and state startup exclusions,
storage/process differences and load variability as described in the Testing
Strategy. Local checks do not establish a remote CI PASS.

When an agent struggles, identify the missing fixture, command, documentation,
guardrail, or runtime signal and improve the harness rather than repeating an
underspecified prompt.
