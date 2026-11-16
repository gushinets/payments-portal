"""Small Linux Compose image path; operators own reviewed selection and maintenance."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def deploy(args: argparse.Namespace) -> None:
    import fcntl

    # One shared operator-owned path across checkouts; keep its inode after release.
    lock = args.lock_file
    if not lock.is_absolute() or lock.parent.stat().st_mode & 0o022:
        raise ValueError(
            "deployment lock needs an absolute path in a private operator directory"
        )
    descriptor = os.open(
        lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
    )
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077:
            raise ValueError("deployment lock must be a private regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        compose = [
            "docker",
            "compose",
            "--project-name",
            args.project,
            "--env-file",
            str(args.env_file.resolve()),
            "-f",
            str(ROOT / "docker-compose.prod.yml"),
        ]
        if args.network_overlay is not None:
            compose.extend(["-f", str(args.network_overlay.resolve())])
        compose.extend(["-f", str(ROOT / "deploy/compose.images.yml")])
        model = json.loads(
            subprocess.run(
                [*compose, "config", "--format", "json"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        for name in ("api", "web"):
            ref = model["services"][name]["image"]
            if "@sha256:" not in ref and (
                ":" not in ref.rsplit("/", 1)[-1] or ref.endswith(":latest")
            ):
                raise ValueError(f"{name} must select a reviewed version tag or digest")
        if args.frontend_only:
            commands = [
                (
                    "up",
                    "-d",
                    "--no-deps",
                    "--no-build",
                    "--pull",
                    "never",
                    "--wait",
                    "web",
                )
            ]
        else:
            commands = [
                # The API owns the embedded billing worker. Stop all old writes first.
                ("stop", "api"),
                ("up", "-d", "--no-build", "--pull", "never", "--wait", "postgres"),
                ("run", "--rm", "--no-deps", "migrate"),
                (
                    "up",
                    "-d",
                    "--no-deps",
                    "--no-build",
                    "--pull",
                    "never",
                    "--wait",
                    "api",
                ),
                ("up", "-d", "--no-deps", "--no-build", "--pull", "never", "--wait", "web"),
            ]
        for command in commands:
            subprocess.run([*compose, *command], cwd=ROOT, check=True)
    finally:
        os.close(descriptor)
