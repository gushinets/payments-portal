# ANY-830 results

PR #190 was reconciled with main `550263e644b49baa01d313de32ddaf1db0016b08`.
GitHub reported the conflict-resolution commit
`6e3c8a2c39d0c017b57820116c9a5e21a4ae20ae` as mergeable.
The [independent review](review.md) records the conflict rationale,
trust boundaries, per-finding verdicts, and verification limits.
The [before/after table](findings.md) derives from the [CSV ledger](findings.csv).

| Original findings | Count |
| --- | ---: |
| Configuration findings addressed in the PR, including workflow-default hardening | 5 |
| Open technical false positives | 4 |
| Intentional development or test behavior | 7 |
| Historical false positive now fixed on main by ANY-896 | 1 |
| **Total** | **17** |

Four findings concern one change that assigns token permissions by job in
the manually disabled AI review workflow. The gate and finalizer keep their
endpoint permissions, and the reusable caller retains the union required by
the pinned jobs. For Checks write, all current jobs need the grant. The
empty workflow default constrains future jobs. The fifth finding removes an
implicit additional development origin while preserving explicit LAN use.
The environment example directs developers to the web launch environment or
`apps/web/.env.local` for this opt-in.
N01 separately requires STARTTLS when production SMTP is configured. The
existing verifying context and disabled-mail and local sink behavior were
reviewed. The workflow stayed disabled and live SMTP was outside the tests.

## Scanner evidence

- [Historical baseline](baseline.json) and [historical PR scan](final-scan.json)
  preserve the original run. All 17 exact keys were open at that baseline.
- [Reconciliation scan](reconciliation-scan.json) captures the main and PR
  observations. Main analysis `a8ff1bc4-68b1-4a7b-9043-28cdddb8bc2e` on
  `550263e644b49baa01d313de32ddaf1db0016b08` reports 16 of the original keys
  open and F07 fixed following ANY-896. The project has 25 open or confirmed
  Security-impact issues on main, including 24 legacy vulnerabilities. Its
  overall security rating is E and the new-code gate is OK.
- The separate PR analysis `b456d12f-d4a0-44c4-b045-a1ed743930e1` on
  `6e3c8a2c39d0c017b57820116c9a5e21a4ae20ae` completed as compute task
  `AaIOLkLflROuuN-CHiAZ`. Both general and new-code PR issue queries returned
  zero, with a passing gate. PR absence leaves the corresponding main issue
  status to the main analysis. The PR description tracks the evidence commit
  and its hosted checks separately.

## Verification

- The first reconciled focused run found two failing positive SMTP settings
  cases from the SQLite fixture. With the production psycopg fixture, all
  162 focused Python cases and both Next configuration cases passed in native
  Git Bash on Windows. The review traces additional existing fixture,
  subprocess, report, and mail checks to their actual coverage.
- On `6e3c8a2c39d0c017b57820116c9a5e21a4ae20ae`, all five hosted CI jobs
  passed, including browser, PostgreSQL and migrations, image builds and
  API readiness. Trivy, CodeQL and metadata also passed. CodeRabbit skipped.
  [CI run](https://github.com/gushinets/payments-portal/actions/runs/45426213096) ·
  [Security run](https://github.com/gushinets/payments-portal/actions/runs/45426213172)
- The follow-up evidence and environment-example wording do not change
  application or workflow code.

## Remaining actions

Four individual false-positive proposals and seven intentional-use
adjudications remain for Sonar issue administration. Issue-admin access was
unavailable in this review. The five PR changes need a fresh main analysis
after a separately authorized merge. F07 already has an automated main
disposition. The workflow's re-enable decision and any production-relay
compatibility verification stay with their operational owners. The 11
installation findings and two regex findings retain separate ownership.
