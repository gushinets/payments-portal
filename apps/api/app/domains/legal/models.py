"""Legal domain model exports."""

from app.models import (
    DocumentAcceptance,
    DocumentVersion,
    LegalAcceptanceEvent,
    LegalEntity,
)

__all__ = ["DocumentAcceptance", "DocumentVersion", "LegalAcceptanceEvent", "LegalEntity"]
