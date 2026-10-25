from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any, TypeVar

import httpx
from pydantic import TypeAdapter

from app.core.settings import AppEnv, Settings
from app.domains.catalog.commercial_offer import SelectedCommercialOffer
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.dto import (
    LbxEnvelope,
    LbxServicePrice,
    LbxTariff,
    LbxTariffPeriod,
    LbxTariffService,
)
from app.integrations.lbx.errors import (
    LbxAuthenticationFailed,
    LbxClosed,
    LbxCreateUncertain,
    LbxNotConfigured,
    LbxPreparationBlocked,
    LbxResponseInvalid,
    LbxScopeMismatch,
)
from app.integrations.lbx.privacy import private_http_diagnostics
from app.integrations.lbx.preparation_dto import (
    AgreementInfo,
    CreateEnvelope,
    CreatedAgreement,
    CreatedSubscription,
    CreatedUser,
    PostAgreement,
    PostSubscription,
    PostUser,
    OpaqueKey,
    SubscriptionInfo,
    UserInfo,
)
from app.integrations.lbx.preparation_profile import PreparationProfile
from app.integrations.lbx.stand import Stand043Permission
from app.integrations.lbx.read_result import LbxRead as LbxRead
from app.integrations.lbx.server_session import _Session, ensure_session
from app.integrations.lbx.transport import _Attempts, _Retryable, request_once, retry_after


API_PATH = "/api/rest/v1"
T = TypeVar("T")


def _require_identity(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise LbxScopeMismatch()


class LbxServerClient:
    """One scoped async Server API pool; selected reads and non-payment CREATE.

    Construct explicitly for source work, never from a DB-only query/startup
    dependency. There is no construction-time HTTP, external catalog cache or
    account routing. The caller owns PreflightAdmission and passes its SAME
    admitted budget through every Kernel/LBX read and subsequent normalization.
    A logical read is one counted source task, including lock/auth/retry/close.
    """

    def __init__(
        self,
        configuration: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        stand_permission: Stand043Permission | None = None,
    ) -> None:
        if not configuration.lbx_base_url:
            raise LbxNotConfigured()
        self._configuration = configuration
        self._stand_permission = stand_permission
        self._session: _Session | None = None
        self._session_lock = asyncio.Lock()
        self._closed = False
        # Recording transports authorize only explicit regression-test profiles.
        # Real CREATE additionally requires the narrow configured stand capability.
        self._recorded_transport = isinstance(transport, httpx.MockTransport)
        self._http = httpx.AsyncClient(
            base_url=configuration.lbx_base_url,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache, no-store",
            },
            follow_redirects=False,
            trust_env=False,
            verify=True,
            limits=httpx.Limits(
                max_connections=configuration.preflight_max_active,
                max_keepalive_connections=configuration.preflight_max_active,
            ),
            transport=transport,
        )

    async def list_tariffs(self, *, tariff_id: int, budget: PreflightBudget) -> LbxRead[list[LbxTariff]]:
        _require_identity(tariff_id)
        result = await self._read(
            "/tariffs", LbxEnvelope[list[LbxTariff]], budget=budget, body={"tariff_id": tariff_id}
        )
        if any(item.tariff_id != tariff_id for item in result) or len(result) > 1:
            raise LbxScopeMismatch()
        return self._scoped(result, tariff_id=tariff_id)

    async def get_tariff(self, *, tariff_id: int, budget: PreflightBudget) -> LbxRead[LbxTariff]:
        _require_identity(tariff_id)
        result = await self._read(f"/tariffs/{tariff_id}", LbxEnvelope[LbxTariff], budget=budget)
        if result.tariff_id != tariff_id:
            raise LbxScopeMismatch()
        return self._scoped(result, tariff_id=tariff_id)

    async def list_tariff_periods(self, *, tariff_id: int, budget: PreflightBudget) -> LbxRead[list[LbxTariffPeriod]]:
        _require_identity(tariff_id)
        result = await self._read(f"/tariffs/{tariff_id}/periods", LbxEnvelope[list[LbxTariffPeriod]], budget=budget)
        if len({item.tariff_period_id for item in result}) != len(result):
            raise LbxResponseInvalid()
        return self._scoped(result, tariff_id=tariff_id)

    async def list_tariff_services(self, *, tariff_id: int, budget: PreflightBudget) -> LbxRead[list[LbxTariffService]]:
        _require_identity(tariff_id)
        result = await self._read(f"/tariffs/{tariff_id}/services", LbxEnvelope[list[LbxTariffService]], budget=budget)
        if any(item.tariff_id != tariff_id for item in result):
            raise LbxScopeMismatch()
        if len({item.tariff_service_id for item in result}) != len(result):
            raise LbxResponseInvalid()
        return self._scoped(result, tariff_id=tariff_id)

    async def list_service_prices(
        self, *, tariff_id: int, tariff_service_id: int, budget: PreflightBudget
    ) -> LbxRead[list[LbxServicePrice]]:
        _require_identity(tariff_id)
        _require_identity(tariff_service_id)
        result = await self._read(
            f"/tariffs/{tariff_id}/services/{tariff_service_id}/prices",
            LbxEnvelope[list[LbxServicePrice]],
            budget=budget,
        )
        if len({item.price_id for item in result}) != len(result):
            raise LbxResponseInvalid()
        return self._scoped(result, tariff_id=tariff_id, tariff_service_id=tariff_service_id)

    def _scoped(self, value: T, *, tariff_id: int, tariff_service_id: int | None = None) -> LbxRead[T]:
        return LbxRead(
            external_billing_account_id=self._configuration.lbx_external_billing_account_id,
            tariff_id=tariff_id,
            tariff_service_id=tariff_service_id,
            observed_at=datetime.now(UTC),
            value=value,
        )

    def require_preparation_profile(self, profile: PreparationProfile) -> None:
        config = self._configuration
        if profile.is_stand:
            if self._stand_permission is None or self._stand_permission != Stand043Permission.configured(config):
                raise LbxPreparationBlocked()
        elif config.app_env != AppEnv.TEST or not self._recorded_transport:
            raise LbxPreparationBlocked()
        profile.require_account(
            account_id=config.lbx_external_billing_account_id,
            origin=config.lbx_base_url,
            username=config.lbx_server_username,
        )
        if (
            config.lbx_seller_organization_id is not None
            and config.lbx_seller_organization_id != profile.organization_id
        ):
            raise LbxPreparationBlocked()

    def require_financial_approval(self) -> None:
        if self._stand_permission is not None:
            self._stand_permission.require_financial_approval()

    async def get_user(self, *, user_id: int, budget: PreflightBudget) -> UserInfo:
        _require_identity(user_id)
        result = await self._read(f"/users/{user_id}", LbxEnvelope[UserInfo], budget=budget)
        if result.user_id != user_id:
            raise LbxScopeMismatch()
        if result.password:
            raise LbxResponseInvalid()
        return result

    async def get_agreement(self, *, agreement_id: int, budget: PreflightBudget) -> AgreementInfo:
        _require_identity(agreement_id)
        result = await self._read(f"/agreements/{agreement_id}", LbxEnvelope[AgreementInfo], budget=budget)
        if result.agreement_id != agreement_id:
            raise LbxScopeMismatch()
        return result

    async def get_subscription(self, *, subscription_id: int, budget: PreflightBudget) -> SubscriptionInfo:
        _require_identity(subscription_id)
        result = await self._read(f"/subscriptions/{subscription_id}", LbxEnvelope[SubscriptionInfo], budget=budget)
        if result.subscription_id != subscription_id:
            raise LbxScopeMismatch()
        return result

    def _bounded_candidates(self, identities: list[int]) -> None:
        # No provider pagination/visibility SLA is invented. At the local cap,
        # completeness is unknown even if this page happens to end there.
        if len(identities) >= self._configuration.lbx_discovery_max_items:
            raise LbxResponseInvalid()
        if len(set(identities)) != len(identities):
            raise LbxScopeMismatch()

    async def discover_users(self, *, outer_id: str, budget: PreflightBudget) -> tuple[int, ...]:
        # Validate opaque-key syntax before any source I/O; no PII search.
        try:
            key = TypeAdapter(OpaqueKey).validate_python(outer_id, strict=True)
        except ValueError:
            raise LbxScopeMismatch() from None
        rows = await self._read(
            "/users", LbxEnvelope[list[UserInfo]], budget=budget, body={"outer_id": key, "show_passwords": False}
        )
        self._bounded_candidates([row.user_id for row in rows])
        if any(row.outer_id != key or row.password for row in rows):
            raise LbxScopeMismatch()
        return tuple(row.user_id for row in rows)

    async def discover_agreements(self, *, user_id: int, budget: PreflightBudget) -> tuple[int, ...]:
        _require_identity(user_id)
        rows = await self._read(
            "/agreements", LbxEnvelope[list[AgreementInfo]], budget=budget, body={"user_id": user_id}
        )
        self._bounded_candidates([row.agreement_id for row in rows])
        if any(row.user_id != user_id for row in rows):
            raise LbxScopeMismatch()
        return tuple(row.agreement_id for row in rows)

    async def discover_subscriptions(self, *, user_id: int, budget: PreflightBudget) -> tuple[int, ...]:
        _require_identity(user_id)
        rows = await self._read(
            "/subscriptions", LbxEnvelope[list[SubscriptionInfo]], budget=budget, body={"user_id": user_id}
        )
        self._bounded_candidates([row.subscription_id for row in rows])
        # The list has no user_id field. A filter alone is not owner proof.
        for agreement_id in {row.agreement_id for row in rows}:
            if agreement_id is None:
                raise LbxResponseInvalid()
            agreement = await self.get_agreement(agreement_id=agreement_id, budget=budget)
            if agreement.user_id != user_id:
                raise LbxScopeMismatch()
        return tuple(row.subscription_id for row in rows)

    async def create_user(
        self, command: PostUser, *, profile: PreparationProfile, budget: PreflightBudget
    ) -> CreatedUser:
        self.require_preparation_profile(profile)
        profile.require_customer(command)
        if profile.is_stand:
            command = command.with_technical_credentials()
        return await self._create(
            "/users",
            CreateEnvelope[CreatedUser],
            command.request_document(),
            budget,
            success_statuses=frozenset({200, 201}) if profile.is_stand else frozenset({201}),
        )

    async def prepare_create(self, *, budget: PreflightBudget) -> None:
        """Acquire Server authentication before Application commits a send claim."""

        async def authenticate() -> None:
            with private_http_diagnostics():
                await self._ensure_session(
                    _Attempts(self._configuration.lbx_max_get_attempts), budget, allow_refresh=True
                )

        await budget.run(authenticate)

    async def create_agreement(
        self, command: PostAgreement, *, profile: PreparationProfile, budget: PreflightBudget
    ) -> CreatedAgreement:
        self.require_preparation_profile(profile)
        profile.require_agreement(command)
        body = command.model_dump(mode="json", exclude_none=True)
        # 043 does not document debt_threshold. Financial policy is independent
        # evidence. Preserve the explicit numeric zero only for old recordings.
        if profile.is_stand:
            body.pop("debt_threshold", None)
        else:
            body["debt_threshold"] = 0
        return await self._create(
            "/agreements",
            CreateEnvelope[CreatedAgreement],
            body,
            budget,
            success_statuses=frozenset({200, 201}) if profile.is_stand else frozenset({201}),
        )

    async def create_subscription(
        self,
        command: PostSubscription,
        *,
        profile: PreparationProfile,
        offer: SelectedCommercialOffer,
        budget: PreflightBudget,
    ) -> CreatedSubscription:
        self.require_preparation_profile(profile)
        profile.require_subscription(command, offer)
        if profile.is_stand:
            assert self._stand_permission is not None
            self._stand_permission.require_financial_approval()
            profile.require_financial_policy()
        return await self._create(
            "/subscriptions",
            CreateEnvelope[CreatedSubscription],
            command.model_dump(exclude_none=True),
            budget,
            success_statuses=frozenset({200, 201}),
        )

    async def _create(
        self,
        path: str,
        model: type[CreateEnvelope[T]],
        body: dict[str, Any],
        budget: PreflightBudget,
        *,
        success_statuses: frozenset[int] = frozenset({201}),
    ) -> T:
        if self._closed:
            raise LbxClosed()
        # Serialization is safe-before-send. No deferred JSON encoding failure
        # can be confused with a provider-side effect.
        content = json.dumps(body, allow_nan=False, separators=(",", ":")).encode("utf-8")
        possible_send = False

        async def create() -> T:
            nonlocal possible_send
            with private_http_diagnostics():
                attempts = _Attempts(self._configuration.lbx_max_get_attempts)
                session = await self._ensure_session(attempts, budget, allow_refresh=True)
                budget.check()
                possible_send = True
                # One exchange. No GET reauth/retry loop, even for 401/429/5xx.
                return await self._request_once(
                    path,
                    model,
                    _Attempts(1),
                    budget,
                    headers={
                        "Authorization": f"Bearer {session.token.get_secret_value()}",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                    content=content,
                    success_statuses=success_statuses,
                )

        try:
            return await budget.run(create)
        except _Retryable as retry:
            if possible_send:
                raise LbxCreateUncertain() from None
            raise retry.failure from None
        except BaseException:
            # Includes cancellation/deadline/body/cleanup failure after send.
            # Step 4 must retain its committed durable possible-send fence.
            if possible_send:
                raise LbxCreateUncertain() from None
            raise

    async def _read(
        self,
        path: str,
        model: type[LbxEnvelope[T]],
        *,
        budget: PreflightBudget,
        body: dict[str, Any] | None = None,
    ) -> T:
        if self._closed:
            raise LbxClosed()

        async def read() -> T:
            with private_http_diagnostics():
                return await self._read_with_session(path, model, budget, body)

        return await budget.run(read)

    async def _read_with_session(
        self,
        path: str,
        model: type[LbxEnvelope[T]],
        budget: PreflightBudget,
        body: dict[str, Any] | None,
    ) -> T:
        attempts = _Attempts(self._configuration.lbx_max_get_attempts)
        reauthenticated = False
        previous_session: _Session | None = None
        while True:
            budget.check()
            try:
                session = await self._ensure_session(attempts, budget, allow_refresh=not reauthenticated)
                if previous_session is not None and session is not previous_session:
                    if reauthenticated:
                        raise LbxAuthenticationFailed()
                    reauthenticated = True
                previous_session = session
                try:
                    return await self._request_once(
                        path,
                        model,
                        attempts,
                        budget,
                        headers={"Authorization": f"Bearer {session.token.get_secret_value()}"},
                        body=body,
                    )
                except LbxAuthenticationFailed:
                    # A stale 401 must never invalidate another caller's fresh
                    # token. No business GET receives more than one reauth.
                    if self._session is session:
                        self._session = None
                    if reauthenticated:
                        raise
            except _Retryable as retry:
                if attempts.used >= attempts.limit:
                    raise retry.failure from None
                config = self._configuration
                delay = retry.retry_after_seconds
                if delay is None:
                    delay = config.lbx_retry_delay_seconds * (2 ** (attempts.used - 1))
                await asyncio.sleep(min(delay, config.lbx_max_retry_delay_seconds))
                budget.check()

    async def _ensure_session(self, attempts: _Attempts, budget: PreflightBudget, *, allow_refresh: bool) -> _Session:
        return await ensure_session(self, attempts, budget, allow_refresh=allow_refresh)

    def _retry_after(self, value: str | None) -> float | None:
        return retry_after(value, maximum=self._configuration.lbx_max_retry_delay_seconds)

    async def _request_once(
        self,
        path: str,
        model: type[LbxEnvelope[T]] | type[CreateEnvelope[T]],
        attempts: _Attempts,
        budget: PreflightBudget,
        *,
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        auth: httpx.Auth | None = None,
        method: str = "GET",
        content: bytes | None = None,
        success_statuses: frozenset[int] = frozenset({200}),
    ) -> T:
        return await request_once(
            self._http,
            self._configuration,
            API_PATH + path,
            model,
            attempts,
            budget,
            retry_after=self._retry_after,
            headers=headers,
            body=body,
            auth=auth,
            method=method,
            content=content,
            success_statuses=success_statuses,
        )

    async def aclose(self) -> None:
        """Owner stops/drains its PreflightAdmission BEFORE closing this pool.

        If admission reports cleanup pending, retain this client until that
        counted source task stops; never reuse resources underneath cleanup.
        """
        self._closed = True
        self._session = None
        with private_http_diagnostics():
            await self._http.aclose()
