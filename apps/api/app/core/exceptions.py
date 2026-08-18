from __future__ import annotations


class ApplicationError(Exception):
    code = "application_error"
    message = "Application error"

    def __init__(
        self,
        *,
        reason: str | None = None,
    ) -> None:
        self.reason = reason
        super().__init__(self.message)

    def log_context(self) -> dict:
        return {
            "code": self.code,
            "reason": self.reason,
        }
