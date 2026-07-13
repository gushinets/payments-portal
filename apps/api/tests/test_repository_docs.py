from __future__ import annotations

from pathlib import Path

from scripts.repo import (
    check_expected_legal_versions,
    check_required_markdown_link_content,
)


def test_consistent_knowledge_fixture_passes() -> None:
    root = Path("repository").resolve()
    source = root / "AGENTS.md"
    authority = root / "docs" / "PRODUCT.md"

    assert (
        check_required_markdown_link_content(
            source,
            "[Product](docs/PRODUCT.md)\n",
            [authority],
            root=root,
        )
        == []
    )
    assert (
        check_expected_legal_versions(
            "2026-07-11",
            [
                ("docs/README.md", ["2026-07-11"], 1),
                ("migration", ["2026-07-11"] * 6, 6),
            ],
        )
        == []
    )


def test_missing_core_authority_link_is_actionable() -> None:
    root = Path("repository").resolve()
    source = root / "AGENTS.md"
    authority = root / "docs" / "PRODUCT.md"

    assert check_required_markdown_link_content(
        source,
        "# Repository map\n",
        [authority],
        root=root,
    ) == [
        f"Missing core authority link in AGENTS.md: {Path('docs') / 'PRODUCT.md'}"
    ]


def test_stale_documented_legal_version_is_rejected() -> None:
    errors = check_expected_legal_versions(
        "2026-07-11", [("docs/README.md", ["2026-07-02"], 1)]
    )

    assert errors == [
        "Current legal version mismatch in docs/README.md: expected 1 occurrence(s) "
        "of 2026-07-11, found 2026-07-02"
    ]


def test_migration_legal_version_mismatch_is_rejected() -> None:
    errors = check_expected_legal_versions(
        "2026-07-11", [("initial migration", ["2026-07-11"] * 5, 6)]
    )

    assert errors == [
        "Current legal version mismatch in initial migration: expected 6 occurrence(s) "
        "of 2026-07-11, found 2026-07-11, 2026-07-11, 2026-07-11, "
        "2026-07-11, 2026-07-11"
    ]
