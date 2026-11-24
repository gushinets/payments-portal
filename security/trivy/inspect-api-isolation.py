#!/usr/bin/env python3
"""Read bounded Linux privilege evidence; never write to cgroups or join another namespace."""

from __future__ import annotations

import ctypes
import errno
import json
import os
from pathlib import Path


def process_security(path: Path) -> dict[str, str]:
    fields = {"Uid", "CapEff", "CapPrm", "CapBnd", "NoNewPrivs", "Seccomp"}
    return {
        key: value.strip()
        for line in path.read_text().splitlines()
        if ":" in line
        for key, value in [line.split(":", 1)]
        if key in fields
    }


def collect() -> dict[str, object]:
    own = process_security(Path("/proc/self/status"))
    init = process_security(Path("/proc/1/status"))
    library = ctypes.CDLL(None, use_errno=True)
    library.setns.argtypes = [ctypes.c_int, ctypes.c_int]
    library.setns.restype = ctypes.c_int
    fd = os.open("/proc/self/ns/mnt", os.O_RDONLY | os.O_CLOEXEC)
    try:
        result = library.setns(fd, 0)
        namespace_errno = ctypes.get_errno() if result != 0 else 0
    finally:
        os.close(fd)
    # O_WRONLY checks access only: no bytes are ever written.
    try:
        fd = os.open("/sys/fs/cgroup/cgroup.procs", os.O_WRONLY | os.O_CLOEXEC)
    except OSError as error:
        cgroup_errno = error.errno
    else:
        os.close(fd)
        cgroup_errno = 0
    secure = all(
        int(status[key], 16) == 0
        for status in (own, init)
        for key in ("CapEff", "CapPrm", "CapBnd")
    )
    secure = secure and all(status["NoNewPrivs"] == "1" for status in (own, init))
    secure = (
        secure
        and namespace_errno == errno.EPERM
        and cgroup_errno in (errno.EROFS, errno.EACCES, errno.EPERM, errno.ENOENT)
    )
    policy = Path("/etc/dpkg/dpkg.cfg.d/99-api-runtime-exclusions")
    filters = policy.read_text().splitlines() if policy.exists() else []
    return {
        "runtime_file_filters": filters,
        "excluded_paths_present": {
            name: Path(name).exists()
            for name in ("/usr/bin/infocmp", "/usr/bin/nsenter")
        },
        "uid": os.getuid(),
        "self": own,
        "pid1": init,
        "self_mount_namespace_join_errno": namespace_errno,
        "cgroup_open_write_errno": cgroup_errno,
        "isolation_boundary_passed": secure,
        "limits": "No cgroup write or exploit performed. Does not exclude kernel flaws, privileged overrides or unsafe root-owned-file ACL operations.",
    }


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2))
