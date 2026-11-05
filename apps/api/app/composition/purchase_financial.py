"""Financial GET facts; strict admission follows the required readback commit."""

from dataclasses import dataclass
from datetime import datetime

from app.core.time import utc_now
from app.core.errors import AppError
from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.readback_contracts import (
    ReadbackSubject,
    ScopedReadbackFinding,
    OriginalCreateReadbackSubject,
    OriginalCreateProof,
)
from app.domains.purchases.contracts import FinancialOperation, Purchase, PurchaseRefused
from app.infrastructure.preflight import PreflightBudget, PreflightDeadlineExceeded
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.errors import LbxError, LbxResponseInvalid, LbxScopeMismatch
from app.integrations.lbx.financial import (
    Agreement,
    Subscription,
    NewSubscription,
    agreement_closed,
    inventory_terminal,
    prove_agreement,
    prove_subscription,
)
from app.integrations.lbx.readback import inspect_readback
from app.models import ExternalCreateOperationKind as Kind


@dataclass(frozen=True)
class FinancialMatch:
    provider_id: int
    agreement: Agreement
    subscription: Subscription | None
    read_started_at: datetime
    read_finished_at: datetime
    finding: ScopedReadbackFinding | None = None
    failure: AppError | None = None

    @property
    def terminal(self) -> bool:
        return agreement_closed(self.agreement) or (
            self.subscription is not None and inventory_terminal(self.subscription, self.agreement)
        )

    def require_original_terms(self, purchase: Purchase, operation: FinancialOperation, customer: CustomerOpen) -> None:
        if self.failure is not None:
            raise self.failure
        agreement_op = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
        prove_agreement(
            self.agreement,
            user_id=int(customer.provider_id),
            seller_id=purchase.accepted.seller_id,
            number=agreement_op.key,
        )
        if self.subscription is not None:
            prove_subscription(
                self.subscription,
                agreement_id=int(agreement_op.bound_id),
                selection=purchase.accepted.selection,
                offer=purchase.accepted.offer,
            )

    def original_proof(self, subject: OriginalCreateReadbackSubject) -> OriginalCreateProof:
        self.require_original_terms(subject.purchase, subject.operation, subject.customer)
        selection = subject.purchase.accepted.selection
        command = NewSubscription(
            agreement_id=int(subject.agreement_id),
            tariff_id=selection.tariff_id,
            period_id=selection.period_id,
            tariff_service_id=selection.tariff_service_id,
            quantity=selection.quantity,
            outer_id=subject.operation.key,
        ).request_document()
        if self.subscription is None or self.finding is None or command != subject.saved_command:
            raise LbxResponseInvalid()
        return OriginalCreateProof(
            str(self.provider_id),
            subject.agreement_id,
            command,
            self.read_started_at,
            self.read_finished_at,
            ("customer", "agreement", "subscription", "unique_candidate", "effective_terms"),
            self.finding.negative,
        )


async def _find_financial(
    client: LbxServerClient,
    purchase: Purchase,
    operation: FinancialOperation,
    customer: CustomerOpen,
    *,
    budget: PreflightBudget,
    require_discovery: bool = False,
    subject: ReadbackSubject | None = None,
) -> FinancialMatch | None:
    """Keep owned negatives even when the later effective-term proof is incomplete."""
    started = utc_now()
    user = None
    if subject is not None:
        user = await client.get_user(user_id=int(customer.provider_id), budget=budget)
        if user.outer_id is None:
            raise LbxResponseInvalid()
        if user.outer_id != customer.outer_key:
            raise LbxScopeMismatch()
    agreement_op = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
    if operation.kind == Kind.AGREEMENT:
        saved = operation.bound_id or operation.candidate_id
        ids = (
            (int(saved),)
            if saved and not require_discovery
            else await client.discover_agreements(
                user_id=int(customer.provider_id), number=operation.key, budget=budget
            )
        )
        if len(ids) > 1 or (require_discovery and saved and ids != (int(saved),)):
            raise LbxScopeMismatch()
        if not ids:
            return None
        agreement = await client.get_agreement(agreement_id=ids[0], budget=budget)
        match = FinancialMatch(ids[0], agreement, None, started, utc_now())
        match.require_original_terms(purchase, operation, customer)
        if require_discovery and (
            operation.agreement_create_date is None
            or agreement.create_date != operation.agreement_create_date.isoformat()
        ):
            raise LbxResponseInvalid()
        return match
    if agreement_op.bound_id is None:
        raise PurchaseRefused("purchase_pending", 409)
    agreement = await client.get_agreement(agreement_id=int(agreement_op.bound_id), budget=budget)
    saved = operation.bound_id or operation.candidate_id
    if operation.bound_id and not require_discovery:
        ids = (int(operation.bound_id),)
    else:
        rows = await client.discover_subscriptions(
            user_id=int(customer.provider_id), agreement_id=int(agreement_op.bound_id), budget=budget
        )
        ids = tuple(row.subscription_id for row in rows)
        if saved:
            if any(value != int(saved) for value in ids) or (require_discovery and ids != (int(saved),)):
                raise LbxScopeMismatch()
            # A receipt narrows discovery; first binding still requires uniqueness.
            if ids or operation.bound_id:
                ids = (int(saved),)
    if len(ids) > 1:
        raise LbxScopeMismatch()
    if not ids:
        return None
    failure = None
    try:
        point = await client.get_subscription(subscription_id=ids[0], budget=budget)
    except (LbxError, PreflightDeadlineExceeded) as error:
        if operation.bound_id is None:
            raise
        point, failure = None, error
    if failure is None:
        budget.check()
    finished = utc_now()
    finding = None
    if subject is not None:
        finding = inspect_readback(
            subject,
            user=user,
            agreement=agreement,
            subscription=point,
            window=(started, finished),
            reads=("customer", "agreement") + (("subscription",) if point else ()),
            provider_subscription_id=str(ids[0]),
        )
    return FinancialMatch(ids[0], agreement, point, started, finished, finding, failure)
