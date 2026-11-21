"""Offline uv wheel-only enforcement using harmless, task-local distributions."""

import io
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

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
