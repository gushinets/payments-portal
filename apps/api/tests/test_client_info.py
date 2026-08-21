from __future__ import annotations

from apps.api.tests.support.settings import configure_api_test_environment

configure_api_test_environment()

from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware  # noqa: E402

from app.core.client_info import ClientInfo, get_client_info  # noqa: E402


def _build_client_info_app() -> FastAPI:
    app = FastAPI()

    @app.get("/client-info")
    def read_client_info(client_info: ClientInfo = Depends(get_client_info)):
        return {
            "ip": client_info.ip,
            "user_agent": client_info.user_agent,
        }

    return app


def test_get_client_info_prefers_forwarded_for_header() -> None:
    proxy_client = TestClient(
        ProxyHeadersMiddleware(_build_client_info_app(), trusted_hosts=["testclient"]),
    )

    response = proxy_client.get(
        "/client-info",
        headers={
            "x-forwarded-for": "203.0.113.10, 198.51.100.8",
            "user-agent": "bundle3-test-agent",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ip": "203.0.113.10",
        "user_agent": "bundle3-test-agent",
    }


def test_get_client_info_falls_back_to_request_client() -> None:
    with TestClient(_build_client_info_app()) as client:
        response = client.get(
            "/client-info",
            headers={"user-agent": "bundle3-test-agent"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "ip": "testclient",
        "user_agent": "bundle3-test-agent",
    }
