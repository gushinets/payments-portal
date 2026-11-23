"""Reserve harness ports only on a disposable Linux Actions runner."""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from scripts import repo


RESERVED_PORTS = Path("/proc/sys/net/ipv4/ip_local_reserved_ports")
EPHEMERAL_RANGE = Path("/proc/sys/net/ipv4/ip_local_port_range")
DIAGNOSTICS = repo.ROOT / ".harness/browser-ports"
RELEASE_TIMEOUT_SECONDS = 70


@dataclass(frozen=True)
class PortProbe:
    port: int
    errno: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class PortSnapshot:
    captured_at: str
    reserved_ports: str
    ephemeral_range: str
    probes: list[PortProbe]
    socket_exit: int | None
    socket_rows: str
    socket_error: str


def parse_reservations(value: str) -> set[int]:
    ports: set[int] = set()
    if not value.strip():
        return ports
    for entry in value.strip().split(","):
        bounds = entry.split("-")
        if len(bounds) not in {1, 2}:
            raise ValueError("Invalid reserved port range")
        first, last = int(bounds[0]), int(bounds[-1])
        if not 0 <= first <= last <= 65535:
            raise ValueError("Invalid reserved port bounds")
        ports.update(range(first, last + 1))
    return ports


def merge_reservations(value: str, required: tuple[int, ...]) -> str:
    ports = sorted(parse_reservations(value) | set(required))
    ranges: list[str] = []
    if not ports:
        return ""
    first = previous = ports[0]
    for port in ports[1:]:
        if port == previous + 1:
            previous = port
            continue
        ranges.append(str(first) if first == previous else f"{first}-{previous}")
        first = previous = port
    ranges.append(str(first) if first == previous else f"{first}-{previous}")
    # Only integer-derived tokens enter argv; raw file text is never forwarded.
    return ",".join(ranges)


def probe_ports(ports: tuple[int, ...] | list[int]) -> list[PortProbe]:
    probes = []
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError as exc:
                probes.append(PortProbe(port, exc.errno, exc.strerror))
            else:
                probes.append(PortProbe(port))
    return probes


def write_snapshot(stage: str, ports: tuple[int, ...] | list[int]) -> None:
    socket_filter = "( " + " or ".join(f"sport = :{port}" for port in ports) + " )"
    try:
        sockets = subprocess.run(
            ["sudo", "-n", "ss", "-H", "-tanp", socket_filter],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        socket_exit, rows, error = sockets.returncode, sockets.stdout, sockets.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        socket_exit, rows, error = None, "", str(exc)
    snapshot = PortSnapshot(
        captured_at=datetime.now(UTC).isoformat(),
        reserved_ports=RESERVED_PORTS.read_text().strip(),
        ephemeral_range=EPHEMERAL_RANGE.read_text().strip(),
        probes=probe_ports(ports),
        socket_exit=socket_exit,
        socket_rows=rows,
        socket_error=error,
    )
    DIAGNOSTICS.mkdir(parents=True, exist_ok=True)
    output = json.dumps(asdict(snapshot), indent=2) + "\n"
    (DIAGNOSTICS / f"{stage}.json").write_text(output, encoding="utf-8")
    print(output)


def reserve_ports(ports: tuple[int, ...] | list[int]) -> None:
    if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError(
            "Port reservation requires a disposable GitHub Actions Linux runner"
        )
    existing = RESERVED_PORTS.read_text().strip()
    merged = merge_reservations(existing, tuple(ports))
    subprocess.run(
        ["sudo", "-n", "sysctl", "-w", f"net.ipv4.ip_local_reserved_ports={merged}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    expected = parse_reservations(existing) | set(ports)
    if not expected <= parse_reservations(RESERVED_PORTS.read_text()):
        raise RuntimeError(
            "Kernel did not retain all existing and required port reservations"
        )
    # Reservations prevent new automatic allocations, but do not evict old sockets.
    deadline = time.monotonic() + RELEASE_TIMEOUT_SECONDS
    while any(probe.errno is not None for probe in probe_ports(ports)):
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "Reserved browser ports remain occupied; see socket diagnostics"
            )
        time.sleep(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("reserve", "diagnose"))
    args = parser.parse_args()
    ports = tuple(repo.runtime_ports(repo.runtime_config()))
    if args.action == "diagnose":
        write_snapshot("failure", ports)
        return 0
    write_snapshot("before-reservation", ports)
    try:
        reserve_ports(ports)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        write_snapshot("reservation-failed", ports)
        print(f"ERROR: Browser port reservation failed: {exc}")
        return 1
    write_snapshot("after-reservation", ports)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
