"""Render the audit's review table from the canonical CSV."""

import csv
from pathlib import Path


def cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", " ")


def main() -> None:
    folder = Path(__file__).resolve().parent
    with (folder / "findings.csv").open(encoding="utf-8", newline="") as ledger:
        rows = list(csv.DictReader(ledger))

    lines = ["# ANY-830 before/after findings", "", "Derived from [findings.csv](findings.csv)."]
    for heading, scope in (
        ("Original findings", lambda row: row["scope"] == "ANY-830"),
        ("New findings", lambda row: row["scope"] == "New ANY-830"),
        ("Separate ownership", lambda row: row["scope"] not in {"ANY-830", "New ANY-830"}),
    ):
        lines.extend([
            "",
            f"## {heading}",
            "",
            "| ID | Sonar issue / location | Rule / security impact | Previous conclusion | Review verdict | Current classification | Action | Baseline main | Recorded main | PR observation |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ])
        for row in filter(scope, rows):
            key = row["issue_key"]
            issue = f"[{key}]({row['issue_url']})<br>" if key else ""
            values = [
                row["id"],
                f"{issue}`{row['location']}`",
                f"{row['rule']} / {row['security_impact'] or 'Unrated'}",
                row["previous_conclusion"],
                row["review_verdict"],
                row["classification"],
                row["action"],
                row["baseline_status"],
                row["final_main_status"],
                row["pr_observation"],
            ]
            lines.append("| " + " | ".join(map(cell, values)) + " |")
    (folder / "findings.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
