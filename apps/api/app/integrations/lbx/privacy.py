"""Suppress automatic vendor diagnostics only inside this LBX I/O context.

HTTPX INFO includes provider URLs; httpcore DEBUG includes response headers and
raw transport exceptions. Neither is safe billing telemetry. Logger names are
the ones used by the repository's pinned HTTPX/httpcore async transports.
Application failure reporting remains with the outer safe error boundary.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar


_PRIVATE_IO: ContextVar[bool] = ContextVar("lbx_private_http_io", default=False)
_HTTP_LOGGERS = (
    "httpx",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
)


class _LbxDiagnosticFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _PRIVATE_IO.get()


_FILTER = _LbxDiagnosticFilter()


@contextmanager
def private_http_diagnostics() -> Iterator[None]:
    # addFilter is idempotent for this one filter object. No logger levels or
    # handlers change, and concurrent non-LBX tasks retain their diagnostics.
    for name in _HTTP_LOGGERS:
        logging.getLogger(name).addFilter(_FILTER)
    token = _PRIVATE_IO.set(True)
    try:
        yield
    finally:
        _PRIVATE_IO.reset(token)
