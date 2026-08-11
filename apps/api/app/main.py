from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.database import engine
from app.core.observability import (
    configure_observability,
    metrics_response,
    request_context_middleware,
)
from app.core.settings import settings
from app.domains.identity.password_reset import router as password_reset_router
from app.domains.identity.router import router as auth_router
from app.domains.legal.router import router as legal_router
from app.integrations.cloudpayments.adapter import cloudpayments_adapter
from app.integrations.cloudpayments.router import router as cloudpayments_router
from app.legal_seed import seed_legal_documents
from app.payment_providers.registry import payment_provider_registry

payment_provider_registry.register(cloudpayments_adapter)
health_router = APIRouter(prefix="/health",tags=["health"])
metrics_router = APIRouter(prefix="/metrics", tags=["metrics"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("SKIP_LEGAL_SEED") != "true":
        with SessionLocal() as db:
            seed_legal_documents(db)

    yield


@health_router.get("")
def health():
    return {
        "status": "ok",
        "cloudpayments_enabled": settings.cloudpayments_enabled,
        "cloudpayments_public_id_configured": bool(settings.cloudpayments_public_id),
    }


@health_router.get("/live")
def health_live():
    return {"status": "ok"}


@health_router.get("/ready")
def health_ready():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ready"}


@metrics_router.get("", include_in_schema=False)
def metrics():
    return metrics_response()


def get_cors_origins() -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                *settings.cors_allow_origins,
            )
        )
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="AnytoolAI Payments API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.middleware("http")(request_context_middleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router)
    app.include_router(password_reset_router)
    app.include_router(legal_router)
    app.include_router(cloudpayments_router)
    app.include_router(health_router)
    app.include_router(metrics_router)
    return app


app = create_app()
configure_observability(app, engine)
