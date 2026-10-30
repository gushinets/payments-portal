"""Authenticated bounded webhook transport; the synchronous unit owns its DB."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.core.settings import settings
from app.domains.billing.webhooks import receive_hint
from app.domains.catalog.publication import SessionFactory
from app.http.body import bounded_body
from app.http.dependencies import get_session_factory
from app.integrations.lbx.webhook import MAX_BODY_BYTES, WebhookRejected, authenticated, decode_hint

router = APIRouter(prefix="/api/billing/lbx", tags=["billing"])


class BillingWebhookResponse(BaseModel):
    delivery_id: UUID
    outcome: Literal["queued", "ignored"]


@router.post("/webhook", response_model=BillingWebhookResponse)
async def billing_webhook(
    request: Request,
    response: Response,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> BillingWebhookResponse:
    response.headers["Cache-Control"] = "no-store"
    if not settings.lbx_webhook_enabled:
        raise HTTPException(404, detail={"code": "lbx_webhook_disabled"})
    if not authenticated(
        request.headers.getlist(settings.lbx_webhook_auth_header), settings.lbx_webhook_auth_value.get_secret_value()
    ):
        raise HTTPException(401, detail={"code": "lbx_webhook_unauthorized"})
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, detail={"code": "lbx_webhook_content_type"})
    body = await bounded_body(request, max_bytes=MAX_BODY_BYTES)
    try:
        hint = decode_hint(body)
    except WebhookRejected as error:
        raise HTTPException(422, detail={"code": error.code}) from None
    receipt = await run_in_threadpool(receive_hint, factory, settings, hint)
    return BillingWebhookResponse(delivery_id=receipt.delivery_id, outcome="queued" if receipt.queued else "ignored")
