from fastapi import APIRouter
from app.domains.observability.health import health_router
from app.domains.observability.metrics import metrics_router
from app.domains.ordering.router import ordering_router


api_router = APIRouter(prefix="/api")
observability_router = APIRouter()

observability_router.include_router(metrics_router)

api_router.include_router(health_router)
api_router.include_router(ordering_router, prefix="/v1")
