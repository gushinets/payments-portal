from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import app.core.database as database

health_router = APIRouter(prefix="/health", tags=["health"])


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
def health_live():
    return {"status": "alive"}


@health_router.get("/ready")
def health_ready():
    return readiness_response()
