from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def run_shell(script: str, directory: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [shutil.which("bash") or "bash", "--noprofile", "--norc", "-ec", script],
        cwd=directory,
        env={**os.environ, "PYTHON_EXECUTABLE": Path(sys.executable).as_posix()},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


@pytest.mark.parametrize("tcp_ready", [True, False])
def test_image_verifier_waits_for_tcp_before_alembic(tmp_path: Path, tcp_ready: bool) -> None:
    verifier = (ROOT / "security/trivy/verify-api-postgres.sh").as_posix()
    stubs = r"""
python3() { "$PYTHON_EXECUTABLE" "$@"; }
sleep() { :; }
docker() {
  printf '%s\n' "$*" >> commands.log
  case "$1 $2" in
    "network create") echo network; return 0 ;;
    "network rm"|"rm --force") return 0 ;;
    "image inspect") echo sha256:fixture; return 0 ;;
    "run --detach") echo container; return 0 ;;
    "run --rm")
      test -e tcp-ready || { echo "migration before TCP readiness" >&2; return 1; }
      return 0 ;;
    "exec container")
      shift 2
      if test "$1" = pg_isready; then
        case " $* " in
          *" -h 127.0.0.1 "*)
            if test "$TCP_READY" = false; then return 1; fi
            if test ! -e tcp-attempt; then touch tcp-attempt; return 1; fi
            touch tcp-ready; return 0 ;;
          *) return 0 ;; # The initialization Unix socket is already accepting.
        esac
      fi
      if test "$1" = id; then echo 999; fi
      return 0 ;;
  esac
  return 1
}
"""
    script = f"TCP_READY={str(tcp_ready).lower()}\n" + stubs + f'\nsource "{verifier}" image:fixture'
    result = run_shell(script, tmp_path)
    commands = (tmp_path / "commands.log").read_text(encoding="utf-8").splitlines()
    migrations = [line for line in commands if line.startswith("run --rm")]
    if tcp_ready:
        assert result.returncode == 0, result.stderr
        assert len(migrations) == 3
        probes = [line for line in commands if "pg_isready" in line]
        assert len(probes) == 2
        assert all("-h 127.0.0.1" in line for line in probes)
    else:
        assert result.returncode != 0
        assert "Disposable PostgreSQL did not become ready" in result.stderr
        assert not migrations


def test_cached_base_reinstall_uses_versions_from_current_index(tmp_path: Path) -> None:
    dockerfile = (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")
    production = dockerfile.split("FROM base AS production\n", 1)[1]
    layer = production.split("RUN ", 1)[1].split("\n\n", 1)[0].replace("\\\n", "")
    transaction = layer[layer.index("apt-get update") : layer.index("&& test ! -e /usr/bin/infocmp")]
    stubs = r"""
apt-get() {
  printf '%s\n' "$*" >> commands.log
  case "$1" in
    update) touch refreshed-index ;;
    upgrade) test -e refreshed-index; touch upgraded ;;
    install)
      test -e refreshed-index
      test -e upgraded || { echo "installed version no longer in index" >&2; return 1; }
      case " $* " in *" ncurses-bin=2 util-linux=2 "*) : ;; *) return 1 ;; esac ;;
    *) return 1 ;;
  esac
}
dpkg-query() {
  if test -e upgraded; then printf 2; else printf 1; fi
}
"""
    result = run_shell(stubs + "\n" + transaction, tmp_path)
    assert result.returncode == 0, result.stderr
    commands = (tmp_path / "commands.log").read_text(encoding="utf-8").splitlines()
    assert [line.split()[0] for line in commands] == ["update", "upgrade", "install"]
