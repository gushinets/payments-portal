from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import image_deploy

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Linux image installation commands")


@pytest.fixture
def selection(tmp_path: Path) -> argparse.Namespace:
    tmp_path.chmod(0o700)
    return argparse.Namespace(
        env_file=tmp_path / "images.env",
        project="any766-disposable",
        lock_file=tmp_path / "deploy.lock",
        frontend_only=False,
    )


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
    assert 'if [ "$PUBLISH" = true ]' in script
