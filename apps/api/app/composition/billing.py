"""One account-customer ensure operation; HTTP never holds a SQL transaction."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from random import uniform
from time import monotonic
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
from app.infrastructure.preflight import PreflightBudget, PreflightCleanupPending, PreflightDeadlineExceeded
from app.integrations.lbx._transport import customer_diagnostics
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.customer import NewCustomer, sign_widget_jwt
from app.integrations.lbx.errors import (
    LbxAuthenticationFailed,
    LbxAttemptsExhausted,
    LbxCreateNotSent,
    LbxError,
    LbxProviderRejected,
    LbxRateLimited,
    LbxResponseInvalid,
    LbxScopeForbidden,
    LbxScopeMismatch,
    LbxTimeout,
    LbxUnavailable,
)

logger = logging.getLogger("payment_portal.billing")
CUSTOMER_RETRY_BASE_SECONDS = 0.25
CUSTOMER_RETRY_MAX_SECONDS = 2.0


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


def _temporary_customer_failure(error: LbxError) -> bool:
    if error.response_facts is not None and error.response_facts.failure_kind == "authorization":
        return False
    if isinstance(error, (LbxCreateNotSent, LbxTimeout, LbxUnavailable, LbxRateLimited, LbxAttemptsExhausted)):
        return True
    # This hint classifies a temporary response only. Permission to repeat a
    # customer CREATE comes from the owner-approved customer policy and claim.
    return error.response_facts is not None and error.response_facts.retryable_get


async def _customer_retry_wait(budget: PreflightBudget, retries: int) -> None:
    delay = min(CUSTOMER_RETRY_MAX_SECONDS, CUSTOMER_RETRY_BASE_SECONDS * 2 ** min(retries, 3))
    if delay >= budget.remaining_seconds():
        raise PreflightDeadlineExceeded()

    async def pause() -> None:
        await asyncio.sleep(uniform(delay / 2, delay))

    await budget.run(pause)


async def _create_customer_attempt(
    client: LbxServerClient,
    *,
    factory: SessionFactory,
    current: CustomerOpen,
    command: NewCustomer,
    budget: PreflightBudget,
) -> CustomerOpen:
    """One fenced send; resource cleanup finishes before any later attempt."""
    keep_lease = False
    try:
        try:
            budget.check()
        except AppError:
            raise LbxCreateNotSent() from None
        try:
            provider_id = await client.create_user(command, budget=budget)
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
            raise
        return await run_in_threadpool(record_customer_receipt, factory, current, provider_id)
    except LbxCreateNotSent:
        await run_in_threadpool(release_unsent_claim, factory, current)
        raise
    except (PreflightDeadlineExceeded, PreflightCleanupPending, asyncio.CancelledError):
        keep_lease = True
        # A timed-out source task can still own cleanup: retain its finite lease.
        raise
    finally:
        # Pending source work keeps its lease until expiry. A completed attempt
        # must be followed by a fresh snapshot and discovery before another send.
        if not keep_lease:
            await run_in_threadpool(finish_customer_attempt, factory, current)


async def ensure_customer(
    client: LbxServerClient,
    configuration: Settings,
    *,
    factory: SessionFactory,
    token: str,
    current: CustomerOpen,
    budget: PreflightBudget,
) -> CustomerOpen:
    """Bounded customer recovery; failed reads never authorize a CREATE."""
    command = NewCustomer(
        outer_id=current.outer_key,
        email=current.email,
        user_name=current.first_name,
        user_surname=current.surname,
        user_patronymic=current.patronymic,
    )
    operation_id = current.operation_id
    retries = 0
    failure: LbxError | None = None
    email_taken = False
    try:
        while True:
            budget.check()
            if current.operation_id != operation_id or current.outer_key != command.outer_id:
                raise BillingRefused("billing_identity_conflict", 409)
            current = replace(current, email=command.email)
            try:
                found = await _find_customer(client, factory, current, budget=budget)
                if found is None and not email_taken and failure is None:
                    await client.prepare_customer_create(budget=budget)
            except LbxError as error:
                if not _temporary_customer_failure(error):
                    raise
            else:
                if found is not None:
                    return found
                # An email rejection proves this opening must search, not send
                # again. A permanent failure still gets one recovery read first.
                if failure is not None and not email_taken and not _temporary_customer_failure(failure):
                    raise failure
                if not email_taken and failure is None:
                    current = await run_in_threadpool(claim_customer_send, factory, configuration, token, current)
                    if current.may_create:
                        try:
                            current = await _create_customer_attempt(
                                client, factory=factory, current=current, command=command, budget=budget
                            )
                        except LbxError as error:
                            failure = error
                            facts = error.response_facts
                            email_taken = facts is not None and facts.reason == "email_not_unique"
                        current = await run_in_threadpool(reserve_customer, factory, configuration, token)
                        # Immediately verify the saved receipt or recover the
                        # failed send. Another CREATE always waits and rereads.
                        continue
            await _customer_retry_wait(budget, retries)
            retries += 1
            if failure is not None and _temporary_customer_failure(failure):
                failure = None
            current = await run_in_threadpool(reserve_customer, factory, configuration, token)
    except PreflightDeadlineExceeded:
        raise BillingAccountFailure("billing_customer_pending", 409) from None
    except asyncio.CancelledError:
        # The enclosing admission scope also enforces this same deadline.
        # Preserve caller cancellation; normalize only its own timeout.
        if monotonic() >= budget.work_deadline:
            raise BillingAccountFailure("billing_customer_pending", 409) from None
        raise


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
