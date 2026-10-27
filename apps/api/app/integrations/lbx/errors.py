from dataclasses import dataclass

from app.core.errors import AppError


@dataclass(frozen=True)
class LbxResponseFacts:
    """Safe observed context; retryable_get never authorizes repeating a CREATE."""

    http_status: int | None
    lbx_code: int | None
    reason: str
    provider_error_present: bool
    failure_kind: str
    retryable_get: bool
    method: str
    endpoint: str
    request_id: str | None
    create_operation_id: str | None


class LbxError(AppError):
    """Safe transport-neutral failure: no remote body, credential or URL."""

    response_facts: LbxResponseFacts | None = None


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


class LbxProviderRejected(LbxError):
    """Recognized provider error envelope; never proof that a CREATE had no effect."""

    def __init__(self) -> None:
        super().__init__("lbx_provider_rejected")


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
