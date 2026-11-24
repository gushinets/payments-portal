# ANY-830 Sonar security audit

[Linear issue](https://linear.app/paveldik/issue/ANY-830) · [PR #190](https://github.com/gushinets/payments-portal/pull/190) · [Sonar main issues](https://sonarcloud.io/project/issues?id=gushinets_payments-portal&branch=main)

The fetched baseline is `236c852e88b5374dcc0c34baae4981bbc78c87c7`. Sonar's main analysis
`509b5422-b252-414b-9b02-0c7a0250c118` at 2026-11-21 19:17:59 UTC analyzed the same revision.
[Baseline evidence](baseline.json) contains selected public API fields. The
relevant current profiles are Sonar way core. Profile metadata records current
project association. A historical profile export was unavailable.

The historical [PR Sonar analysis](https://sonarcloud.io/dashboard?id=gushinets_payments-portal&pullRequest=190)
`b4048339-4031-4cac-8ddf-bd8e68771ac3` analyzed `36679b064752340a2fdf2d8f3c31c32c418ae40f` at
2026-11-22 13:21:38 UTC and completed at 13:22:11 UTC. The Sonar pull
request listing, compute task and exact-commit GitHub check attest to this
result. [Final scan evidence](final-scan.json) also records the separate
main re-query from that session. The [reconciliation scan](reconciliation-scan.json)
records the newer analysis of main and all 17 exact original keys, alongside
the separately identified PR analysis on the conflict-resolution commit.
The PR description records the hosted status of the evidence commit itself.

[Canonical ledger](findings.csv) · [Readable table](findings.md) · [Independent review](review.md) · [Summary](summary.md)

Issue keys came from Linear. Markdown escaping was normalized and all 17
keys were confirmed by the Sonar API. Each source review traces the
input origin, consumers, permissions and prerequisites, then compares
those facts with the flagged mechanism. Technical classification,
implementation, scanner disposition and risk acceptance stay independent.
The ledger preserves the original keys, historical baseline, and previous
technical conclusions. Separate-ownership rows for ANY-744 installation and
ANY-745/746 regex retain their historical scan metadata. Evidence uses
sanitized metadata only.

Edit the CSV and regenerate the Markdown table with
`python docs/engineering/evidence/ANY-830/render.py` from the repository
root. The table links each issue to its main-branch record.
