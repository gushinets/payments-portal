from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import app.core.database as database


health_router = APIRouter(prefix="/api/health", tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["alive"]


class ReadinessSuccessResponse(BaseModel):
    status: Literal["ready"]


class ReadinessUnavailableResponse(BaseModel):
    status: Literal["not_ready"]


def database_is_ready() -> bool:
    try:
        with database.SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


def readiness_response(worker_ready: bool = True) -> JSONResponse:
    if worker_ready and database_is_ready():
        return JSONResponse(status_code=200, content={"status": "ready"})
    return JSONResponse(status_code=503, content={"status": "not_ready"})


@health_router.get("/live")
def liveness() -> LivenessResponse:
    return LivenessResponse(status="alive")


@health_router.get(
    "/ready",
    response_model=ReadinessSuccessResponse,
    responses={503: {"model": ReadinessUnavailableResponse}},
)
def readiness(request: Request) -> JSONResponse:
    worker = getattr(request.app.state, "billing_worker", None)
    return readiness_response(worker_ready=worker is None or worker.ready)


class BillingHealthResponse(BaseModel):
    status: Literal["disabled", "not_configured", "running", "degraded", "stopping"]
    active_slots: int = 0
    cleanup_pending: int = 0
    pending_work: int = 0
    invalid_work: int = 0
    failures: int = 0
    enrolled_batches: int = 0
    oldest_due_at: str | None = None
    last_progress_at: str | None = None
    last_scan_at: str | None = None


@health_router.get("/billing")
def billing_health(request: Request) -> BillingHealthResponse:
    worker = getattr(request.app.state, "billing_worker", None)
    if worker is None:
        return BillingHealthResponse(status=getattr(request.app.state, "billing_worker_mode", "disabled"))
    return BillingHealthResponse(
        status="stopping" if worker.stopping else "running" if worker.healthy else "degraded",
        active_slots=sum(admission.active_count for admission in worker.admissions.values()),
        cleanup_pending=sum(admission.cleanup_pending_count for admission in worker.admissions.values()),
        pending_work=worker.pending,
        invalid_work=worker.invalid,
        failures=worker.failures,
        enrolled_batches=worker.enrolled_batches,
        oldest_due_at=worker.oldest_due_at.isoformat() if worker.oldest_due_at else None,
        last_progress_at=worker.last_progress_at.isoformat() if worker.last_progress_at else None,
        last_scan_at=worker.last_scan_at.isoformat() if worker.last_scan_at else None,
    )
