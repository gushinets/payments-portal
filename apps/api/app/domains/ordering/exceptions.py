from __future__ import annotations

from app.core.exceptions import ApplicationError
from app.domains.ordering.schemas import ResolveSellablePlanInput
from app.models import DocumentVersion, Plan


class OrderingApplicationError(ApplicationError):
    code = "ordering_error"
    message = "Ordering operation failed"


class SellablePlanResolutionError(OrderingApplicationError):
    code = "unknown_product_plan"
    message = "Sellable plan could not be resolved"

    def __init__(
        self,
        *,
        reason: str,
        payload: ResolveSellablePlanInput,
        plan: Plan | None = None,
    ) -> None:
        self.payload = payload
        self.plan = plan
        super().__init__(reason=reason)

    def log_context(self) -> dict:
        return {
            "code": self.code,
            "reason": self.reason,
            "tenant_id": self.payload.tenant_id,
            "region": self.payload.region,
            "entrypoint_code": self.payload.entrypoint_code,
            "plan_code": self.payload.plan_code,
            "plan_id": str(self.plan.id) if self.plan else None,
            "scope_type": self.plan.scope_type if self.plan else None,
            "product_id": str(self.plan.product_id) if self.plan and self.plan.product_id else None,
            "bundle_id": str(self.plan.bundle_id) if self.plan and self.plan.bundle_id else None,
        }


class MissingRequiredDocumentsError(OrderingApplicationError):
    code = "missing_required_documents"
    message = "Required legal documents must be accepted before checkout"

    def __init__(
        self,
        *,
        user_id: str,
        documents: list[DocumentVersion],
    ) -> None:
        self.user_id = user_id
        self.documents = documents
        super().__init__()

    def log_context(self) -> dict:
        return {
            "code": self.code,
            "user_id": self.user_id,
            "document_count": len(self.documents),
            "documents": [
                {
                    "document_version_id": str(document.id),
                    "doc_type": document.doc_type,
                    "version": document.version,
                }
                for document in self.documents
            ],
        }
