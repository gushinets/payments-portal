from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from app.composition.backend_consumers import initialize_backend_consumers
from app.composition.sources import source_resources
from app.composition.billing_worker import billing_worker_resources
from app.composition.paid_reads import paid_read_resources
from app.composition.paid_usage import paid_usage_resources
from app.core.database import SessionLocal, engine
from app.core.errors import AppError
from app.core.observability import (
    configure_observability,
    request_context_middleware,
)
from app.core.settings import AppEnv, settings
from app.domains.billing.exhaustion_router import router as exhaustion_router
from app.domains.billing.paid_router import router as paid_access_router
from app.domains.billing.usage_router import router as paid_usage_router
from app.domains.billing.snapshot_router import router as access_snapshot_router
from app.domains.billing.router import router as billing_router
from app.domains.catalog.router import router as catalog_router
from app.domains.identity.password_reset import router as password_reset_router
from app.domains.identity.router import router as auth_router
from app.domains.identity.backend_router import router as backend_session_router
from app.http.backend_session_policy import backend_session_policy, session_validation_error
from app.domains.legal.router import router as legal_router
from app.domains.purchases.router import router as purchases_router
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
    await run_in_threadpool(initialize_backend_consumers, settings, SessionLocal)
    if os.getenv("SKIP_LEGAL_SEED") != "true":
        await run_in_threadpool(_seed_legal_documents_sync)

    async with (
        paid_read_resources(settings) as reads,
        source_resources(settings) as sources,
        paid_usage_resources(settings) as usage,
    ):
        _app.state.paid_reads = reads
        _app.state.paid_usage = usage
        _app.state.sources = sources
        async with billing_worker_resources(settings) as worker:
            _app.state.billing_worker = worker
            _app.state.billing_worker_mode = (
                "disabled" if not settings.billing_worker_enabled else "not_configured" if worker is None else "running"
            )
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

    app.middleware("http")(backend_session_policy)
    app.add_exception_handler(RequestValidationError, session_validation_error)
    app.include_router(backend_session_router)
    app.include_router(billing_router)
    app.include_router(exhaustion_router)
    app.include_router(paid_access_router)
    app.include_router(paid_usage_router)
    app.include_router(access_snapshot_router)
    app.include_router(purchases_router)
    app.include_router(catalog_router)
    app.include_router(auth_router)
    app.include_router(password_reset_router)
    app.include_router(legal_router)
    app.include_router(health_router)
    app.include_router(metrics_router)
    return app


app = create_app()
configure_observability(app, engine)
configure_sentry(settings)
