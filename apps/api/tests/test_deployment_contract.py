from __future__ import annotations

from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]


def load_compose(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


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


@pytest.mark.parametrize(
    "path",
    ["deploy/caddy/Caddyfile.dev", "deploy/caddy/Caddyfile.prod"],
)
def test_caddy_proxies_canonical_health_routes(path: str) -> None:
    caddyfile = (ROOT / path).read_text(encoding="utf-8")

    assert "reverse_proxy /api/*" in caddyfile
