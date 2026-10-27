"""Account-only billing contracts; no commercial or paid-access authority."""

from dataclasses import dataclass, field
from uuid import UUID

from app.core.errors import AppError


CREATE_RESPONSE_SCHEMA = "customer-create-response:v1"
CREATE_FAILURE_REASONS = frozenset(
    {"email_not_unique", "provider_rejected", "credentials_denied", "schema_invalid", "unknown"}
)


class BillingRefused(AppError):
    def __init__(self, code: str, status: int = 503) -> None:
        super().__init__(code)
        self.status = status


class BillingAccountFailure(BillingRefused):
    """Unresolved account integration failure, reported once by Presentation."""


@dataclass(frozen=True, repr=False)
class CustomerOpen:
    customer_id: UUID
    operation_id: UUID
    fence: UUID | None
    outer_key: str
    provider_id: str | None
    may_create: bool = False
    email: str = field(default="", repr=False)
    first_name: str | None = None
    surname: str | None = None
    patronymic: str | None = None
    receipt_id: str | None = None
