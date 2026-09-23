from __future__ import annotations

from typing import ClassVar

from app.core.errors import AppError


class LegalAcceptanceError(AppError):
    """Base class for transport-neutral legal acceptance failures."""

    code: ClassVar[str]

    def __init__(self) -> None:
        super().__init__(self.code)


class DocumentVersionNotFoundError(LegalAcceptanceError):
    code = "document_version_not_found"


class RecurringConsentContextRequiredError(LegalAcceptanceError):
    code = "recurring_consent_context_required"


class RecurringConsentPlanInvalidError(LegalAcceptanceError):
    code = "recurring_consent_plan_invalid"


class InvalidAcceptanceTextHashError(LegalAcceptanceError):
    code = "invalid_acceptance_text_hash"


class RegistrationLegalPackInvalidError(LegalAcceptanceError):
    code = "registration_legal_pack_invalid"
