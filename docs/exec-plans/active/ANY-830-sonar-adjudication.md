# ANY-830 Sonar adjudication

Objective: adjudicate the 17 original keys against fetched main, fix confirmed
in-scope defects and retain auditable before/after evidence.

- [x] Confirm Linear, isolate at fetched main and capture scanner identities.
- [ ] Trace the six priority findings, then the other eleven. Record provenance,
  counter-evidence, verification and separate owners in the
  [findings ledger](../../engineering/evidence/ANY-830/findings.csv).
- [ ] Establish failing regressions for confirmed defects, implement proportionate
  fixes and run focused and canonical checks.
- [ ] Recheck main, publish a focused PR and reconcile its Sonar result with the
  separately queried main set. Record access and post-merge limitations.

Preserve test fixtures, production readiness checks, SMTP verification and
dependency-installation policy ownership. No merge or residual-risk approval.
