"""Single CREATE consumer and exactly-once reporting of handled Widget failures."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.core.observability import request_id_context
from app.composition import billing
from app.composition.billing import AccountWidget
from app.domains.billing import router as billing_router
from app.domains.billing.contracts import BillingAccountFailure, BillingRefused, CustomerOpen
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
@pytest.mark.parametrize("stage", ["reserve", "recheck"])
async def test_widget_contention_remains_a_temporary_local_refusal(monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    from pydantic import SecretStr

    current = CustomerOpen(uuid4(), uuid4(), None, "synthetic-key", "123")
    factory = MagicMock()
    sources = MagicMock()
    sources.billing.operation.return_value.__aenter__.return_value = Mock()
    client = sources.require_lbx.return_value
    client.client_user = AsyncMock(return_value=SimpleNamespace(user_id=123, outer_id=current.outer_key))
    monkeypatch.setattr(billing, "authenticate", Mock(return_value=SimpleNamespace(id=uuid4())))
    monkeypatch.setattr(
        billing,
        "reserve_customer",
        Mock(side_effect=BillingRefused("billing_busy", 503)) if stage == "reserve" else Mock(return_value=current),
    )
    monkeypatch.setattr(billing, "ensure_customer", AsyncMock(return_value=current))
    monkeypatch.setattr(billing, "sign_widget_jwt", Mock(return_value=SecretStr("synthetic-widget-token")))
    monkeypatch.setattr(billing, "recheck_widget_session", Mock(side_effect=BillingRefused("billing_busy", 503)))
    with pytest.raises(BillingRefused) as caught:
        await billing.bootstrap_account(sources, step1_settings(), factory=factory, token="synthetic-session")
    assert type(caught.value) is BillingRefused
    assert caught.value.code == "billing_busy" and caught.value.status == 503
    client.create_user.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["failed", "auth", "pending", "busy", "recovered", "rejected", "unknown_create"])
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
        if mode == "busy":
            raise BillingRefused("billing_busy", 503)
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
        == {
            "failed": 503,
            "auth": 403,
            "pending": 409,
            "busy": 503,
            "recovered": 200,
            "rejected": 503,
            "unknown_create": 409,
        }[mode]
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
