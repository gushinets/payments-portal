from __future__ import annotations

from fastapi import APIRouter, Response

from app.core.observability import metrics_response


metrics_router = APIRouter(prefix="/metrics", tags=["metrics"])


@metrics_router.get("", include_in_schema=False)
def metrics() -> Response:
    return metrics_response()
