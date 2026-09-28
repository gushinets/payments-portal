from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
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


def readiness_response() -> JSONResponse:
    if database_is_ready():
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
def readiness() -> JSONResponse:
    return readiness_response()
