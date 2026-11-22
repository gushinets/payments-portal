# ANY-830 results

All 17 original keys were found and investigated. All were open in both the
[baseline](baseline.json) and the latest queried main response in the
[final scan evidence](final-scan.json). The latest main analysis still
matches the original revision. The [before/after table](findings.md) and
[canonical ledger](findings.csv) retain individual evidence and actions.

| Original findings | Count |
| --- | ---: |
| Confirmed configuration defects with changes implemented | 5 |
| Verified technical false positives | 5 |
| Intentional test or development behavior | 7 |
| Already resolved at baseline | 0 |
| Unresolved technical investigations | 0 |
| **Total** | **17** |

Four original findings share one fix that limits GitHub token permissions
to the jobs that use them. The workflow is manually disabled, so its
live comment-trigger path could not be exercised. The fifth finding
removes the implicit Next development LAN allowlist. Explicit LAN
configuration remains supported. A separate source-review finding (N01)
is addressed by requiring verifying STARTTLS whenever production mail is
enabled. Local SMTP sinks still work. No live SMTP configuration was
inspected. N01 has no independent Sonar key.

PR #190 analysis `b4048339-4031-4cac-8ddf-bd8e68771ac3` on `36679b064752340a2fdf2d8f3c31c32c418ae40f`
had zero issues in the general and new-code PR queries and a passing
new-code Quality Gate. No replacement key was visible in that analysis.
Main had 28 open Security-impact issues, including 27 legacy
vulnerabilities, overall security rating E and zero hotspots. Main's
new-code Quality Gate was also OK. That gate measures recent code and
can pass while older findings remain open. The PR query did not report
any of the 17 original keys, including the 12 whose flagged code was
preserved. Post-merge main validation is pending.

Five issue-specific False Positive dispositions and seven intentional
development or fixture reviews remain pending. The issue-administration
API returned HTTP 401 without an authenticated issue-admin session. The
five changed findings require post-merge scanner verification. No risk
was accepted. Intentional cases require an issue-by-issue Sonar owner
decision if their treatment would require acceptance. Re-enabling the
AI review workflow remains an operational decision for its owner.
The 11 installation findings and two regex findings retain separate owners.

## Verification of the implementation revision

- Three Python regressions failed as expected before the fixes. Four controls
  passed. The unset-origin Node regression failed as expected while its
  explicit-origin control passed.
- At the implementation change, 272 focused API and tooling cases and both
  Next configuration tests passed. The focused API run used native Git Bash.
  An earlier direct invocation selected WSL Bash and failed 21 shell cases.
- The first canonical commands stopped at regression test formatting. The
  formatting correction is included in the scanned revision.
- The hosted Code Quality job on the scanned revision had one failure in
  the unchanged preflight deadline timing test. That test passed in isolation.
  The PR description tracks the next hosted run and the canonical checks.
- Sonar, CodeQL, Trivy and the two hosted harness smoke jobs passed on the
  scanned revision. The disabled review workflow was verified statically.
