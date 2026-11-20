"""Signal handling shared by the API test runner and its database fixtures."""

import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import current_thread, main_thread
from types import FrameType


@contextmanager
def defer_interrupts(*signals: int) -> Iterator[None]:
    """Replay the first handled signal after recording ownership of a resource."""
    if current_thread() is not main_thread():
        yield
        return

    handlers: dict[int, Callable[[int, FrameType | None], object]] = {}
    pending: tuple[int, FrameType | None] | None = None

    def defer(signum: int, frame: FrameType | None) -> None:
        nonlocal pending
        if pending is None:
            pending = signum, frame

    try:
        for signum in signals:
            handler = signal.getsignal(signum)
            if callable(handler):
                handlers[signum] = handler
                signal.signal(signum, defer)
        yield
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)
        if pending is not None:
            signum, frame = pending
            handlers[signum](signum, frame)
