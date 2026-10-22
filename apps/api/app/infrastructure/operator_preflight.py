"""One operator source operation per trusted local deployment, across processes."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.core.errors import AppError
from app.infrastructure.preflight import PreflightSaturated


@contextmanager
def operator_preflight_lock(path: Path | None) -> Iterator[None]:
    """Nonblocking Unix flock; never unlink the inode or fall back unlocked.

    Deployment configuration must name one shared file in a trusted local
    directory. This is not a lock across independent servers/filesystems.
    """
    if path is None or not path.is_absolute():
        raise AppError("mapping_operator_lock_unavailable")
    try:
        # Keep Windows imports functional, but refuse operator source commands.
        import fcntl
    except ImportError:
        raise AppError("mapping_operator_lock_unavailable") from None
    try:
        parent = path.parent.stat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_mode & 0o022:
            raise AppError("mapping_operator_lock_unavailable")
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    except (OSError, ValueError):
        raise AppError("mapping_operator_lock_unavailable") from None
    try:
        try:
            info = os.fstat(descriptor)
        except OSError:
            raise AppError("mapping_operator_lock_unavailable") from None
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_nlink != 1:
            raise AppError("mapping_operator_lock_unavailable")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PreflightSaturated() from None
        except OSError:
            raise AppError("mapping_operator_lock_unavailable") from None
        yield
    finally:
        # Closing releases flock even on cancellation/error. A crashed process
        # is handled by the OS; keeping the file prevents split-inode races.
        os.close(descriptor)
