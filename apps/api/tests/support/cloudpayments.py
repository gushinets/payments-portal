from __future__ import annotations

from fastapi import FastAPI

from app.integrations.cloudpayments.adapter import CloudPaymentsAdapter
from app.integrations.cloudpayments.router import router as cloudpayments_router
from app.main import create_app


def create_retained_cloudpayments_test_app() -> FastAPI:
    """Compose the retained CloudPayments integration only for direct tests."""
    app = create_app()
    cloudpayments_adapter = CloudPaymentsAdapter()
    app.state.payment_provider_registry.register(cloudpayments_adapter)
    app.state.cloudpayments_adapter = cloudpayments_adapter
    app.include_router(cloudpayments_router)
    return app
