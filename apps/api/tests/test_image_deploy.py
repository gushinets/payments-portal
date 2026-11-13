from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import image_deploy, repo

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Linux image installation commands")


@pytest.fixture
def selection(tmp_path: Path) -> argparse.Namespace:
    tmp_path.chmod(0o700)
    return argparse.Namespace(
        env_file=tmp_path / "images.env",
        project="any766-disposable",
        lock_file=tmp_path / "deploy.lock",
        frontend_only=False,
        network_overlay=None,
    )


@pytest.fixture
def real_compose_config(
    monkeypatch: pytest.MonkeyPatch, selection: argparse.Namespace
) -> tuple[list[list[str]], list[str]]:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose is required for configuration-only regressions")
    selection.env_file.write_text(
        "INSTANCE_TENANT_ID=anytoolai\nINSTANCE_REGION=ru\n"
        "POSTGRES_DB=synthetic\nPOSTGRES_USER=synthetic\nPOSTGRES_PASSWORD=synthetic\n"
        "CORS_ALLOW_ORIGINS=http://portal.invalid\nAPP_PUBLIC_BASE_URL=http://portal.invalid\n"
        "NEXT_PUBLIC_API_BASE_URL=http://portal.invalid/api\nCADDY_DOMAIN=portal.invalid\n"
        "PORTAL_API_IMAGE=portal-api:reviewed\nPORTAL_WEB_IMAGE=portal-web:reviewed\n"
    )
    run_config = subprocess.run
    calls: list[list[str]] = []
    configs: list[str] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if "config" in command:
            result = run_config(
                command,
                env={"PATH": os.environ["PATH"], "DOCKER_HOST": "unix:///nonexistent/any766.sock"},
                **kwargs,
            )
            configs.append(result.stdout)
            return result
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(image_deploy.subprocess, "run", run)
    return calls, configs


@pytest.mark.parametrize("frontend_only", [False, True])
@pytest.mark.parametrize("shared_edge", [False, True])
def test_image_update_keeps_selected_networks(
    monkeypatch: pytest.MonkeyPatch,
    selection: argparse.Namespace,
    real_compose_config: tuple[list[list[str]], list[str]],
    frontend_only: bool,
    shared_edge: bool,
) -> None:
    monkeypatch.chdir(selection.env_file.parent)
    selection.frontend_only = frontend_only
    files = [str(image_deploy.ROOT / "docker-compose.prod.yml")]
    if shared_edge:
        selection.network_overlay = Path("operator network.yml")
        selection.network_overlay.write_text(
            "services:\n"
            "  api:\n    networks:\n      edge:\n        aliases: [review-api]\n"
            "  web:\n    networks:\n      edge:\n        aliases: [review-web]\n"
            "networks:\n  edge:\n    external: true\n    name: review-edge\n"
        )
        files.append(str(selection.network_overlay.resolve()))
    files.append(str(image_deploy.ROOT / "deploy/compose.images.yml"))
    image_deploy.deploy(selection)
    calls, configs = real_compose_config
    model = json.loads(configs[0])
    assert model["networks"]["edge"].get("external", False) is shared_edge
    assert model["networks"]["edge"]["name"] == ("review-edge" if shared_edge else "any766-disposable_edge")
    for service in ("api", "web"):
        assert model["services"][service]["networks"]["edge"] == (
            {"aliases": [f"review-{service}"]} if shared_edge else None
        )
        assert "build" not in model["services"][service]
        assert model["services"][service]["pull_policy"] == "never"
    for service in ("postgres", "migrate"):
        assert set(model["services"][service]["networks"]) == {"backend"}
    assert not model["networks"]["backend"].get("external", False)
    assert [calls[0][i + 1] for i, value in enumerate(calls[0]) if value == "-f"] == files
    assert all(call[: len(calls[0]) - 3] == calls[0][:-3] for call in calls[1:])
    assert [call[-1] for call in calls[1:]] == (
        ["web"] if frontend_only else ["api", "postgres", "migrate", "api", "web"]
    )


@pytest.mark.parametrize("contents", [None, "services: [invalid]"])
def test_invalid_network_overlay_stops_before_service_changes(
    selection: argparse.Namespace,
    real_compose_config: tuple[list[list[str]], list[str]],
    contents: str | None,
) -> None:
    selection.network_overlay = selection.env_file.parent / "invalid.yml"
    if contents is not None:
        selection.network_overlay.write_text(contents)
    with pytest.raises(subprocess.CalledProcessError):
        image_deploy.deploy(selection)
    calls, _ = real_compose_config
    assert len(calls) == 1
    assert calls[0][-3:] == ["config", "--format", "json"]


def test_image_up_parser_accepts_optional_network_overlay() -> None:
    parser = repo.build_parser()
    command = ["image-up", "--env-file", "images.env", "--project", "review", "--lock-file", "/private/lock"]
    assert parser.parse_args(command).network_overlay is None
    assert parser.parse_args([*command, "--network-overlay", "operator.yml"]).network_overlay == Path("operator.yml")


def fake_compose(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_migration: bool = False,
    api_ref: str = "portal-api:reviewed",
) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if "config" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    {
                        "services": {
                            "api": {"image": api_ref},
                            "web": {"image": "portal-web:reviewed"},
                        }
                    }
                ),
            )
        if fail_migration and command[-1] == "migrate":
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(image_deploy.subprocess, "run", run)
    return calls


def test_migration_failure_leaves_admission_closed(
    monkeypatch: pytest.MonkeyPatch, selection: argparse.Namespace
) -> None:
    calls = fake_compose(monkeypatch, fail_migration=True)
    with pytest.raises(subprocess.CalledProcessError):
        image_deploy.deploy(selection)
    assert calls[1][-2:] == ["stop", "api"]
    assert calls[-1][-4:] == ["run", "--rm", "--no-deps", "migrate"]
    assert not any("up" in call and call[-1] == "api" for call in calls)
    assert not any("--volumes" in call or "--build" in call for call in calls)


def test_frontend_update_touches_only_web(monkeypatch: pytest.MonkeyPatch, selection: argparse.Namespace) -> None:
    calls = fake_compose(monkeypatch)
    selection.frontend_only = True
    image_deploy.deploy(selection)
    assert len(calls) == 2
    assert calls[-1][-8:] == ["up", "-d", "--no-deps", "--no-build", "--pull", "never", "--wait", "web"]


def test_install_migrates_before_ready_backend(monkeypatch: pytest.MonkeyPatch, selection: argparse.Namespace) -> None:
    calls = fake_compose(monkeypatch)
    image_deploy.deploy(selection)
    assert [call[-1] for call in calls[1:]] == ["api", "postgres", "migrate", "api", "web"]
    assert "--wait" in calls[-2]


@pytest.mark.parametrize("api_ref", ["portal-api", "portal-api:latest"])
def test_unpinned_image_is_refused_before_stopping_api(
    monkeypatch: pytest.MonkeyPatch,
    selection: argparse.Namespace,
    api_ref: str,
) -> None:
    calls = fake_compose(monkeypatch, api_ref=api_ref)
    with pytest.raises(ValueError, match="version tag or digest"):
        image_deploy.deploy(selection)
    assert len(calls) == 1
    assert "config" in calls[0]


def test_concurrent_install_is_refused(monkeypatch: pytest.MonkeyPatch, selection: argparse.Namespace) -> None:
    import fcntl

    calls = fake_compose(monkeypatch)
    with selection.lock_file.open("w") as lock:
        selection.lock_file.chmod(0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            image_deploy.deploy(selection)
    assert calls == []


def test_workflow_components_and_build_origins() -> None:
    workflow = yaml.safe_load((image_deploy.ROOT / ".github/workflows/publish-images.yml").read_text())
    jobs = workflow["jobs"]
    assert "'backend'" in jobs["api"]["if"]
    assert "'frontend'" in jobs["web"]["if"]
    script = jobs["web"]["steps"][-1]["run"]
    assert '--build-arg "APP_PUBLIC_BASE_URL=$APP_PUBLIC_BASE_URL"' in script
    assert '--build-arg "NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL"' in script
    assert '--build-arg "NEXT_PUBLIC_KERNEL_WEB_BASE_URL=$NEXT_PUBLIC_KERNEL_WEB_BASE_URL"' in script
    assert jobs["web"]["steps"][-1]["env"]["NEXT_PUBLIC_KERNEL_WEB_BASE_URL"] == "${{ inputs.kernel_web_base_url }}"
    assert 'if [ "$PUBLISH" = true ]' in script


@pytest.mark.parametrize("filename", ["docker-compose.agent.yml", "docker-compose.prod.yml"])
def test_compose_forwards_kernel_web_build_origin(filename: str) -> None:
    compose = yaml.safe_load((image_deploy.ROOT / filename).read_text())
    assert compose["services"]["web"]["build"]["args"]["NEXT_PUBLIC_KERNEL_WEB_BASE_URL"] == (
        "${NEXT_PUBLIC_KERNEL_WEB_BASE_URL:-}"
    )
    dockerfile = (image_deploy.ROOT / "apps/web/Dockerfile").read_text()
    builder = dockerfile.split("FROM dependencies AS builder", 1)[1].split("FROM node:", 1)[0]
    assert "ARG NEXT_PUBLIC_KERNEL_WEB_BASE_URL" in builder
    assert "ENV NEXT_PUBLIC_KERNEL_WEB_BASE_URL=${NEXT_PUBLIC_KERNEL_WEB_BASE_URL}" in builder
