# ANY-674 — Clean PR delivery plan

Ticket: https://linear.app/paveldik/issue/ANY-674

## Scope and coverage

Replace PR179 with a fresh branch from fetched main1584c3fc. Retain its reviewed
implementation and regression tests, without historical audit datasets or commits.
No runtime behavior is redesigned. Original evidence stays on the old draft PR
and local archive branch. The [handoff](../../engineering/ANY-674-high-remediation-followup.md)
records supported updates, evidence custody and the agreed follow-up decision.

- [x] Preserve old branch/evidence; convert PR179 to draft.
- [x] Copy26 implementation/test/operational-doc paths exactly from6e650f46.
- [x] Keep only concise handoff and this plan; omit raw reports/inventories.
- [x] Verify26 copied blob identities,183 focused tests (Git Bash), documentation, lint and metadata.
- [ ] Publish one new commit/PR against current main and link replacement from old PR.
- [ ] Record exact new-head hosted canonical/security results when available.

Reuse historical runtime characterization only where blobs are identical. New CI
must verify current-main composition. No merge, deploy, risk exception or Linear
completion. Human review decides whether the scoped Linear follow-up satisfies P1.
