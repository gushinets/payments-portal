# ANY-830 Sonar adjudication

Objective: adjudicate the 17 original keys against fetched main, fix confirmed
in-scope defects and retain auditable before/after evidence.

- [x] Confirm Linear, isolate at fetched main and capture scanner identities.
- [x] Trace the six priority findings, then the other eleven. Record provenance,
  counter-evidence, verification and separate owners in the
  [findings ledger](../../engineering/evidence/ANY-830/findings.csv).
- [x] Establish failing regressions for confirmed defects, implement proportionate
  fixes and run focused checks.
- [x] Recheck main, publish a focused PR and reconcile its Sonar result with the
  separately queried main set. Record access and post-merge limitations.

Preserve test fixtures, production readiness checks, SMTP verification and
dependency-installation policy ownership. No merge or residual-risk approval.

- [x] Reconcile the existing PR with main, preserve both test suites and verify
  mergeability. Review 17 original keys and N01 independently and correct the
  ledger for upstream changes and review evidence.
- [ ] Record canonical and hosted verification results and hand off the PR.
- [ ] Revalidate the original keys on main after a human-approved merge. Sonar
  issue administration remains pending for the documented per-issue dispositions.
