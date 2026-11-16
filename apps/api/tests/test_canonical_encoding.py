from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from scripts.repo import canonical_check_environment


def test_canonical_checks_read_utf8_sources_under_legacy_host_locale(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text(chr(0x2713), encoding="utf-8")
    environment = canonical_check_environment(
        root=tmp_path,
        environ={**os.environ, "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0", "LC_ALL": "C"},
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from pathlib import Path; assert Path(sys.argv[1]).read_text() == chr(0x2713)",
            str(source),
        ],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
