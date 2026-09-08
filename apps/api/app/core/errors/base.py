from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class AppError(Exception):
    def __init__(
        self,
        code: str | None = None,
        *,
        message_safe: str | None = None,
        details_safe: Mapping[str, Any] | None = None,
    ) -> None:
        if code is None:
            super().__init__()
        else:
            super().__init__(code)
        self.code = code
        self.message_safe = message_safe
        self.details_safe = dict(details_safe or {})
