"""Explicit account-only Widget open; no implicit GET mutation."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.composition.billing import bootstrap_account
from app.core.errors import AppError
from app.core.observability import request_id_context
from app.core.settings import settings
from app.domains.billing.contracts import BillingAccountFailure, BillingRefused
from app.domains.catalog.publication import SessionFactory
from app.http.dependencies import get_session_factory
from app.infrastructure.sentry import FailureCategory, Operation, report_exception

router = APIRouter(prefix="/api/billing", tags=["billing"])


class WidgetBootstrapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WidgetBootstrapResponse(BaseModel):
    presentation: Literal["account"]
    credential: str = Field(repr=False)
    widget_origin: str
    sdk_url: str
    serviceBaseUrl: str
    disableCreateSubscription: bool
    disableEditSubscription: bool
    disableStopSubscription: bool
    disableAutopayments: bool
    disablePayments: bool
    disableInvoiceGeneration: bool
    request_id: str


@router.post("/widget-bootstrap", response_model=WidgetBootstrapResponse)
async def widget_bootstrap(
    payload: WidgetBootstrapRequest,
    request: Request,
    response: Response,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
    authorization: Annotated[str | None, Header()] = None,
) -> WidgetBootstrapResponse:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise BillingRefused("billing_session_required", 401)
        result = await bootstrap_account(
            request.app.state.sources, settings, factory=factory, token=authorization.removeprefix("Bearer ").strip()
        )
    except AppError as error:
        if isinstance(error, BillingAccountFailure):
            report_exception(
                error,
                operation=Operation.HTTP_REQUEST,
                failure_category=FailureCategory.INTEGRATION_FAILURE,
                method="POST",
                route="/api/billing/widget-bootstrap",
                error_code=error.code,
            )
        raise HTTPException(
            status_code=error.status if isinstance(error, BillingRefused) else 503,
            detail={"code": error.code, "request_id": request_id_context.get()},
            headers={"Cache-Control": "no-store"},
        ) from None
    return WidgetBootstrapResponse(
        presentation="account",
        disableCreateSubscription=True,
        disableEditSubscription=True,
        disableStopSubscription=True,
        disableAutopayments=True,
        disablePayments=True,
        disableInvoiceGeneration=True,
        credential=result.credential.get_secret_value(),
        widget_origin=result.origin,
        sdk_url=result.origin + "/lbxwidget.js",
        serviceBaseUrl=result.origin + "/api/rest/v1/client",
        request_id=request_id_context.get(),
    )
