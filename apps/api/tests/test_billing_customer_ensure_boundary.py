"""Single CREATE consumer and exactly-once reporting of handled Widget failures."""

from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.core.observability import request_id_context
from app.composition.billing import AccountWidget
from app.domains.billing import router as billing_router
from app.domains.billing.contracts import BillingAccountFailure, BillingRefused
from app.http.dependencies import get_session_factory
from apps.api.tests.support.any709_step1 import step1_settings


def test_customer_create_has_one_application_caller() -> None:
    root = Path(__file__).parents[1] / "app"
    callers = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "create_user":
                callers.append(path.relative_to(root).as_posix())
    assert callers == ["composition/billing.py"]


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["failed", "auth", "pending", "recovered", "rejected", "unknown_create"])
async def test_widget_reports_only_unresolved_integration_failure_once(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    from pydantic import SecretStr

    reported = []

    async def bootstrap(*args: object, **kwargs: object) -> AccountWidget:
        if mode == "failed":
            raise BillingAccountFailure("billing_source_unavailable")
        if mode == "rejected":
            raise BillingAccountFailure("billing_source_rejected")
        if mode == "unknown_create":
            raise BillingAccountFailure("billing_customer_pending", 409)
        if mode == "auth":
            raise BillingRefused("billing_email_verification_required", 403)
        if mode == "pending":
            raise BillingRefused("billing_customer_pending", 409)
        return AccountWidget(SecretStr("opaque-widget-token"), "https://billing.test")

    def report(error: Exception, **kwargs: object) -> None:
        reported.append((error, kwargs))

    monkeypatch.setattr(billing_router, "bootstrap_account", bootstrap)
    monkeypatch.setattr(billing_router, "report_exception", report)
    monkeypatch.setattr(billing_router, "settings", step1_settings())
    app = FastAPI()
    app.include_router(billing_router.router)
    app.state.sources = object()
    app.dependency_overrides[get_session_factory] = lambda: object()
    context = request_id_context.set("safe-request")
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as client:
            response = await client.post(
                "/api/billing/widget-bootstrap", json={}, headers={"Authorization": "Bearer PRIVATE"}
            )
    finally:
        request_id_context.reset(context)
    assert len(reported) == (1 if mode in {"failed", "rejected", "unknown_create"} else 0)
    assert (
        response.status_code
        == {"failed": 503, "auth": 403, "pending": 409, "recovered": 200, "rejected": 503, "unknown_create": 409}[mode]
    )
    if reported:
        assert (
            reported[0][1]["error_code"]
            == {
                "failed": "billing_source_unavailable",
                "rejected": "billing_source_rejected",
                "unknown_create": "billing_customer_pending",
            }[mode]
        )
        assert response.json()["detail"]["request_id"] == "safe-request"
        assert "PRIVATE" not in response.text
        assert "PRIVATE" not in str(reported)
