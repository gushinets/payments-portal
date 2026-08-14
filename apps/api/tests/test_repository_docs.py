from __future__ import annotations

import argparse
import stat
from pathlib import Path

import pytest

import scripts.repo as repo
from scripts.repo import (
    canonical_check_environment,
    check_expected_legal_versions,
    check_required_markdown_link_content,
    resolve_cloudpayments_api_secret,
    resolve_cloudpayments_public_id,
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

    assert len(invocations) == 4
    assert all(environment is check_environment for _, environment in invocations)
    assert any("test:components" in command for command, _ in invocations)
    assert any("pytest" in command for command, _ in invocations)


def test_full_check_runs_alembic_with_postgres_fixture_fallback(
    monkeypatch,
) -> None:
    check_environment = {
        "POSTGRES_USER_TEST": "test-user",
        "POSTGRES_PASSWORD_TEST": "test-password",
        "POSTGRES_PORT_TEST": "5432",
        "POSTGRES_DB_TEST": "payment_portal_test",
    }
    invocations: list[tuple[list[str], dict[str, str] | None]] = []

    monkeypatch.delenv("TEST_POSTGRES_DATABASE_URL", raising=False)
    monkeypatch.delenv("RUN_E2E", raising=False)
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

    repo.cmd_check(argparse.Namespace(fast=False))

    alembic_invocations = [
        (command, environment)
        for command, environment in invocations
        if "apps/api/tests/test_alembic_postgres.py" in command
        and "--ignore" not in command
    ]
    assert alembic_invocations == [
        (
            [
                repo.sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "apps/api/tests/test_alembic_postgres.py",
            ],
            check_environment,
        )
    ]


def test_cloudpayments_public_id_uses_process_environment_first() -> None:
    value = resolve_cloudpayments_public_id(
        {"CLOUDPAYMENTS_PUBLIC_ID": "pk_from_dotenv"},
        environ={"CLOUDPAYMENTS_PUBLIC_ID": "pk_from_process"},
    )

    assert value == "pk_from_process"


def test_cloudpayments_public_id_uses_dotenv_fallback() -> None:
    value = resolve_cloudpayments_public_id(
        {"CLOUDPAYMENTS_PUBLIC_ID": "pk_from_dotenv"},
        environ={},
    )

    assert value == "pk_from_dotenv"


def test_cloudpayments_public_id_defaults_empty_when_missing() -> None:
    value = resolve_cloudpayments_public_id({}, environ={})

    assert value == ""


def test_cloudpayments_public_id_ignores_legacy_next_public_value() -> None:
    value = resolve_cloudpayments_public_id(
        {"NEXT_PUBLIC_CLOUDPAYMENTS_PUBLIC_ID": "pk_legacy_dotenv"},
        environ={"NEXT_PUBLIC_CLOUDPAYMENTS_PUBLIC_ID": "pk_legacy_process"},
    )

    assert value == ""


def test_cloudpayments_api_secret_uses_process_environment_first() -> None:
    value = resolve_cloudpayments_api_secret(
        {"CLOUDPAYMENTS_API_SECRET": "secret_from_dotenv"},
        environ={"CLOUDPAYMENTS_API_SECRET": "secret_from_process"},
    )

    assert value == "secret_from_process"


def test_cloudpayments_api_secret_uses_dotenv_before_runtime_fallback() -> None:
    value = resolve_cloudpayments_api_secret(
        {"CLOUDPAYMENTS_API_SECRET": "secret_from_dotenv"},
        environ={},
    )

    assert value == "secret_from_dotenv"


def test_cloudpayments_api_secret_skips_empty_values_before_fallback() -> None:
    dotenv_value = resolve_cloudpayments_api_secret(
        {"CLOUDPAYMENTS_API_SECRET": "secret_from_dotenv"},
        environ={"CLOUDPAYMENTS_API_SECRET": ""},
    )
    fallback_value = resolve_cloudpayments_api_secret(
        {"CLOUDPAYMENTS_API_SECRET": ""},
        environ={"CLOUDPAYMENTS_API_SECRET": ""},
    )

    assert dotenv_value == "secret_from_dotenv"
    assert fallback_value == "test-cloudpayments-signing-key"


def test_write_runtime_protects_generated_secret_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    harness_dir = tmp_path / ".harness"
    runtime_json = harness_dir / "runtime.json"
    runtime_env = harness_dir / "runtime.env"
    monkeypatch.setattr(repo, "HARNESS_DIR", harness_dir)
    monkeypatch.setattr(repo, "RUNTIME_JSON", runtime_json)
    monkeypatch.setattr(repo, "RUNTIME_ENV", runtime_env)
    monkeypatch.setattr(repo, "read_dotenv", lambda: {})

    repo.write_runtime(
        repo.RuntimeConfig(
            worktree_id="test",
            compose_project="payment-portal-test",
            database_name="payment_portal_test",
            web_port=3000,
            api_port=8000,
            postgres_port=5432,
            grafana_port=3001,
            loki_port=3100,
            prometheus_port=9090,
            tempo_port=3200,
            otlp_grpc_port=4317,
            otlp_http_port=4318,
        )
    )

    assert stat.S_IMODE(harness_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(runtime_env.stat().st_mode) == 0o600
    assert "CLOUDPAYMENTS_API_SECRET=test-cloudpayments-signing-key" in (
        runtime_env.read_text(encoding="utf-8")
    )


def test_write_runtime_does_not_leave_secret_when_protection_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    harness_dir = tmp_path / ".harness"
    runtime_json = harness_dir / "runtime.json"
    runtime_env = harness_dir / "runtime.env"
    monkeypatch.setattr(repo, "HARNESS_DIR", harness_dir)
    monkeypatch.setattr(repo, "RUNTIME_JSON", runtime_json)
    monkeypatch.setattr(repo, "RUNTIME_ENV", runtime_env)
    monkeypatch.setattr(repo, "read_dotenv", lambda: {})
    monkeypatch.setenv("CLOUDPAYMENTS_API_SECRET", "super-secret")

    def fail_protection(path: Path) -> None:
        assert path.read_text(encoding="utf-8") == ""
        raise repo.HarnessError("protection failed")

    monkeypatch.setattr(repo, "protect_runtime_env_file", fail_protection)

    with pytest.raises(repo.HarnessError, match="protection failed"):
        repo.write_runtime(
            repo.RuntimeConfig(
                worktree_id="test",
                compose_project="payment-portal-test",
                database_name="payment_portal_test",
                web_port=3000,
                api_port=8000,
                postgres_port=5432,
                grafana_port=3001,
                loki_port=3100,
                prometheus_port=9090,
                tempo_port=3200,
                otlp_grpc_port=4317,
                otlp_http_port=4318,
            )
        )

    assert not runtime_env.exists()
    assert all(
        "super-secret" not in path.read_text(encoding="utf-8")
        for path in harness_dir.iterdir()
        if path.is_file()
    )


def test_runtime_env_windows_acl_removes_inheritance_for_current_user() -> None:
    invocations: list[list[str]] = []

    repo.protect_runtime_env_file(
        Path("C:/repo/.harness/runtime.env"),
        os_name="nt",
        environ={
            "USERNAME": "agent",
            "USERDOMAIN": "WORKSTATION",
            "COMPUTERNAME": "WORKSTATION",
        },
        runner=lambda command: invocations.append(command),
        icacls_path="icacls",
    )

    assert invocations == [
        [
            "icacls",
            "C:/repo/.harness/runtime.env",
            "/inheritance:r",
            "/grant:r",
            "agent:RW",
        ]
    ]


def test_harness_directory_windows_acl_removes_inheritance_for_current_user() -> None:
    invocations: list[list[str]] = []

    repo.protect_private_directory(
        Path("C:/repo/.harness"),
        os_name="nt",
        environ={
            "USERNAME": "agent",
            "USERDOMAIN": "WORKSTATION",
            "COMPUTERNAME": "WORKSTATION",
        },
        runner=lambda command: invocations.append(command),
        icacls_path="icacls",
    )

    assert invocations == [
        [
            "icacls",
            "C:/repo/.harness",
            "/inheritance:r",
            "/grant:r",
            "agent:(OI)(CI)F",
        ]
    ]


def test_runtime_env_windows_acl_preserves_domain_user() -> None:
    invocations: list[list[str]] = []

    repo.protect_runtime_env_file(
        Path("C:/repo/.harness/runtime.env"),
        os_name="nt",
        environ={
            "USERNAME": "agent",
            "USERDOMAIN": "ANYTOOL",
            "COMPUTERNAME": "WORKSTATION",
        },
        runner=lambda command: invocations.append(command),
        icacls_path="icacls",
    )

    assert invocations[0][-1] == "ANYTOOL\\agent:RW"


def test_runtime_env_windows_acl_requires_current_user() -> None:
    with pytest.raises(repo.HarnessError, match="current user is unknown"):
        repo.protect_runtime_env_file(
            Path("C:/repo/.harness/runtime.env"),
            os_name="nt",
            environ={},
            runner=lambda command: None,
            icacls_path="icacls",
        )
