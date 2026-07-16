from __future__ import annotations

import argparse
from pathlib import Path

import scripts.repo as repo
from scripts.repo import (
    canonical_check_environment,
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


def test_canonical_checks_use_a_worktree_scoped_temp_directory(tmp_path: Path) -> None:
    first_root = tmp_path / "first-worktree"
    second_root = tmp_path / "second-worktree"
    original = {"PATH": "tools", "TEMP": "unreadable-system-temp"}

    first = canonical_check_environment(root=first_root, environ=original)
    second = canonical_check_environment(root=second_root, environ=original)

    first_temp = (first_root / ".harness" / "tmp").resolve()
    second_temp = (second_root / ".harness" / "tmp").resolve()
    assert first["PATH"] == "tools"
    assert original["TEMP"] == "unreadable-system-temp"
    assert {first[name] for name in ("TEMP", "TMP", "TMPDIR")} == {
        str(first_temp)
    }
    assert {second[name] for name in ("TEMP", "TMP", "TMPDIR")} == {
        str(second_temp)
    }
    assert first_temp.is_dir()
    assert second_temp.is_dir()
    assert first_temp != second_temp


def test_fast_check_passes_the_scoped_environment_to_every_subprocess(
    monkeypatch,
) -> None:
    check_environment = {"TEMP": "worktree-temp"}
    invocations: list[tuple[list[str], dict[str, str] | None]] = []

    monkeypatch.setattr(repo, "canonical_check_environment", lambda: check_environment)
    monkeypatch.setattr(repo, "cmd_docs", lambda _: None)
    monkeypatch.setattr(repo, "cmd_generate", lambda _: None)
    monkeypatch.setattr(repo, "cmd_architecture", lambda _: None)
    monkeypatch.setattr(repo, "tool", lambda name: name)
    monkeypatch.setattr(
        repo,
        "run",
        lambda command, **kwargs: invocations.append((command, kwargs.get("env"))),
    )

    repo.cmd_check(argparse.Namespace(fast=True))

    assert len(invocations) == 3
    assert all(environment is check_environment for _, environment in invocations)
    assert any("pytest" in command for command, _ in invocations)
