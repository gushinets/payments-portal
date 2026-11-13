"""Private pytest protocol for the subprocess API runner; no fixture ownership."""

from __future__ import annotations

import json
import signal
from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--runner-manifest", required=True)


def pytest_configure() -> None:
    # Windows process groups receive CTRL_BREAK_EVENT from the runner.
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.default_int_handler)


def pytest_collection_finish(session: pytest.Session) -> None:
    for item in session.items:
        item.user_properties.append(("nodeid", item.nodeid))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    Path(session.config.getoption("--runner-manifest")).write_text(
        json.dumps(
            {
                "nodeids": [item.nodeid for item in session.items],
                "exit_code": int(exitstatus),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
