from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import app.core.database as database


canonical_health_router = APIRouter(prefix="/api/health", tags=["health"])
legacy_health_router = APIRouter(prefix="/health", tags=["health"])


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


@canonical_health_router.get("/live")
def canonical_liveness():
    return {"status": "alive"}


@canonical_health_router.get("/ready")
def canonical_readiness():
    return readiness_response()


@legacy_health_router.get("")
def legacy_health():
    return {"status": "ok"}


@legacy_health_router.get("/live")
def legacy_liveness():
    return {"status": "ok"}


@legacy_health_router.get("/ready")
def legacy_readiness():
    return readiness_response()
