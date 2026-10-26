from app.core.errors import AppError


class LbxError(AppError):
    """Safe transport-neutral failure: no remote body, credential or URL."""


class LbxNotConfigured(LbxError):
    def __init__(self) -> None:
        super().__init__("lbx_not_configured")


class LbxAuthenticationFailed(LbxError):
    def __init__(self) -> None:
        super().__init__("lbx_authentication_failed")


class LbxScopeForbidden(LbxError):
    def __init__(self) -> None:
        super().__init__("lbx_scope_forbidden")


class LbxScopeMismatch(LbxError):
    def __init__(self) -> None:
        super().__init__("lbx_scope_mismatch")


class LbxResponseInvalid(LbxError):
    def __init__(self) -> None:
        super().__init__("lbx_response_invalid")


class LbxUnavailable(LbxError):
    def __init__(self) -> None:
        super().__init__("lbx_unavailable")


class LbxRateLimited(LbxError):
    def __init__(self) -> None:
        super().__init__("lbx_rate_limited")


class LbxTimeout(LbxError):
    def __init__(self) -> None:
        super().__init__("lbx_timeout")


class LbxAttemptsExhausted(LbxError):
    def __init__(self) -> None:
        super().__init__("lbx_attempts_exhausted")


class LbxClosed(LbxError):
    def __init__(self) -> None:
        super().__init__("lbx_closed")


class LbxCreateNotSent(LbxError):
    """Proven failure before dispatch, distinct from every possible-send error."""

    def __init__(self) -> None:
        super().__init__("lbx_create_not_sent")
