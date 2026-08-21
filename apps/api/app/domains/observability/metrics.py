from fastapi import APIRouter
from app.core.observability import metrics_response

metrics_router = APIRouter(prefix="/metrics", tags=["metrics"])


@metrics_router.get("", include_in_schema=False)
def metrics():
    return metrics_response()
