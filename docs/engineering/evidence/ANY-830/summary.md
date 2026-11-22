# ANY-830 results

All 17 original issue identities were located and investigated against the
[fetched baseline](baseline.json). They were open at baseline. The
[before/after table](findings.md) and [canonical ledger](findings.csv) retain
the issue-level evidence.

| Original findings | Count |
| --- | ---: |
| Confirmed configuration defects with changes implemented | 5 |
| Verified technical false positives | 5 |
| Intentional test or development behavior | 7 |
| Already resolved at baseline | 0 |
| Unresolved technical investigations | 0 |
| **Total** | **17** |

Four original findings share one workflow fix, which limits GitHub token
permissions to the jobs that use them. The workflow is manually disabled.
The other original defect is the implicit Next development LAN allowlist.
A separate source-review finding (N01) is addressed by requiring STARTTLS
when production email delivery is enabled. It has no independent Sonar key.

PR evidence and latest main reconciliation are pending. Main initially had
28 open Security-impact issues, including 27 legacy vulnerabilities, overall
security rating E and zero hotspots. The new-code Quality Gate was OK.
That gate measures a recent code period and can pass with older open issues.

Issue administration requires authenticated Sonar issue-admin access. The
public permissions request returned HTTP 401. The five false-positive
proposals and seven intentional-case reviews are pending on their exact keys.
Implementation status is distinct from scanner status. No risk was accepted.
The 11 installation-policy findings and the two regex findings have separate
owners and do not enter the denominator.
