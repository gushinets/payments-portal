"""Outer async LBX I/O; every DB unit owns its synchronous Session."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pydantic import SecretStr
from starlette.concurrency import run_in_threadpool

from app.composition.sources import SourceResources
from app.core.errors import AppError
from app.core.settings import Settings
from app.domains.billing.contracts import BillingRefused, CustomerOpen
from app.domains.billing.customers import (
    authenticate,
    apply_customer_read,
    claim_customer_send,
    recheck_widget_session,
    release_unsent_claim,
    reserve_customer,
)
from app.domains.catalog.publication import SessionFactory
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.customer import NewCustomer, sign_widget_jwt
from app.integrations.lbx.errors import LbxAuthenticationFailed, LbxCreateNotSent, LbxResponseInvalid, LbxScopeMismatch

logger = logging.getLogger("payment_portal.billing")


@dataclass(frozen=True)
class AccountWidget:
    credential: SecretStr = field(repr=False)
    origin: str


async def recover_customer(
    client: LbxServerClient,
    factory: SessionFactory,
    current: CustomerOpen,
    *,
    budget: PreflightBudget,
    receipt_id: int | None = None,
) -> CustomerOpen:
    """Callable read-only discovery/point proof for later recovery; never POST/JWT."""
    provider_id = int(current.provider_id) if current.provider_id is not None else receipt_id
    if provider_id is None:
        candidates = await client.discover_users(outer_id=current.outer_key, budget=budget)
        if len(candidates) != 1:
            await run_in_threadpool(apply_customer_read, factory, current, ambiguous=len(candidates) > 1)
            raise BillingRefused("billing_customer_pending", 409)
        provider_id = candidates[0]
    point = await client.get_user(user_id=provider_id, budget=budget)
    return await run_in_threadpool(
        apply_customer_read, factory, current, provider_id=str(point.user_id), outer_key=point.outer_id
    )


async def bootstrap_account(
    sources: SourceResources, configuration: Settings, *, factory: SessionFactory, token: str
) -> AccountWidget:
    # Auth/email checks precede configuration/source access, including anonymous calls.
    def check_auth() -> None:
        with factory() as db:
            authenticate(db, configuration, token)

    await run_in_threadpool(check_auth)
    if configuration.lbx_widget_configuration_error is not None:
        raise BillingRefused(configuration.lbx_widget_configuration_error)
    client = sources.require_lbx()
    if sources.billing is None:
        raise BillingRefused("billing_not_configured")
    async with sources.billing.operation() as budget:
        current = await run_in_threadpool(reserve_customer, factory, configuration, token)
        logger.info(
            "billing_account_open",
            extra={"structured": {"stage": "account_bootstrap", "create_operation_id": str(current.operation_id)}},
        )
        possible_send = False
        try:
            if current.may_create:
                await client.prepare_customer_create(budget=budget)
                current = await run_in_threadpool(claim_customer_send, factory, configuration, token, current)
                if current.may_create:
                    try:
                        budget.check()
                    except AppError:
                        # Claim commit returned to this owner, and create_user
                        # has not been called: no source task can send later.
                        raise LbxCreateNotSent() from None
                    command = NewCustomer(
                        outer_id=current.outer_key,
                        email=current.email,
                        user_name=current.first_name,
                        user_surname=current.surname,
                        user_patronymic=current.patronymic,
                    )
                    # A crash/cancellation from here is possible_send, never eligible
                    # for another POST. Read-only recovery on the next explicit open.
                    possible_send = True
                    provider_id = await client.create_user(command, budget=budget)
                else:
                    provider_id = None
            else:
                provider_id = None
            current = await recover_customer(client, factory, current, budget=budget, receipt_id=provider_id)
            if current.provider_id is None:
                raise BillingRefused("billing_customer_pending", 409)
            credential = sign_widget_jwt(
                customer_id=current.provider_id, secret=configuration.lbx_widget_signing_secret
            )
            try:
                ready = await client.client_user(token=credential, budget=budget)
            except AppError as error:
                logger.warning(
                    "billing_client_not_ready",
                    extra={
                        "structured": {
                            "stage": "client_readiness",
                            "create_operation_id": str(current.operation_id),
                            "reason": error.code,
                        }
                    },
                )
                raise BillingRefused("billing_client_not_ready") from None
            if str(ready.user_id) != current.provider_id or ready.outer_id not in {None, current.outer_key}:
                await run_in_threadpool(apply_customer_read, factory, current, ambiguous=True)
                raise BillingRefused("billing_identity_conflict", 409)
            budget.check()
            await run_in_threadpool(recheck_widget_session, factory, configuration, token, current)
            budget.check()
            logger.info(
                "billing_account_ready",
                extra={"structured": {"stage": "client_ready", "create_operation_id": str(current.operation_id)}},
            )
            return AccountWidget(credential, configuration.lbx_provider_origin)
        except LbxCreateNotSent:
            await run_in_threadpool(release_unsent_claim, factory, current)
            logger.warning(
                "billing_customer_not_sent",
                extra={
                    "structured": {
                        "stage": "customer_create",
                        "method": "POST",
                        "endpoint": "/users",
                        "create_operation_id": str(current.operation_id),
                        "reason": "lbx_create_not_sent",
                    }
                },
            )
            raise BillingRefused("billing_source_unavailable") from None
        except LbxScopeMismatch:
            await run_in_threadpool(apply_customer_read, factory, current, ambiguous=True)
            raise BillingRefused("billing_identity_conflict", 409) from None
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
                raise
            # The durable possible_send fence already preserves uncertainty.
            if possible_send and current.provider_id is None:
                await run_in_threadpool(apply_customer_read, factory, current)
            raise BillingRefused(
                "billing_server_auth_failed"
                if isinstance(error, LbxAuthenticationFailed)
                else "billing_source_invalid_response"
                if isinstance(error, LbxResponseInvalid)
                else "billing_source_unavailable"
            ) from None
