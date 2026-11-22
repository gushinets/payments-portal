# ANY-830 Sonar security audit

[Linear issue](https://linear.app/paveldik/issue/ANY-830) · [Sonar main issues](https://sonarcloud.io/project/issues?id=gushinets_payments-portal&branch=main)

The fetched baseline is `236c852e88b5374dcc0c34baae4981bbc78c87c7`. Sonar main analysis
`509b5422-b252-414b-9b02-0c7a0250c118` at 2026-11-21 19:17:59 UTC analyzed the same revision.
[Baseline evidence](baseline.json) contains selected public API fields. Profile
metadata is the current project association, rather than a historical profile
export. Issue keys were taken from Linear, with Markdown escaping normalized
and all 17 identities confirmed by the Sonar API.

[Canonical ledger](findings.csv) · [Readable table](findings.md) · [Summary](summary.md)

Trace each rule to its actual inputs, caller and privileges. Compare that
evidence with scanner status, keeping technical classification, implementation,
scanner disposition and risk acceptance independent. Retain ANY-744 installation
and ANY-745/746 regex ownership in the separate ledger section. Store only
sanitized metadata. Main and PR analyses are recorded independently.

Update the CSV and regenerate the readable table with
`python docs/engineering/evidence/ANY-830/render.py` from the repository root.
