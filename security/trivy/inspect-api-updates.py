#!/usr/bin/env python3
"""Check current signed Debian candidates in a disposable build-base container."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def planned_upgrades(simulation: str) -> list[str]:
    """Identify actual simulated install/upgrade records, not success text alone."""
    return [line for line in simulation.splitlines() if line.startswith("Inst ")]


def main() -> None:
    sources = Path("/etc/apt/sources.list.d/any674-backports.sources")
    sources.write_text(
        "Types: deb\nURIs: http://deb.debian.org/debian\nSuites: trixie-backports\n"
        "Components: main\nSigned-By: /usr/share/keyrings/debian-archive-keyring.gpg\n",
        encoding="utf-8",
    )
    update = subprocess.run(
        ["apt-get", "update"], capture_output=True, text=True, check=True
    )
    simulation = subprocess.run(
        ["apt-get", "--simulate", "upgrade"], capture_output=True, text=True, check=True
    )
    inventory = subprocess.run(
        [
            "dpkg-query",
            "-W",
            "-f=${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\n",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    packages = [line.split("\t")[0] for line in inventory.stdout.splitlines()]
    policy = subprocess.run(
        ["apt-cache", "policy", *packages], capture_output=True, text=True, check=True
    )
    print(
        json.dumps(
            {
                "scope": "Disposable build-base only. Official backports queried, not added to final image.",
                "apt_update_exit": update.returncode,
                "repository_sources": {
                    str(p): p.read_text()
                    for p in Path("/etc/apt/sources.list.d").glob("*.sources")
                },
                "installed_packages": inventory.stdout,
                "upgrade_simulation": simulation.stdout,
                "pending_upgrades": planned_upgrades(simulation.stdout),
                "candidate_policy": policy.stdout,
                "note": "Backports may have lower priority; inspect version table against vendor fixed versions. "
                "No package installed by this probe. No unsupported repository or final-image modification.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
