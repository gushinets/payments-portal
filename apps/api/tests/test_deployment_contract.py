from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]


def load_compose(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def load_env_example(path: str) -> dict[str, str]:
    entries = {}
    for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            key, separator, value = line.partition("=")
            if separator:
                entries[key] = value
    return entries


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(0o755)


@pytest.mark.parametrize("path", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_migration_service_gates_api_startup(path: str) -> None:
    services = load_compose(path)["services"]
    migrate = services["migrate"]
    api = services["api"]

    assert migrate["restart"] == "no"
    assert migrate["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert migrate["command"] == [
        "python",
        "-m",
        "alembic",
        "-c",
        "apps/api/alembic.ini",
        "upgrade",
        "head",
    ]
    assert migrate["environment"] == api["environment"]
    assert api["depends_on"]["migrate"]["condition"] == "service_completed_successfully"


@pytest.mark.parametrize("path", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_postgres_healthcheck_requires_tcp_before_migration(path: str) -> None:
    check = load_compose(path)["services"]["postgres"]["healthcheck"]["test"]
    assert check[0] == "CMD-SHELL"
    command = shlex.split(check[1])
    # The image's temporary initialization server accepts Unix sockets before TCP.
    assert command[0] == "pg_isready"
    assert "-h" in command
    assert command[command.index("-h") + 1] == "127.0.0.1"


def test_production_sentry_configuration_is_optional_and_minimal() -> None:
    expected_keys = {"SENTRY_DSN", "SENTRY_RELEASE"}
    example = load_env_example(".env.production.example")
    services = load_compose("docker-compose.prod.yml")["services"]
    api_environment = services["api"]["environment"]

    assert {key for key in example if key.startswith("SENTRY_")} == expected_keys
    assert example["SENTRY_DSN"] == ""
    assert example["SENTRY_RELEASE"] == ""
    assert {key for key in api_environment if key.startswith("SENTRY_")} == expected_keys
    assert api_environment["SENTRY_DSN"] == "${SENTRY_DSN:-}"
    assert api_environment["SENTRY_RELEASE"] == "${SENTRY_RELEASE:-}"
    assert services["migrate"]["environment"] == api_environment


def test_instance_scope_is_explicit_in_managed_environments() -> None:
    local_example = load_env_example(".env.example")
    production_example = load_env_example(".env.production.example")
    production_example_text = (ROOT / ".env.production.example").read_text(encoding="utf-8")
    deployment_document = (ROOT / "docs/architecture/deployment.md").read_text(encoding="utf-8")
    local_api_environment = load_compose("docker-compose.yml")["services"]["api"]["environment"]
    agent_api_environment = load_compose("docker-compose.agent.yml")["services"]["api"]["environment"]
    production_api_environment = load_compose("docker-compose.prod.yml")["services"]["api"]["environment"]
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert local_example["INSTANCE_TENANT_ID"] == "anytoolai"
    assert local_example["INSTANCE_REGION"] == "ru"
    assert production_example["INSTANCE_TENANT_ID"] == ""
    assert production_example["INSTANCE_REGION"] == ""
    assert local_api_environment["INSTANCE_TENANT_ID"] == "${INSTANCE_TENANT_ID:-anytoolai}"
    assert local_api_environment["INSTANCE_REGION"] == "${INSTANCE_REGION:-ru}"
    assert agent_api_environment["INSTANCE_TENANT_ID"] == "${INSTANCE_TENANT_ID}"
    assert agent_api_environment["INSTANCE_REGION"] == "${INSTANCE_REGION}"
    assert production_api_environment["INSTANCE_TENANT_ID"] == ("${INSTANCE_TENANT_ID:?INSTANCE_TENANT_ID is required}")
    assert production_api_environment["INSTANCE_REGION"] == ("${INSTANCE_REGION:?INSTANCE_REGION is required}")
    assert "INSTANCE_TENANT_ID: anytoolai" in workflow
    assert "INSTANCE_REGION: ru" in workflow
    assert 'echo "INSTANCE_TENANT_ID=$INSTANCE_TENANT_ID"' in workflow
    assert 'echo "INSTANCE_REGION=$INSTANCE_REGION"' in workflow
    assert "supports exactly this deployed scope" in production_example_text
    assert "support exactly `anytoolai` / `ru`" in deployment_document
    assert "fail before successful startup or" in deployment_document


@pytest.mark.parametrize(
    "path",
    ["docker-compose.yml", "docker-compose.prod.yml", "docker-compose.agent.yml"],
)
def test_api_healthcheck_uses_canonical_readiness(path: str) -> None:
    api = load_compose(path)["services"]["api"]

    assert "http://localhost:8000/api/health/ready" in " ".join(api["healthcheck"]["test"])


def test_api_image_commands_do_not_run_migrations() -> None:
    dockerfile = (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")
    commands = [json.loads(line.removeprefix("CMD ")) for line in dockerfile.splitlines() if line.startswith("CMD ")]

    assert len(commands) == 2
    for command in commands:
        assert command[:2] == ["sh", "-c"]
        launch = command[2]
        assert "alembic" not in launch
        assert "python -m uvicorn app.main:app" in launch
        assert "--no-access-log" in launch.split(" && exec ", 1)[1].split()


def test_production_runtime_verification_supplies_scope_and_disables_access_logging() -> None:
    script = (ROOT / "security/trivy/verify-api-runtime.sh").read_text(encoding="utf-8")

    assert "--env INSTANCE_TENANT_ID=anytoolai" in script
    assert "--env INSTANCE_REGION=ru" in script
    assert "python -m uvicorn app.main:app" in script
    assert "--no-access-log" in script


def test_dev_api_command_disables_access_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import repo

    invocations: list[list[str]] = []
    controlled_environment = {"APP_ENV": "development", "DATABASE_URL": "sqlite://"}
    monkeypatch.setattr(repo, "direct_api_environment", lambda: controlled_environment)
    monkeypatch.setattr(repo, "run", lambda command, **_: invocations.append(command))

    repo.cmd_dev_api(None)

    assert invocations == [
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--reload",
            "--no-access-log",
            "--app-dir",
            "apps/api",
        ]
    ]


def test_dockerignore_excludes_nested_virtualenvs() -> None:
    patterns = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert "**/.venv" in patterns


def test_quality_job_collects_coverage_without_repeating_suites() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["quality"]["steps"]
    checks = [step for step in steps if "check:fast" in step.get("run", "")]
    assert len(checks) == 1
    assert checks[0]["run"] == "npm run check:fast -- --coverage"
    assert "continue-on-error" not in checks[0]
    assert not any("coverage api" in step.get("run", "") for step in steps)
    assert not any("test:components" in step.get("run", "") for step in steps)
    for name, path in (
        ("api-coverage", ".harness/coverage/api/"),
        ("frontend-component-coverage", ".harness/coverage/web-components/"),
    ):
        upload = next(step for step in steps if step.get("with", {}).get("path") == path)
        assert steps.index(upload) > steps.index(checks[0])
        assert upload["if"] == "always()"
        assert upload["with"]["name"] == name + "-${{ github.run_id }}-${{ github.run_attempt }}"
        assert upload["with"]["if-no-files-found"] == "warn"
        assert upload["with"]["retention-days"] == 7
        assert upload["with"]["include-hidden-files"] is True


def test_ci_postgres_uses_ram_and_retains_parallel_runner_diagnostics() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    gate = workflow["jobs"]["production-gate"]
    options = gate["services"]["postgres"]["options"]
    assert "--tmpfs /var/lib/postgresql:rw,size=2g" in options
    assert "--health-cmd" in options
    postgres_step = next(
        step for step in gate["steps"] if step.get("name") == "Run PostgreSQL tests and migration cycles"
    )
    assert "exec python scripts/repo.py test api-postgres --workers 4" in postgres_step["run"]
    assert '--junitxml="$CI_ARTIFACTS/postgres-junit.xml"' in postgres_step["run"]
    assert '> "$CI_ARTIFACTS/postgres-pytest.log" 2>&1' in postgres_step["run"]
    assert "--cov" not in postgres_step["run"]
    assert "continue-on-error" not in postgres_step
    report = next(step for step in gate["steps"] if step.get("name") == "Upload PostgreSQL test results")
    assert gate["steps"].index(report) == gate["steps"].index(postgres_step) + 1
    assert report.get("if", "success()") == "success()"
    assert report["uses"].startswith("actions/upload-artifact@")
    assert report["with"]["path"] == "${{ env.CI_ARTIFACTS }}/postgres-junit.xml"
    assert report["with"]["include-hidden-files"] is True
    assert report["with"]["if-no-files-found"] == "error"
    diagnostics = next(step for step in gate["steps"] if step.get("name") == "Upload failure diagnostics")
    assert diagnostics["if"] == "failure() || cancelled()"
    assert diagnostics["with"]["include-hidden-files"] is True
    assert set(diagnostics["with"]["path"].splitlines()) == {".harness/ci/", ".harness/api-tests/"}


def test_browser_evidence_upload_persists_only_playwright_artifacts() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["browser"]["steps"]
    validator = next(step for step in steps if step.get("name") == "Validate browser evidence")
    upload = next(step for step in steps if step.get("name") == "Upload browser evidence")
    inputs = upload["with"]

    assert validator["if"] == "always()"
    assert upload["if"] == "always()"
    assert inputs["include-hidden-files"] is True
    assert inputs["if-no-files-found"] == "error"
    assert set(inputs["path"].splitlines()) == {
        ".harness/playwright-react-runtime-results/",
        ".harness/playwright-react-runtime-report/",
        ".harness/playwright-results/",
        ".harness/playwright-report/",
    }


def browser_evidence_validator_script() -> str:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["browser"]["steps"]
    return next(step["run"] for step in steps if step.get("name") == "Validate browser evidence")


def write_browser_evidence_fixture(root: Path, *, attempt_suffix: str = "") -> None:
    results = root / ".harness/playwright-react-runtime-results"
    for project in ("desktop-chromium", "mobile-chromium"):
        project_results = results / f"react-runtime-{project}{attempt_suffix}"
        project_results.mkdir(parents=True)
        for screenshot in ("landing", "account"):
            (project_results / f"{screenshot}.png").write_bytes(b"png")

    for report in (
        ".harness/playwright-react-runtime-report/results.json",
        ".harness/playwright-react-runtime-report/html/index.html",
        ".harness/playwright-report/results.json",
        ".harness/playwright-report/html/index.html",
    ):
        path = root / report
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("evidence", encoding="utf-8")


def run_browser_evidence_validator(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            shutil.which("bash") or "bash",
            "--noprofile",
            "--norc",
            "-e",
            "-o",
            "pipefail",
            "-c",
            browser_evidence_validator_script(),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_browser_evidence_validator_accepts_current_portal_without_retired_pages(tmp_path: Path) -> None:
    write_browser_evidence_fixture(tmp_path)

    result = run_browser_evidence_validator(tmp_path)

    assert result.returncode == 0, result.stderr


def test_browser_evidence_validator_accepts_complete_retry_evidence(tmp_path: Path) -> None:
    write_browser_evidence_fixture(tmp_path, attempt_suffix="-retry1")

    result = run_browser_evidence_validator(tmp_path)

    assert result.returncode == 0, result.stderr


def test_browser_evidence_validator_accepts_complete_retry_after_incomplete_base(
    tmp_path: Path,
) -> None:
    write_browser_evidence_fixture(tmp_path)
    (tmp_path / ".harness/playwright-react-runtime-results/react-runtime-desktop-chromium/landing.png").unlink()
    write_browser_evidence_fixture(tmp_path, attempt_suffix="-retry1")

    result = run_browser_evidence_validator(tmp_path)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("attempt_suffix", ["-retry-backup", "-retry-backup-retry1"])
def test_browser_evidence_validator_rejects_non_numeric_retry_suffix(tmp_path: Path, attempt_suffix: str) -> None:
    write_browser_evidence_fixture(tmp_path, attempt_suffix=attempt_suffix)

    result = run_browser_evidence_validator(tmp_path)

    assert result.returncode != 0
    assert "inspected 0" in result.stdout


@pytest.mark.parametrize("project", ["desktop-chromium", "mobile-chromium"])
@pytest.mark.parametrize("screenshot", ["landing", "account"])
def test_browser_evidence_validator_rejects_missing_screenshot(tmp_path: Path, project: str, screenshot: str) -> None:
    write_browser_evidence_fixture(tmp_path)
    missing = tmp_path / f".harness/playwright-react-runtime-results/react-runtime-{project}/{screenshot}.png"
    missing.unlink()

    result = run_browser_evidence_validator(tmp_path)

    assert result.returncode != 0
    assert f"{project}/{screenshot}.png" in result.stdout


def test_browser_evidence_validator_rejects_screenshots_split_across_attempts(
    tmp_path: Path,
) -> None:
    write_browser_evidence_fixture(tmp_path)
    (tmp_path / ".harness/playwright-react-runtime-results/react-runtime-desktop-chromium/landing.png").unlink()
    write_browser_evidence_fixture(tmp_path, attempt_suffix="-retry1")
    (tmp_path / ".harness/playwright-react-runtime-results/react-runtime-desktop-chromium-retry1/account.png").unlink()

    result = run_browser_evidence_validator(tmp_path)

    assert result.returncode != 0
    assert "desktop-chromium/landing.png" in result.stdout
    assert "desktop-chromium-retry1/account.png" in result.stdout


@pytest.mark.parametrize("project", ["desktop-chromium", "mobile-chromium"])
@pytest.mark.parametrize("screenshot", ["landing", "account"])
def test_browser_evidence_validator_rejects_empty_screenshot(tmp_path: Path, project: str, screenshot: str) -> None:
    write_browser_evidence_fixture(tmp_path)
    empty = tmp_path / f".harness/playwright-react-runtime-results/react-runtime-{project}/{screenshot}.png"
    empty.write_bytes(b"")

    result = run_browser_evidence_validator(tmp_path)

    assert result.returncode != 0
    assert f"{project}/{screenshot}.png" in result.stdout


@pytest.mark.parametrize(
    "masquerade",
    [
        ".harness/playwright-react-runtime-results/react-runtime-mobile-chromium/account.png",
        ".harness/playwright-report/results.json",
    ],
)
def test_browser_evidence_validator_rejects_directory_masquerading_as_file(tmp_path: Path, masquerade: str) -> None:
    write_browser_evidence_fixture(tmp_path)
    target = tmp_path / masquerade
    target.unlink()
    target.mkdir()

    result = run_browser_evidence_validator(tmp_path)

    assert result.returncode != 0
    assert masquerade in result.stdout


@pytest.mark.parametrize(
    "missing_report",
    [
        ".harness/playwright-react-runtime-report/results.json",
        ".harness/playwright-react-runtime-report/html/index.html",
        ".harness/playwright-report/results.json",
        ".harness/playwright-report/html/index.html",
    ],
)
def test_browser_evidence_validator_rejects_missing_report(tmp_path: Path, missing_report: str) -> None:
    write_browser_evidence_fixture(tmp_path)
    (tmp_path / missing_report).unlink()

    result = run_browser_evidence_validator(tmp_path)

    assert result.returncode != 0
    assert missing_report in result.stdout


def test_production_gate_migrates_database_before_api_smoke(tmp_path: Path) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["production-gate"]["steps"]
    smoke_script = next(step["run"] for step in steps if step.get("name") == "Smoke API image")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command_log = tmp_path / "docker-commands.log"
    curl_log = tmp_path / "curl.log"
    ci_env_file = tmp_path / "ci.env"
    ci_env_file.write_text("", encoding="utf-8")

    write_executable(
        bin_dir / "docker",
        """#!/bin/sh
printf '%s\\n' "$*" >> "$COMMAND_LOG"
case "$1 $2" in
  "image inspect") exit 0 ;;
  "run --rm") exit 0 ;;
  "run --detach") printf '%s\\n' 'container-id'; exit 0 ;;
  "container inspect") printf '%s\\n' 'true'; exit 0 ;;
esac
exit 1
""",
    )
    write_executable(
        bin_dir / "curl",
        """#!/bin/sh
printf '%s\\n' "$*" >> "$CURL_LOG"
printf '%s\\n' '{"status":"ready"}'
""",
    )
    write_executable(bin_dir / "python", "#!/bin/sh\ncat > /dev/null\n")

    environment = {
        **os.environ,
        "CI_ENV_FILE": str(ci_env_file),
        "TEST_BIN_DIR": bin_dir.as_posix(),
        "COMMAND_LOG": str(command_log),
        "COMPOSE_PROJECT_NAME": "payment-portal-ci-test",
        "CURL_LOG": str(curl_log),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }
    result = subprocess.run(
        [
            shutil.which("bash") or "bash",
            "--noprofile",
            "--norc",
            "-e",
            "-o",
            "pipefail",
            "-c",
            'PATH="$(cd "$TEST_BIN_DIR" && pwd):$PATH"\n' + smoke_script,
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    commands = command_log.read_text(encoding="utf-8").splitlines()
    migration_commands = [
        command for command in commands if "python -m alembic -c apps/api/alembic.ini upgrade head" in command
    ]
    api_commands = [command for command in commands if command.startswith("run --detach ")]

    assert len(migration_commands) == 1
    assert len(api_commands) == 1
    assert commands.index(migration_commands[0]) < commands.index(api_commands[0])
    assert "/api/health/ready" in curl_log.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "path",
    ["deploy/caddy/Caddyfile.dev", "deploy/caddy/Caddyfile.prod"],
)
def test_caddy_proxies_canonical_health_routes(path: str) -> None:
    caddyfile = (ROOT / path).read_text(encoding="utf-8")

    assert "reverse_proxy /api/*" in caddyfile


@pytest.mark.parametrize("path", ["deploy/caddy/Caddyfile.dev", "deploy/caddy/Caddyfile.prod"])
def test_caddy_routes_service_api_and_swagger_without_rewriting_paths(path: str) -> None:
    caddyfile = (ROOT / path).read_text(encoding="utf-8")
    matcher = next(
        (line.strip() for line in caddyfile.splitlines() if line.strip().startswith("@portal_service_api path ")), ""
    )
    paths = set(matcher.split()[2:])
    assert {
        "/internal/v1/backend-sessions/exchange",
        "/internal/v1/backend-sessions/introspect",
        "/internal/v1/access-snapshots/*",
        "/internal/v1/allowance-exhaustions",
        "/docs",
        "/docs/*",
        "/openapi.json",
    } <= paths
    assert "reverse_proxy @portal_service_api api:8000" in caddyfile
    assert "handle_path" not in caddyfile
    assert "payments-portal-prod-api-1" not in caddyfile


@pytest.mark.parametrize("path", ["docker-compose.prod.yml", "docker-compose.agent.yml"])
def test_web_receives_only_public_backend_callbacks(path: str) -> None:
    services = load_compose(path)["services"]
    public = services["web"]["environment"]
    assert "BACKEND_CONSUMERS" not in public
    assert "BACKEND_CALLBACKS" in public
    assert "BACKEND_CONSUMERS" not in public["BACKEND_CALLBACKS"]
    assert "BACKEND_CONSUMERS" in services["api"]["environment"]


def test_manual_ai_review_limits_token_permissions_to_each_job() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ai-pr-review.yml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]

    assert workflow.get("permissions") == {}
    assert jobs["comment-gate"]["permissions"] == {"pull-requests": "write", "checks": "write"}
    assert jobs["ai-pr-review"]["permissions"] == {
        "actions": "read",
        "contents": "read",
        "statuses": "read",
        "pull-requests": "write",
        "checks": "write",
    }
    assert jobs["finalize-trigger"]["permissions"] == {"checks": "write"}


def run_production_package_removal(
    tmp_path: Path, blocked_package: str, flags: str, audit_mode: str = "clean"
) -> tuple[subprocess.CompletedProcess[str], Path]:
    dockerfile = (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")
    production = dockerfile.split("FROM base AS production", 1)[1]
    command = "runtime_build_packages=" + production.split("runtime_build_packages=", 1)[1].split("\n\n", 1)[0].replace(
        "\\\n", ""
    )
    marker = tmp_path / "purged.txt"
    environment = {
        **os.environ,
        "BLOCKED_PACKAGE": blocked_package,
        "BLOCKED_FLAGS": flags,
        "PURGE_MARKER": marker.as_posix(),
        "AUDIT_MODE": audit_mode,
    }
    stubs = r"""
groupadd() { :; }
useradd() { :; }
install() { :; }
dpkg-statoverride() { :; }
dpkg-query() {
  for queried_package; do :; done
  if [ "$queried_package" = "$BLOCKED_PACKAGE" ]; then
    if [ "$BLOCKED_FLAGS" = "query-error" ]; then return 1; fi
    printf '%s' "$BLOCKED_FLAGS"
  else
    printf 'no:no'
  fi
}
dpkg() {
  if [ "$1" = "--audit" ]; then
    case "$AUDIT_MODE" in
      error) echo "Cannot read package database" >&2; return 2 ;;
      dirty) echo "incomplete package"; return 0 ;;
    esac
  fi
  if [ "$1" = "--purge" ]; then printf '%s\n' "$@" > "$PURGE_MARKER"; fi
  return 0
}
"""
    result = subprocess.run(
        [shutil.which("bash") or "bash", "--noprofile", "--norc", "-c", stubs + "\n" + command],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, marker


@pytest.mark.parametrize("package", ["apt", "passwd", "libsepol2"])
@pytest.mark.parametrize("flags", ["yes:no", "no:yes", "query-error"])
def test_production_removal_rejects_every_essential_protected_or_unknown_package(
    tmp_path: Path, package: str, flags: str
) -> None:
    result, marker = run_production_package_removal(tmp_path, package, flags)

    assert result.returncode != 0, result.stdout + result.stderr
    assert not marker.exists(), "Package purge ran after a rejected precondition"


def test_production_removal_allows_verified_nonessential_packages(tmp_path: Path) -> None:
    result, marker = run_production_package_removal(tmp_path, "", "no:no")

    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text(encoding="utf-8").splitlines()[0] == "--purge"


@pytest.mark.parametrize("audit_mode", ["error", "dirty"])
def test_production_removal_requires_successful_clean_audit(tmp_path: Path, audit_mode: str) -> None:
    result, marker = run_production_package_removal(tmp_path, "", "no:no", audit_mode)

    assert marker.exists(), "Fixture must reach the post-purge audit"
    assert result.returncode != 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "mode",
    ["find-error", "ldd-error-first", "ldd-error-last", "missing", "privileged", "privilege-traversal-error", "clean"],
)
def test_runtime_native_inspection_requires_successful_complete_commands(tmp_path: Path, mode: str) -> None:
    script = (ROOT / "security/trivy/verify-api-runtime.sh").read_text(encoding="utf-8")
    container_check = script.split("-ec '", 1)[1].split("\n'", 1)[0]
    marker = tmp_path / "imports-reached.txt"
    stubs = r"""
id() { echo 999; }
command() { return 1; }
dpkg-query() {
  if [ "$1" = "-s" ]; then return 1; fi
  echo "util-linux 2.41.5-0+deb13u1"
}
dpkg() { return 0; }
find() {
  case "$*" in
    *-perm*)
      if [ "$NATIVE_MODE" = "privilege-traversal-error" ]; then return 2; fi
      if [ "$NATIVE_MODE" = "privileged" ]; then echo /usr/bin/su; fi
      return 0 ;;
  esac
  if [ "$NATIVE_MODE" = "find-error" ]; then
    echo "Permission denied" >&2; return 1
  fi
  case "$*" in
    *-exec*) ldd /fixture/first.so; ldd /fixture/last.so; return 0 ;;
  esac
  printf '%s\n' /fixture/first.so /fixture/last.so
}
ldd() {
  case "$NATIVE_MODE:$1" in
    ldd-error-first:/fixture/first.so|ldd-error-last:/fixture/last.so)
      echo "Cannot execute dependency inspector" >&2; return 2 ;;
  esac
  if [ "$NATIVE_MODE" = "missing" ]; then echo "libexample.so => not found"; fi
}
python() { echo imports > "$IMPORT_MARKER"; }
"""
    result = subprocess.run(
        [shutil.which("bash") or "bash", "--noprofile", "--norc", "-ec", stubs + container_check],
        env={**os.environ, "NATIVE_MODE": mode, "IMPORT_MARKER": marker.as_posix()},
        text=True,
        capture_output=True,
        check=False,
    )

    if mode == "clean":
        assert result.returncode == 0, result.stdout + result.stderr
        assert marker.exists()
    else:
        assert result.returncode != 0, result.stdout + result.stderr
        assert not marker.exists(), "Imports ran after incomplete native inspection"
