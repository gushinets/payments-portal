from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]


def load_compose(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
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


@pytest.mark.parametrize(
    "path",
    ["docker-compose.yml", "docker-compose.prod.yml", "docker-compose.agent.yml"],
)
def test_api_healthcheck_uses_canonical_readiness(path: str) -> None:
    api = load_compose(path)["services"]["api"]

    assert "http://localhost:8000/api/health/ready" in " ".join(api["healthcheck"]["test"])


def test_api_image_commands_do_not_run_migrations() -> None:
    dockerfile = (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")
    commands = [line for line in dockerfile.splitlines() if line.startswith("CMD ")]

    assert len(commands) == 2
    assert all("alembic" not in command for command in commands)
    assert all("uvicorn" in command for command in commands)


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
        "COMMAND_LOG": str(command_log),
        "COMPOSE_PROJECT_NAME": "payment-portal-ci-test",
        "CURL_LOG": str(curl_log),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", smoke_script],
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
