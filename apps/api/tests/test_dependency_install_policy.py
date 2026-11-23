"""Offline uv wheel-only enforcement using harmless, task-local distributions."""

import argparse
import io
import subprocess
import sys
import tarfile
import zipfile
from functools import partial
from pathlib import Path

import pytest

from scripts import repo

METADATA = "Metadata-Version: 2.1\nName: policy-fixture\nVersion: 1.0\n"


def test_uv_rejects_source_build_and_installs_wheel(tmp_path: Path) -> None:
    marker = tmp_path / "backend-ran"
    source = tmp_path / "policy_fixture-1.0.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        files = {
            "PKG-INFO": METADATA,
            "pyproject.toml": ('[build-system]\nrequires = []\nbuild-backend = "backend"\nbackend-path = ["."]\n'),
            "backend.py": (
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).touch()\n"
                "raise RuntimeError('synthetic source backend reached')\n"
            ),
        }
        for name, content in files.items():
            data = content.encode()
            entry = tarfile.TarInfo(f"policy_fixture-1.0/{name}")
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))

    wheel = tmp_path / "policy_fixture-1.0-py3-none-any.whl"
    info = "policy_fixture-1.0.dist-info"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"{info}/METADATA", METADATA)
        archive.writestr(f"{info}/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        archive.writestr(f"{info}/RECORD", f"{info}/METADATA,,\n{info}/WHEEL,,\n{info}/RECORD,,\n")

    venv = tmp_path / "venv"
    uv = ["uv", "--no-config", "--offline", "--cache-dir", str(tmp_path / "cache")]
    subprocess.run([*uv, "venv", "--python", sys.executable, str(venv)], check=True)
    command = [*uv, "pip", "install", "--no-index", "--python", str(venv)]
    control = subprocess.run([*command, str(source)], text=True, capture_output=True, check=False)
    assert control.returncode != 0
    assert marker.exists(), control.stderr
    marker.unlink()

    rejected = subprocess.run([*command, "--no-build", str(source)], text=True, capture_output=True, check=False)
    assert rejected.returncode != 0
    assert "Building source distributions for `policy-fixture` is disabled" in rejected.stderr
    assert not marker.exists()

    subprocess.run([*command, "--no-build", str(wheel)], check=True)
    subprocess.run([*uv, "pip", "show", "--python", str(venv), "policy-fixture"], check=True)


def test_api_lock_check_rejects_stale_source_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pyproject = tmp_path / "pyproject.toml"
    project = '[project]\nname = "lock-check-fixture"\nversion = "1.0.0"\nrequires-python = ">=3.12,<3.13"\n'
    pyproject.write_text(project + "dependencies = []\n", encoding="utf-8")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("UV_NO_CONFIG", "1")
    monkeypatch.setattr(repo, "API_DIR", tmp_path)
    monkeypatch.setattr(repo, "run", partial(repo.run, capture=True))
    repo.run(repo.api_uv_command("lock", "--no-build"), env=repo.uv_environment())
    original_lock = (tmp_path / "uv.lock").read_bytes()
    repo.cmd_check_api_lock(argparse.Namespace())

    # This inert archive has neither static metadata nor an executable backend.
    source = tmp_path / "lock_policy_fixture-1.0.tar.gz"
    build_system = b'[build-system]\nrequires = []\nbuild-backend = "unavailable_fixture_backend"\n'
    with tarfile.open(source, "w:gz") as archive:
        entry = tarfile.TarInfo("lock_policy_fixture-1.0/pyproject.toml")
        entry.size = len(build_system)
        archive.addfile(entry, io.BytesIO(build_system))
    pyproject.write_text(
        project
        + 'dependencies = ["lock-policy-fixture"]\n'
        + '\n[tool.uv.sources]\nlock-policy-fixture = { path = "lock_policy_fixture-1.0.tar.gz" }\n',
        encoding="utf-8",
    )

    with pytest.raises(subprocess.CalledProcessError) as rejected:
        repo.cmd_check_api_lock(argparse.Namespace())

    assert "Building source distributions for `lock-policy-fixture` is disabled" in rejected.value.stderr
    assert (tmp_path / "uv.lock").read_bytes() == original_lock
