import os
from pathlib import Path

import pytest

from apps.api.tests.support.filesystem import assert_private_path
from scripts import repo


@pytest.mark.parametrize("directory", [False, True], ids=["file", "directory"])
def test_private_path_assertion_checks_real_platform_permissions(tmp_path: Path, directory: bool) -> None:
    path = tmp_path / "private"
    if directory:
        path.mkdir()
    else:
        path.write_text("synthetic data")
    if os.name != "nt":
        path.chmod(0o755 if directory else 0o644)
    with pytest.raises(AssertionError):
        assert_private_path(path)
    if directory:
        repo.protect_private_directory(path)
    else:
        repo.protect_runtime_env_file(path)
    assert_private_path(path)


def test_private_acl_runner_preserves_native_bytes_without_logging(capsys: pytest.CaptureFixture[str]) -> None:
    import sys

    result = repo.run_private_acl([sys.executable, "-c", "import sys; sys.stdout.buffer.write(bytes([255]))"])
    assert result.returncode == 0
    assert result.stdout == bytes([255])
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
