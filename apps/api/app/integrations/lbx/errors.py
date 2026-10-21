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


class LbxPreparationBlocked(LbxError):
    def __init__(self) -> None:
        super().__init__("lbx_preparation_blocked")


class LbxCreateUncertain(LbxError):
    """The POST may have taken effect. Only read-only recovery is safe.

    No remote exception/body/credential is retained. Step 4 owns durable fences;
    this outcome cannot authorize another POST, including after zero matches.
    """

    possible_send = True

    def __init__(self) -> None:
        super().__init__("lbx_create_uncertain")
