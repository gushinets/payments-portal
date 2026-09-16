from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated

from apps.api.tests.support.settings import configure_api_test_environment

configure_api_test_environment()

from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import get_db  # noqa: E402
from app.http_dependencies import (  # noqa: E402
    get_current_session,
    get_payment_provider_registry,
)
from app.main import create_app  # noqa: E402
from app.models import AuthSession, User, UserStatus  # noqa: E402
from app.payment_providers.registry import PaymentProviderRegistry  # noqa: E402


@contextmanager
def dependency_overrides(
    application: FastAPI,
    overrides: dict[Callable[..., object], Callable[..., object]],
) -> Iterator[None]:
    original = application.dependency_overrides.copy()
    application.dependency_overrides.update(overrides)
    try:
        yield
    finally:
        application.dependency_overrides.clear()
        application.dependency_overrides.update(original)


def test_current_session_dependency_can_be_overridden_for_active_endpoint() -> None:
    application = create_app()
    client = TestClient(application)
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        tenant_id="anytoolai",
        region="ru",
        email="override@example.com",
        email_normalized="override@example.com",
        status=UserStatus.ACTIVE,
    )
    auth_session = AuthSession(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user_id,
        token_hash="override-token-hash",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    def override_current_session() -> tuple[User, AuthSession]:
        return user, auth_session

    with dependency_overrides(application, {get_current_session: override_current_session}):
        response = client.get("/api/auth/session")

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "user": {
            "tenant_id": "anytoolai",
            "region": "ru",
            "user_id": str(user_id),
            "email": "override@example.com",
        },
        "product_state": None,
    }
    assert application.dependency_overrides == {}
    client.close()


def test_database_dependency_can_be_overridden_without_monkeypatching() -> None:
    application = create_app()
    client = TestClient(application)
    replacement = object()

    @application.get("/_test/database-dependency")
    def database_dependency_probe(db: Annotated[object, Depends(get_db)]) -> dict[str, bool]:
        return {"is_replacement": db is replacement}

    def override_get_db() -> Iterator[object]:
        yield replacement

    with dependency_overrides(application, {get_db: override_get_db}):
        response = client.get("/_test/database-dependency")

    assert response.status_code == 200
    assert response.json() == {"is_replacement": True}
    assert application.dependency_overrides == {}
    client.close()


def test_provider_registry_dependency_can_be_overridden() -> None:
    application = create_app()
    client = TestClient(application)
    replacement = PaymentProviderRegistry()

    @application.get("/_test/provider-registry-dependency")
    def provider_registry_dependency_probe(
        registry: Annotated[PaymentProviderRegistry, Depends(get_payment_provider_registry)],
    ) -> dict[str, bool]:
        return {"is_replacement": registry is replacement}

    with dependency_overrides(application, {get_payment_provider_registry: lambda: replacement}):
        response = client.get("/_test/provider-registry-dependency")

    assert response.status_code == 200
    assert response.json() == {"is_replacement": True}
    assert application.dependency_overrides == {}
    client.close()


def test_missing_authorization_preserves_legacy_response() -> None:
    application = create_app()
    client = TestClient(application)

    response = client.get("/api/auth/session")

    assert response.status_code == 401
    assert response.json() == {"detail": "missing_session"}
    assert application.dependency_overrides == {}
    client.close()
