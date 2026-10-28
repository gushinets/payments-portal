"""One account-customer ensure operation; HTTP never holds a SQL transaction."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from uuid import UUID

from pydantic import SecretStr
from starlette.concurrency import run_in_threadpool

from app.composition.sources import SourceResources
from app.core.errors import AppError
from app.core.settings import Settings
from app.domains.billing.contracts import BillingAccountFailure, BillingRefused, CustomerOpen
from app.domains.billing.customers import (
    apply_customer_read,
    authenticate,
    claim_customer_send,
    finish_customer_attempt,
    recheck_widget_session,
    record_customer_create_failure,
    record_customer_receipt,
    release_unsent_claim,
    reserve_customer,
)
from app.domains.catalog.publication import SessionFactory
from app.infrastructure.preflight import PreflightBudget, PreflightCleanupPending
from app.integrations.lbx._transport import customer_diagnostics
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.customer import NewCustomer, sign_widget_jwt
from app.integrations.lbx.errors import (
    LbxAuthenticationFailed,
    LbxCreateNotSent,
    LbxError,
    LbxProviderRejected,
    LbxResponseInvalid,
    LbxScopeForbidden,
    LbxScopeMismatch,
)

logger = logging.getLogger("payment_portal.billing")


@dataclass(frozen=True)
class AccountWidget:
    credential: SecretStr = field(repr=False)
    origin: str
    purchase_id: UUID | None = None
    agreement_reference: str | None = None
    seller_reference: str | None = None


async def _find_customer(
    client: LbxServerClient, factory: SessionFactory, current: CustomerOpen, *, budget: PreflightBudget
) -> CustomerOpen | None:
    """Search candidates, then require original paired identity before binding."""
    saved_id = current.provider_id or current.receipt_id
    if saved_id is not None:
        candidates = (int(saved_id),)
    else:
        candidates = await client.discover_users(outer_id=current.outer_key, budget=budget)
        if not candidates and current.email:
            email_ids: set[int] = set()
            for email in dict.fromkeys((current.email, current.email.casefold())):
                email_ids.update(await client.discover_users_by_email(email=email, budget=budget))
            candidates = tuple(sorted(email_ids))
    if len(candidates) > 1:
        await run_in_threadpool(apply_customer_read, factory, current, ambiguous=True)
    if not candidates:
        return None
    point = await client.get_user(user_id=candidates[0], budget=budget)
    return await run_in_threadpool(
        apply_customer_read, factory, current, provider_id=str(point.user_id), outer_key=point.outer_id
    )


async def recover_customer(
    client: LbxServerClient, factory: SessionFactory, current: CustomerOpen, *, budget: PreflightBudget
) -> CustomerOpen:
    """GET-only recovery entrypoint; never creates or issues Widget credentials."""
    found = await _find_customer(client, factory, current, budget=budget)
    if found is None:
        raise BillingAccountFailure("billing_source_unavailable")
    return found


async def ensure_customer(
    client: LbxServerClient,
    configuration: Settings,
    *,
    factory: SessionFactory,
    token: str,
    current: CustomerOpen,
    budget: PreflightBudget,
) -> CustomerOpen:
    """Shared discover/bind/create/recover use case; the sole caller of CREATE."""
    found = await _find_customer(client, factory, current, budget=budget)
    if found is not None:
        return found
    await client.prepare_customer_create(budget=budget)
    current = await run_in_threadpool(claim_customer_send, factory, configuration, token, current)
    if not current.may_create:
        # Another open owns the send or has just stored a receipt/binding.
        found = await _find_customer(client, factory, current, budget=budget)
        if found is not None:
            return found
        raise BillingRefused("billing_customer_pending", 409)
    keep_lease = False
    try:
        try:
            budget.check()
        except AppError:
            raise LbxCreateNotSent() from None
        try:
            provider_id = await client.create_user(
                NewCustomer(
                    outer_id=current.outer_key,
                    email=current.email,
                    user_name=current.first_name,
                    user_surname=current.surname,
                    user_patronymic=current.patronymic,
                ),
                budget=budget,
            )
        except LbxCreateNotSent:
            raise
        except LbxError as error:
            facts = error.response_facts
            if facts is not None and facts.http_status is not None:
                await run_in_threadpool(
                    record_customer_create_failure,
                    factory,
                    current,
                    http_status=facts.http_status,
                    lbx_code=facts.lbx_code,
                    reason=facts.reason,
                )
            # Includes duplicate/uniqueness rejection and lost/malformed replies.
            # Recovery never sends another POST in the same opening request.
            try:
                found = await _find_customer(client, factory, current, budget=budget)
            except LbxScopeMismatch:
                raise
            except LbxError:
                raise BillingAccountFailure("billing_customer_pending", 409) from None
            if found is not None:
                return found
            raise BillingAccountFailure("billing_customer_pending", 409) from None
        current = await run_in_threadpool(record_customer_receipt, factory, current, provider_id)
        return await recover_customer(client, factory, current, budget=budget)
    except LbxCreateNotSent:
        await run_in_threadpool(release_unsent_claim, factory, current)
        raise
    except (PreflightCleanupPending, asyncio.CancelledError):
        keep_lease = True
        # A timed-out source task can still own cleanup: retain its finite lease.
        raise
    finally:
        # Pending source work keeps its lease until expiry. Completed responses
        # can be retried on another explicit open after fresh discovery.
        if not keep_lease:
            await run_in_threadpool(finish_customer_attempt, factory, current)


async def bootstrap_account(
    sources: SourceResources,
    configuration: Settings,
    *,
    factory: SessionFactory,
    token: str,
    purchase_id: UUID | None = None,
) -> AccountWidget:
    def check_auth() -> UUID:
        with factory() as db:
            return authenticate(db, configuration, token).id

    owner_id = await run_in_threadpool(check_auth)
    if purchase_id is not None:
        from app.domains.purchases.service import read_purchase
        from app.models import PurchaseIntentState

        owned_purchase = await run_in_threadpool(read_purchase, factory, owner_id, purchase_id)
        if not owned_purchase.held or owned_purchase.state != PurchaseIntentState.LINKED:
            raise BillingRefused("purchase_not_prepared", 409)
    if configuration.lbx_widget_configuration_error is not None:
        raise BillingAccountFailure(configuration.lbx_widget_configuration_error)
    client = sources.require_lbx()
    if sources.billing is None:
        raise BillingAccountFailure("billing_not_configured")
    async with sources.billing.operation() as budget:
        try:
            current = await run_in_threadpool(reserve_customer, factory, configuration, token)
        except BillingRefused as error:
            if error.status in {401, 403} or error.code == "billing_busy":
                raise
            raise BillingAccountFailure(error.code, error.status) from None
        logger.info(
            "billing_account_open",
            extra={"structured": {"stage": "account_bootstrap", "create_operation_id": str(current.operation_id)}},
        )
        with customer_diagnostics(str(current.operation_id)):
            try:
                current = await ensure_customer(
                    client, configuration, factory=factory, token=token, current=current, budget=budget
                )
                payment_purchase = None
                if purchase_id is not None:
                    from app.composition.purchases import verify_payment_purchase

                    payment_purchase = await verify_payment_purchase(
                        sources,
                        configuration,
                        factory=factory,
                        token=token,
                        purchase_id=purchase_id,
                        customer=current,
                        budget=budget,
                    )
                credential = sign_widget_jwt(
                    customer_id=current.provider_id, secret=configuration.lbx_widget_signing_secret
                )
                try:
                    ready = await client.client_user(token=credential, budget=budget)
                except AppError:
                    raise BillingAccountFailure("billing_client_not_ready") from None
                if str(ready.user_id) != current.provider_id or ready.outer_id not in {None, current.outer_key}:
                    await run_in_threadpool(apply_customer_read, factory, current, ambiguous=True)
                    raise BillingAccountFailure("billing_identity_conflict", 409)
                budget.check()
                await run_in_threadpool(recheck_widget_session, factory, configuration, token, current)
                budget.check()
                logger.info(
                    "billing_account_ready",
                    extra={"structured": {"stage": "client_ready", "create_operation_id": str(current.operation_id)}},
                )
                if payment_purchase is not None:
                    from app.domains.purchases.service import recheck_payment_purchase
                    from app.models import ExternalCreateOperationKind

                    await run_in_threadpool(recheck_payment_purchase, factory, configuration, token, payment_purchase)
                    budget.check()
                    agreement = next(
                        op for op in payment_purchase.operations if op.kind == ExternalCreateOperationKind.AGREEMENT
                    )
                    return AccountWidget(
                        credential,
                        configuration.lbx_provider_origin,
                        payment_purchase.id,
                        agreement.key,
                        str(payment_purchase.accepted.seller_id),
                    )
                return AccountWidget(credential, configuration.lbx_provider_origin)
            except AppError as error:
                logger.warning(
                    "billing_account_failed",
                    extra={
                        "structured": {
                            "stage": "account_bootstrap",
                            "create_operation_id": str(current.operation_id),
                            "reason": error.code,
                        }
                    },
                )
                if isinstance(error, BillingRefused):
                    if error.status in {401, 403} or error.code in {"billing_customer_pending", "billing_busy"}:
                        raise
                    raise BillingAccountFailure(error.code, error.status) from None
                if isinstance(error, LbxScopeMismatch):
                    try:
                        await run_in_threadpool(apply_customer_read, factory, current, ambiguous=True)
                    except BillingRefused as conflict:
                        raise BillingAccountFailure(conflict.code, conflict.status) from None
                raise BillingAccountFailure(
                    "billing_server_auth_failed"
                    if isinstance(error, (LbxAuthenticationFailed, LbxScopeForbidden))
                    else "billing_identity_conflict"
                    if isinstance(error, LbxScopeMismatch)
                    else "billing_source_invalid_response"
                    if isinstance(error, LbxResponseInvalid)
                    else "billing_source_rejected"
                    if isinstance(error, LbxProviderRejected)
                    else "billing_source_unavailable"
                ) from None
