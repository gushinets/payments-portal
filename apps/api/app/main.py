from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from app.core.database import SessionLocal, engine
from app.core.errors import AppError
from app.core.observability import (
    configure_observability,
    request_context_middleware,
)
from app.core.settings import AppEnv, settings
from app.domains.identity.password_reset import router as password_reset_router
from app.domains.identity.router import router as auth_router
from app.domains.legal.router import router as legal_router
from app.http.errors import app_error_handler, unexpected_failure_middleware
from app.http.health import health_router
from app.http.metrics import metrics_router
from app.infrastructure.sentry import configure_sentry
from app.legal_seed import seed_legal_documents


def _seed_legal_documents_sync() -> None:
    with SessionLocal() as db:
        seed_legal_documents(
            db,
            tenant_id=settings.instance_tenant_id,
            region=settings.instance_region,
        )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if os.getenv("SKIP_LEGAL_SEED") != "true":
        await run_in_threadpool(_seed_legal_documents_sync)

    yield


def get_cors_origins() -> tuple[str, ...]:
    if settings.app_env != AppEnv.DEVELOPMENT:
        return settings.cors_allow_origins

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
    # Middleware is inserted in reverse registration order: request context
    # must wrap the unexpected-failure boundary so it can add X-Request-ID to
    # the converted response and record request completion.
    app.middleware("http")(unexpected_failure_middleware)
    app.middleware("http")(request_context_middleware)
    app.add_exception_handler(AppError, app_error_handler)

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
    app.include_router(health_router)
    app.include_router(metrics_router)
    return app


app = create_app()
configure_observability(app, engine)
configure_sentry(settings)
