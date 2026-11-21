from __future__ import annotations

import socket
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import repo


ROOT = Path(__file__).resolve().parents[3]


def test_browser_reserves_ports_before_network_and_retains_failure_diagnostics() -> None:
    steps = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]["browser"]["steps"]
    commands = [step.get("run", "") for step in steps]
    reserve = commands.index("python -m scripts.ci_browser_ports reserve")
    assert reserve < commands.index("uv sync --directory apps/api --locked --no-dev --python 3.12")
    assert reserve < commands.index("npm run test:e2e:react-runtime")
    assert "python scripts/repo.py up" in commands
    diagnostics = next(step for step in steps if step.get("run") == "python -m scripts.ci_browser_ports diagnose")
    assert diagnostics["if"] == "failure() || cancelled()"
    upload = next(step for step in steps if step.get("name") == "Upload browser port diagnostics")
    assert upload["if"] == "always()"
    assert upload["with"]["path"] == ".harness/browser-ports/"


def test_reservation_preserves_existing_ranges_and_all_runtime_ports() -> None:
    from scripts import ci_browser_ports

    ports = tuple(repo.runtime_ports(repo.runtime_config()))
    existing = "1000-1002,65000"
    merged = ci_browser_ports.merge_reservations(existing, ports)
    actual = ci_browser_ports.parse_reservations(merged)
    assert {1000, 1001, 1002, 65000, *ports} <= actual
    assert actual == {1000, 1001, 1002, 65000, *ports}


def test_sysctl_argument_is_serialized_from_validated_integers() -> None:
    from scripts import ci_browser_ports

    assert ci_browser_ports.merge_reservations(" +01000-01002, 65000 ", (38400,)) == ("1000-1002,38400,65000")


@pytest.mark.parametrize("value", ["bad", "10-1", "65536", "1-2-3", "1000 --help"])
def test_reservation_rejects_invalid_kernel_values(value: str) -> None:
    from scripts import ci_browser_ports

    with pytest.raises(ValueError):
        ci_browser_ports.parse_reservations(value)


def test_probe_records_actual_bind_errno_for_a_live_collision() -> None:
    from scripts import ci_browser_ports

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        probe = ci_browser_ports.probe_ports([port])[0]
        assert probe.port == port
        assert probe.errno is not None
        assert probe.error


def test_harness_reports_original_bind_failure(capsys: pytest.CaptureFixture[str]) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert not repo.port_is_free(port)
    error = capsys.readouterr().err
    assert f"Port {port} bind failed" in error
    assert "errno=" in error


def test_reservation_cannot_mutate_a_non_ci_host(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import ci_browser_ports

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(RuntimeError, match="disposable GitHub Actions Linux runner"):
        ci_browser_ports.reserve_ports([38400])


@pytest.mark.parametrize("kernel_applies_update", [True, False])
def test_reservation_verifies_kernel_readback_without_losing_existing_ranges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kernel_applies_update: bool
) -> None:
    from scripts import ci_browser_ports as ports

    reserved = tmp_path / "reserved"
    reserved.write_text("1000-1002")
    monkeypatch.setattr(ports, "RESERVED_PORTS", reserved)
    monkeypatch.setattr(ports.platform, "system", lambda: "Linux")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    def run_sysctl(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert argv[:4] == ["sudo", "-n", "sysctl", "-w"]
        assert kwargs["check"] is True
        value = argv[4].split("=", 1)[1]
        assert {1000, 1001, 1002, 38400} <= ports.parse_reservations(value)
        if kernel_applies_update:
            reserved.write_text(value)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(ports.subprocess, "run", run_sysctl)
    monkeypatch.setattr(ports, "probe_ports", lambda _: [])
    if kernel_applies_update:
        ports.reserve_ports([38400])
    else:
        with pytest.raises(RuntimeError, match="did not retain"):
            ports.reserve_ports([38400])


def test_reserved_port_wait_has_a_deadline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import ci_browser_ports as ports

    reserved = tmp_path / "reserved"
    reserved.write_text("38400")
    monkeypatch.setattr(ports, "RESERVED_PORTS", reserved)
    monkeypatch.setattr(ports.platform, "system", lambda: "Linux")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(ports.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(ports, "probe_ports", lambda _: [ports.PortProbe(38400, 98, "busy")])
    ticks = iter([0, ports.RELEASE_TIMEOUT_SECONDS + 1])
    monkeypatch.setattr(ports.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(ports.time, "sleep", lambda _: pytest.fail("Deadline already exceeded"))
    with pytest.raises(RuntimeError, match="remain occupied"):
        ports.reserve_ports([38400])


def test_diagnostics_capture_socket_state_and_bind_error_without_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from scripts import ci_browser_ports as ports

    reserved, ephemeral = tmp_path / "reserved", tmp_path / "range"
    reserved.write_text("38400")
    ephemeral.write_text("32768 60999")
    monkeypatch.setattr(ports, "RESERVED_PORTS", reserved)
    monkeypatch.setattr(ports, "EPHEMERAL_RANGE", ephemeral)
    monkeypatch.setattr(ports, "DIAGNOSTICS", tmp_path / "diagnostics")
    monkeypatch.setenv("SECRET_CANARY", "must-not-appear-in-port-report")
    monkeypatch.setattr(ports, "probe_ports", lambda _: [ports.PortProbe(38400, 98, "busy")])

    def read_sockets(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert argv == ["sudo", "-n", "ss", "-H", "-tanp", "( sport = :38400 )"]
        return subprocess.CompletedProcess(argv, 0, "TIME-WAIT 127.0.0.1:38400", "")

    monkeypatch.setattr(ports.subprocess, "run", read_sockets)
    ports.write_snapshot("failure", [38400])
    text = (ports.DIAGNOSTICS / "failure.json").read_text()
    report = json.loads(text)
    assert report["probes"] == [{"port": 38400, "errno": 98, "error": "busy"}]
    assert "TIME-WAIT" in report["socket_rows"]
    assert "SECRET_CANARY" not in text
    assert "must-not-appear-in-port-report" not in text
