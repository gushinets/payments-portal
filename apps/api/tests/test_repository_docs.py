from __future__ import annotations

import argparse
import stat
from pathlib import Path

import pytest

import scripts.repo as repo
from scripts.repo import (
    canonical_check_environment,
    check_canonical_persisted_model_layer,
    check_documented_metadata_tables,
    check_expected_legal_versions,
    check_required_markdown_link_content,
    direct_api_environment,
    host_database_url_from_runtime,
    api_test_environment,
    build_parser,
    validate_production_caddy_domain,
    validate_production_deployment_environment,
    resolve_cloudpayments_api_secret,
    resolve_cloudpayments_public_id,
    uv_environment,
)


def _write_api_source(root: Path, relative: str, source: str) -> None:
    path = root / "apps/api/app" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_canonical_persisted_model_guard_rejects_billing_model_facade(tmp_path: Path) -> None:
    _write_api_source(tmp_path, "domains/billing/models.py", "from app.models import Order\n")

    errors = check_canonical_persisted_model_layer(tmp_path)

    assert any("domains/billing/models.py is forbidden" in error for error in errors)


def test_canonical_persisted_model_guard_rejects_billing_model_import(tmp_path: Path) -> None:
    _write_api_source(tmp_path, "feature.py", "from app.domains.billing.models import Order\n")

    errors = check_canonical_persisted_model_layer(tmp_path)

    assert any("imports ORM models through app.domains.billing.models" in error for error in errors)


def test_canonical_persisted_model_guard_rejects_duplicate_enum_definition(tmp_path: Path) -> None:
    _write_api_source(tmp_path, "feature.py", "class PaymentStatus: pass\n")

    errors = check_canonical_persisted_model_layer(tmp_path)

    assert any("defines protected persisted enum PaymentStatus" in error for error in errors)


def test_canonical_persisted_model_guard_rejects_removed_enum_facades(tmp_path: Path) -> None:
    _write_api_source(
        tmp_path,
        "feature.py",
        "from app.domains.billing.enums import PaymentStatus\nfrom app.domains.legal.enums import AcceptanceKind\n",
    )

    errors = check_canonical_persisted_model_layer(tmp_path)

    assert any("imports PaymentStatus through the removed billing enum façade" in error for error in errors)
    assert any("imports the removed legal enum façade" in error for error in errors)


def test_canonical_persisted_model_guard_allows_canonical_definition(tmp_path: Path) -> None:
    _write_api_source(tmp_path, "models/enums.py", "class PaymentStatus: pass\n")

    assert check_canonical_persisted_model_layer(tmp_path) == []


def test_canonical_persisted_model_guard_allows_unrelated_provider_enum(tmp_path: Path) -> None:
    _write_api_source(
        tmp_path,
        "domains/billing/enums.py",
        "from enum import StrEnum\n\nclass ProviderSubscriptionState(StrEnum):\n    ACTIVE = 'active'\n",
    )

    assert check_canonical_persisted_model_layer(tmp_path) == []


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
    ) == [f"Missing core authority link in AGENTS.md: {Path('docs') / 'PRODUCT.md'}"]


def test_stale_documented_legal_version_is_rejected() -> None:
    errors = check_expected_legal_versions("2026-07-11", [("docs/README.md", ["2026-07-02"], 1)])

    assert errors == [
        "Current legal version mismatch in docs/README.md: expected 1 occurrence(s) of 2026-07-11, found 2026-07-02"
    ]


def test_migration_legal_version_mismatch_is_rejected() -> None:
    errors = check_expected_legal_versions("2026-07-11", [("initial migration", ["2026-07-11"] * 5, 6)])

    assert errors == [
        "Current legal version mismatch in initial migration: expected 6 occurrence(s) "
        "of 2026-07-11, found 2026-07-11, 2026-07-11, 2026-07-11, "
        "2026-07-11, 2026-07-11"
    ]


def test_canonical_metadata_table_entry_is_accepted() -> None:
    assert (
        check_documented_metadata_tables(
            ["documented_table"],
            "| `documented_table` | Implemented | Purpose |\n",
        )
        == []
    )


def test_metadata_table_name_only_in_prose_is_still_missing() -> None:
    assert check_documented_metadata_tables(
        ["referenced_table"],
        "The `referenced_table` relation is discussed elsewhere.\n",
    ) == ["Implemented table missing from canonical data model: referenced_table"]


def test_missing_metadata_tables_are_reported_sorted() -> None:
    assert check_documented_metadata_tables(
        ["zeta_table", "documented_table", "alpha_table"],
        "| `documented_table` | Implemented | Purpose |\n",
    ) == [
        "Implemented table missing from canonical data model: alpha_table",
        "Implemented table missing from canonical data model: zeta_table",
    ]


def test_check_docs_uses_imported_metadata_tables(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FakeMetadata:
        tables = {
            "documented_table": object(),
            "metadata_only_table": object(),
        }

    class FakeBase:
        metadata = FakeMetadata()

    for required in (
        "AGENTS.md",
        "ARCHITECTURE.md",
        "docs/README.md",
        "docs/architecture/payment-portal-data-model.md",
        "docs/architecture/contours.md",
        "docs/architecture/region-resolver-contract.md",
        "docs/architecture/payment-providers.md",
        "docs/product/ru-mvp.md",
    ):
        path = tmp_path / required
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    (tmp_path / "docs/architecture/payment-portal-data-model.md").write_text(
        "| `documented_table` | Implemented | Purpose |\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(repo, "ROOT", tmp_path)
    monkeypatch.setattr(repo, "check_knowledge_hierarchy", lambda: [])
    monkeypatch.setattr(repo, "engineering_markdown_files", lambda: [])
    monkeypatch.setattr(repo, "import_api", lambda: (FakeBase, object()))

    assert repo.check_docs() == ["Implemented table missing from canonical data model: metadata_only_table"]


def test_canonical_checks_use_a_worktree_scoped_temp_directory(tmp_path: Path) -> None:
    first_root = tmp_path / "first-worktree"
    second_root = tmp_path / "second-worktree"
    original = {
        "PATH": "tools",
        "TEMP": "unreadable-system-temp",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318",
    }

    first = canonical_check_environment(root=first_root, environ=original)
    second = canonical_check_environment(root=second_root, environ=original)

    first_temp = (first_root / ".harness" / "tmp").resolve()
    second_temp = (second_root / ".harness" / "tmp").resolve()
    assert first["PATH"] == "tools"
    assert original["TEMP"] == "unreadable-system-temp"
    assert {first[name] for name in ("TEMP", "TMP", "TMPDIR")} == {str(first_temp)}
    assert {second[name] for name in ("TEMP", "TMP", "TMPDIR")} == {str(second_temp)}
    assert first["OTEL_EXPORTER_OTLP_ENDPOINT"] == ""
    assert second["OTEL_EXPORTER_OTLP_ENDPOINT"] == ""
    assert first_temp.is_dir()
    assert second_temp.is_dir()
    assert first_temp != second_temp


def test_production_compose_derives_database_url_from_postgres_environment() -> None:
    production_compose = Path("docker-compose.prod.yml").read_text(encoding="utf-8")
    production_example = Path(".env.production.example").read_text(encoding="utf-8")

    assert "DATABASE_URL=" not in production_example
    assert "DATABASE_URL: ${DATABASE_URL:?" not in production_compose
    assert "POSTGRES_DB: ${POSTGRES_DB:?POSTGRES_DB is required}" in production_compose
    assert "POSTGRES_USER: ${POSTGRES_USER:?POSTGRES_USER is required}" in production_compose
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}" in production_compose
    assert "POSTGRES_HOST: postgres" in production_compose
    assert "POSTGRES_PORT: 5432" in production_compose


def test_validate_production_caddy_domain_accepts_public_hostname() -> None:
    assert validate_production_caddy_domain("payments.example.test") == "payments.example.test"


@pytest.mark.parametrize(
    "value, message",
    [
        ("", "CADDY_DOMAIN is required"),
        ("https://payments.example.test", "CADDY_DOMAIN must not include a URL scheme"),
        ("localhost", "CADDY_DOMAIN must not use a loopback host in production"),
        ("127.0.0.1", "CADDY_DOMAIN must not use a loopback host in production"),
        ("[::1]", "CADDY_DOMAIN must not use a loopback host in production"),
        ("payments.example.test:443", "CADDY_DOMAIN must be a bare public hostname"),
        ("payments.example.test/path", "CADDY_DOMAIN must be a bare public hostname"),
    ],
)
def test_validate_production_caddy_domain_rejects_invalid_hostnames(value: str, message: str) -> None:
    with pytest.raises(repo.HarnessError, match=message):
        validate_production_caddy_domain(value)


def test_validate_production_deployment_environment_requires_public_caddy_domain() -> None:
    with pytest.raises(repo.HarnessError, match="CADDY_DOMAIN must not use a loopback host in production"):
        validate_production_deployment_environment(environ={"CADDY_DOMAIN": "localhost"})


def test_alembic_uses_validated_application_database_url() -> None:
    alembic_env = Path("apps/api/alembic/env.py").read_text(encoding="utf-8")

    assert "from app.core.settings import settings" in alembic_env
    assert 'os.getenv("DATABASE_URL")' not in alembic_env
    assert 'config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))' in alembic_env


def test_direct_api_environment_uses_host_database_url_from_runtime(
    monkeypatch,
) -> None:
    runtime_env = {
        "APP_ENV": "development",
        "APP_PUBLIC_BASE_URL": "http://localhost:39000",
        "CORS_ALLOW_ORIGINS": "http://localhost:39000",
        "DATABASE_URL": "postgresql+psycopg://anytoolai:anytoolai-local-only@postgres:5432/payments_test",
        "POSTGRES_DB": "payments_test",
        "POSTGRES_USER": "anytoolai",
        "POSTGRES_PASSWORD": "anytoolai-local-only",
        "POSTGRES_PORT": "32053",
        "CLOUDPAYMENTS_ENABLED": "false",
    }
    monkeypatch.setattr(repo, "read_dotenv", dict)
    monkeypatch.setattr(repo, "read_runtime_env", lambda: runtime_env)

    environment = direct_api_environment(environ={})

    assert environment["APP_ENV"] == "development"
    assert environment["DATABASE_URL"] == (
        "postgresql+psycopg://anytoolai:anytoolai-local-only@127.0.0.1:32053/payments_test"
    )
    assert environment["SKIP_LEGAL_SEED"] == "true"


def test_direct_api_environment_preserves_process_overrides(
    monkeypatch,
) -> None:
    runtime_env = {
        "APP_ENV": "development",
        "APP_PUBLIC_BASE_URL": "http://localhost:39000",
        "CORS_ALLOW_ORIGINS": "http://localhost:39000",
        "POSTGRES_DB": "payments_test",
        "POSTGRES_USER": "anytoolai",
        "POSTGRES_PASSWORD": "anytoolai-local-only",
        "POSTGRES_PORT": "32053",
        "CLOUDPAYMENTS_ENABLED": "false",
    }
    monkeypatch.setattr(repo, "read_dotenv", lambda: {"LOG_LEVEL": "DEBUG", "DATABASE_URL": "sqlite:///dotenv.db"})
    monkeypatch.setattr(repo, "read_runtime_env", lambda: runtime_env)

    environment = direct_api_environment(
        environ={
            "LOG_LEVEL": "WARNING",
            "DATABASE_URL": "sqlite:///process.db",
        }
    )

    assert environment["LOG_LEVEL"] == "WARNING"
    assert environment["DATABASE_URL"] == "sqlite:///process.db"


def test_direct_api_environment_keeps_host_database_url_over_local_dotenv(
    monkeypatch,
) -> None:
    runtime_env = {
        "APP_ENV": "development",
        "APP_PUBLIC_BASE_URL": "http://localhost:39000",
        "CORS_ALLOW_ORIGINS": "http://localhost:39000",
        "POSTGRES_DB": "payments_test",
        "POSTGRES_USER": "anytoolai",
        "POSTGRES_PASSWORD": "anytoolai-local-only",
        "POSTGRES_PORT": "32053",
        "CLOUDPAYMENTS_ENABLED": "false",
    }
    monkeypatch.setattr(
        repo,
        "read_dotenv",
        lambda: {"DATABASE_URL": "postgresql+psycopg://anytoolai:anytoolai@postgres:5432/anytoolai"},
    )
    monkeypatch.setattr(repo, "read_runtime_env", lambda: runtime_env)

    environment = direct_api_environment(environ={})

    assert environment["DATABASE_URL"] == (
        "postgresql+psycopg://anytoolai:anytoolai-local-only@127.0.0.1:32053/payments_test"
    )


def test_host_database_url_from_runtime_url_encodes_credentials() -> None:
    assert (
        host_database_url_from_runtime(
            {
                "POSTGRES_DB": "payments/test",
                "POSTGRES_USER": "any/tool",
                "POSTGRES_PASSWORD": "secret value",
                "POSTGRES_PORT": "32053",
            }
        )
        == "postgresql+psycopg://any%2Ftool:secret%20value@127.0.0.1:32053/payments%2Ftest"
    )


def test_uv_environment_targets_root_venv_without_activation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(repo, "ROOT", tmp_path)

    environment = uv_environment(
        environ={"PATH": "tools", "VIRTUAL_ENV": "/wrong/.venv"},
        python="/usr/bin/python3.12",
    )

    assert environment["UV_PROJECT_ENVIRONMENT"] == str((tmp_path / ".venv").resolve())
    assert environment["UV_PYTHON"] == "/usr/bin/python3.12"
    assert environment["UV_PYTHON_DOWNLOADS"] == "never"
    assert "VIRTUAL_ENV" not in environment
    assert environment["PATH"] == "tools"


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["test", "api"], "api"),
        (["sync-api"], "sync-api"),
        (["lock-api"], "lock-api"),
        (["check-api-lock"], "check-api-lock"),
        (["migrate-api"], "migrate-api"),
    ],
)
def test_repository_parser_accepts_api_tooling_commands(argv: list[str], expected: str) -> None:
    parsed = build_parser().parse_args(argv)
    assert parsed.command == expected if expected != "api" else parsed.target == expected


def test_test_db_commands_target_only_postgres(monkeypatch) -> None:
    config = repo.RuntimeConfig(
        worktree_id="test",
        compose_project="payments-test",
        database_name="payments_test",
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
    invocations: list[list[str]] = []
    monkeypatch.setattr(repo, "load_runtime", lambda: config)
    monkeypatch.setattr(repo, "write_runtime", lambda _: None)
    monkeypatch.setattr(repo, "compose_command", lambda _: ["docker", "compose"])
    monkeypatch.setattr(repo, "run", lambda command, **_: invocations.append(command))

    repo.cmd_test_db(argparse.Namespace(action="up"))
    repo.cmd_test_db(argparse.Namespace(action="stop"))

    assert invocations == [
        ["docker", "compose", "up", "-d", "--no-deps", "--wait", "postgres"],
        ["docker", "compose", "stop", "postgres"],
    ]


def test_api_test_environment_preserves_explicit_url(monkeypatch) -> None:
    environment = {"TEST_POSTGRES_DATABASE_URL": "postgresql+psycopg://explicit/db_tests"}
    monkeypatch.setattr(repo, "read_runtime_env", lambda: (_ for _ in ()).throw(AssertionError()))

    assert api_test_environment("api-postgres", environment) is environment


def test_api_test_environment_preserves_complete_explicit_postgres_configuration(monkeypatch) -> None:
    environment = {
        "POSTGRES_USER_TEST": "test-user",
        "POSTGRES_PASSWORD_TEST": "test-password",
        "POSTGRES_PORT_TEST": "5432",
        "POSTGRES_DB_TEST": "payments_test",
        "POSTGRES_HOST_TEST": "localhost",
    }
    monkeypatch.setattr(repo, "read_runtime_env", lambda: (_ for _ in ()).throw(AssertionError()))

    assert api_test_environment("api", environment) is environment


def test_api_test_environment_rejects_partial_explicit_postgres_configuration() -> None:
    with pytest.raises(repo.HarnessError, match="Incomplete PostgreSQL test configuration"):
        api_test_environment("api-postgres", {"POSTGRES_USER_TEST": "test-user"})


def test_api_test_environment_derives_worktree_test_database_url(monkeypatch) -> None:
    runtime_env = {
        "POSTGRES_DB": "payments_worktree",
        "POSTGRES_USER": "anytoolai",
        "POSTGRES_PASSWORD": "local-password",
        "POSTGRES_PORT": "32053",
    }
    monkeypatch.setattr(repo, "read_runtime_env", lambda: runtime_env)
    monkeypatch.setattr(repo, "port_is_free", lambda _: False)
    environment: dict[str, str] = {}

    result = api_test_environment("api", environment)

    assert result["TEST_POSTGRES_DATABASE_URL"] == (
        "postgresql+psycopg://anytoolai:local-password@127.0.0.1:32053/payments_worktree_tests"
    )


def test_api_test_environment_ignores_empty_explicit_url(monkeypatch) -> None:
    runtime_env = {
        "POSTGRES_DB": "payments_worktree",
        "POSTGRES_USER": "anytoolai",
        "POSTGRES_PASSWORD": "local-password",
        "POSTGRES_PORT": "32053",
    }
    monkeypatch.setattr(repo, "read_runtime_env", lambda: runtime_env)
    monkeypatch.setattr(repo, "port_is_free", lambda _: False)
    environment = {"TEST_POSTGRES_DATABASE_URL": ""}

    result = api_test_environment("api", environment)

    assert result["TEST_POSTGRES_DATABASE_URL"] != ""
    assert result["TEST_POSTGRES_DATABASE_URL"].endswith("/payments_worktree_tests")


def test_api_fast_test_environment_does_not_require_postgres(monkeypatch) -> None:
    monkeypatch.setattr(repo, "read_runtime_env", lambda: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(repo, "port_is_free", lambda _: (_ for _ in ()).throw(AssertionError()))

    assert api_test_environment("api-fast", {}) == {}


def test_makefile_contains_only_test_database_shortcuts() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    targets = [
        line[:-1]
        for line in makefile.splitlines()
        if line and not line.startswith((" ", "\t", "#")) and line.endswith(":")
    ]

    assert targets == ["test_db_up", "test_db_stop"]


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

    assert len(invocations) == 6
    assert all(environment is check_environment for _, environment in invocations)
    assert any(command[-3:] == ["ruff", "check", "."] for command, _ in invocations)
    assert any(command[-4:] == ["ruff", "format", "--check", "."] for command, _ in invocations)
    assert any("test:components" in command for command, _ in invocations)
    assert any(command[-3:] == ["-m", "not postgres", "apps/api/tests"] for command, _ in invocations)


def test_full_check_runs_explicit_postgres_partition(
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

    postgres_invocations = [
        (command, environment)
        for command, environment in invocations
        if command[-3:] == ["-m", "postgres", "apps/api/tests"]
    ]
    assert postgres_invocations == [
        (
            [
                repo.sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-m",
                "postgres",
                "apps/api/tests",
            ],
            check_environment,
        )
    ]


def test_api_coverage_writes_xml_to_stable_harness_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    check_environment = {"TEMP": "worktree-temp"}
    invocations: list[tuple[list[str], dict[str, str] | None]] = []

    monkeypatch.setattr(repo, "ROOT", tmp_path)
    monkeypatch.setattr(repo, "canonical_check_environment", lambda: check_environment)
    monkeypatch.setattr(
        repo,
        "run",
        lambda command, **kwargs: invocations.append((command, kwargs.get("env"))),
    )

    repo.cmd_coverage(argparse.Namespace(target="api-fast"))

    coverage_xml = tmp_path / ".harness" / "coverage" / "api" / "coverage.xml"
    assert coverage_xml.parent.is_dir()
    assert invocations == [
        (
            [
                repo.sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-m",
                "not postgres",
                "--cov=apps/api/app",
                "--cov-report=term-missing",
                f"--cov-report=xml:{coverage_xml}",
                "apps/api/tests",
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
    monkeypatch.setattr(repo, "read_dotenv", dict)
    monkeypatch.delenv("CLOUDPAYMENTS_API_SECRET", raising=False)

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
    assert "APP_ENV=development" in runtime_env.read_text(encoding="utf-8")
    assert "CLOUDPAYMENTS_API_SECRET=test-cloudpayments-signing-key" in (runtime_env.read_text(encoding="utf-8"))


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
    monkeypatch.setattr(repo, "read_dotenv", dict)
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
        "super-secret" not in path.read_text(encoding="utf-8") for path in harness_dir.iterdir() if path.is_file()
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
