from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

from fastapi.routing import APIRoute

from app.http_dependencies import get_raw_request_body
from app.integrations.cloudpayments.adapter import CloudPaymentsAdapter
from app.integrations.cloudpayments.router import router as cloudpayments_router
from app.main import app
from scripts.repo import (
    check_persistence_transaction_ownership,
    check_python_boundaries,
)


def write_module(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_retained_cloudpayments_webhook_keeps_shared_async_body_and_sync_processing_boundary() -> None:
    route = next(
        route
        for route in cloudpayments_router.routes
        if isinstance(route, APIRoute) and route.path == "/api/cloudpayments/{endpoint}"
    )
    dependencies = {dependency.name: dependency.call for dependency in route.dependant.dependencies}

    assert "/api/cloudpayments/{endpoint}" not in app.openapi()["paths"]
    assert not inspect.iscoroutinefunction(route.endpoint)
    assert dependencies["raw_body"] is get_raw_request_body
    assert inspect.iscoroutinefunction(get_raw_request_body)
    assert not inspect.iscoroutinefunction(CloudPaymentsAdapter.normalize_webhook_request)


def test_ast_import_forms_are_rejected_with_actionable_errors(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "apps/api/app/core/settings.py",
        "import app.integrations.cloudpayments as provider\n",
    )
    write_module(
        tmp_path,
        "apps/api/app/domains/legal/service.py",
        "from app import integrations\n",
    )

    errors = check_python_boundaries(tmp_path)

    assert any(
        "apps/api/app/core/settings.py:1 imports app.integrations.cloudpayments" in error
        and "core dependency direction" in error
        and "move the dependency" in error
        for error in errors
    )
    assert any(
        "apps/api/app/domains/legal/service.py:1 imports app.integrations" in error
        and "domain-to-integration dependency" in error
        and "inject a provider-independent service" in error
        for error in errors
    )


def test_core_to_payment_provider_dependency_is_rejected(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "apps/api/app/core/errors.py",
        "from app.payment_providers import errors\n",
    )

    assert check_python_boundaries(tmp_path) == [
        "apps/api/app/core/errors.py:1 imports app.payment_providers; "
        "violates core dependency direction; move the dependency to wiring or "
        "shared core infrastructure (see ARCHITECTURE.md)"
    ]


def test_relative_router_import_is_rejected(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "apps/api/app/domains/legal/router.py",
        "from ..identity import router\n",
    )

    assert check_python_boundaries(tmp_path) == [
        "apps/api/app/domains/legal/router.py:1 imports app.domains.identity.router; "
        "violates router-to-router dependency; import a service, contract, or session "
        "dependency instead of a router (see ARCHITECTURE.md)"
    ]


def test_layer_specific_router_rules_are_enforced(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "apps/api/app/domains/legal/service.py",
        "from app.domains.identity import router\n",
    )
    write_module(
        tmp_path,
        "apps/api/app/integrations/cloudpayments/handler.py",
        "from app.domains.billing import router\n",
    )

    errors = check_python_boundaries(tmp_path)

    assert any("domain service/model-to-router dependency" in error for error in errors)
    assert any("integration-to-domain-router dependency" in error for error in errors)


def test_domain_service_trees_reject_fastapi_and_starlette_dependencies(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "apps/api/app/domains/identity/services/checkout.py",
        "from fastapi import HTTPException\n",
    )
    write_module(
        tmp_path,
        "apps/api/app/domains/billing/service/reconciliation.py",
        "from starlette.requests import Request\n",
    )

    errors = check_python_boundaries(tmp_path)

    assert any(
        "apps/api/app/domains/identity/services/checkout.py:1 imports fastapi" in error
        and "domain service/application-to-transport dependency" in error
        for error in errors
    )
    assert any(
        "apps/api/app/domains/billing/service/reconciliation.py:1 imports starlette" in error
        and "domain service/application-to-transport dependency" in error
        for error in errors
    )


def test_domain_application_trees_reject_fastapi_and_starlette_dependencies(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "apps/api/app/domains/identity/application/checkout.py",
        "from fastapi import HTTPException\n",
    )
    write_module(
        tmp_path,
        "apps/api/app/domains/billing/application/reconciliation.py",
        "from starlette.requests import Request\n",
    )

    errors = check_python_boundaries(tmp_path)

    assert any(
        "apps/api/app/domains/identity/application/checkout.py:1 imports fastapi" in error
        and "domain service/application-to-transport dependency" in error
        for error in errors
    )
    assert any(
        "apps/api/app/domains/billing/application/reconciliation.py:1 imports starlette" in error
        and "domain service/application-to-transport dependency" in error
        for error in errors
    )


@pytest.mark.parametrize(
    "relative",
    (
        "apps/api/app/domains/identity/services/account.py",
        "apps/api/app/domains/legal/service.py",
        "apps/api/app/domains/billing/service/catalog.py",
    ),
)
def test_refactored_application_surfaces_reject_direct_query_composition(
    tmp_path: Path,
    relative: str,
) -> None:
    write_module(
        tmp_path,
        relative,
        "from sqlalchemy import select\n"
        "from sqlalchemy.orm import Session\n\n"
        "def load(db: Session) -> object:\n"
        "    db.execute(select(object))\n"
        "    db.get(object, 1)\n"
        "    db.scalar(select(object))\n"
        "    db.scalars(select(object))\n"
        "    return db.query(object).first()\n",
    )

    errors = check_python_boundaries(tmp_path)

    assert any(
        error.startswith(f"{relative}:1 imports sqlalchemy") and "refactored Application persistence boundary" in error
        for error in errors
    )
    for line, method in (
        (5, "execute"),
        (6, "get"),
        (7, "scalar"),
        (8, "scalars"),
        (9, "query"),
    ):
        assert any(
            error.startswith(f"{relative}:{line} calls SQLAlchemy Session.{method}()")
            and "refactored Application code" in error
            for error in errors
        )


def test_refactored_application_surfaces_allow_transaction_orchestration(
    tmp_path: Path,
) -> None:
    write_module(
        tmp_path,
        "apps/api/app/domains/identity/services/auth.py",
        "from sqlalchemy.orm import Session\n\n"
        "def save(db: Session, entity: object) -> None:\n"
        "    db.add(entity)\n"
        "    db.flush()\n"
        "    db.refresh(entity)\n"
        "    db.commit()\n"
        "    db.rollback()\n"
        "    db.delete(entity)\n",
    )

    assert check_python_boundaries(tmp_path) == []


def test_active_domain_presentation_rejects_persistence_orchestration(tmp_path: Path) -> None:
    relative = "apps/api/app/domains/identity/http_api.py"
    write_module(
        tmp_path,
        relative,
        "from fastapi import APIRouter as Router\n"
        "from sqlalchemy.orm import Session\n"
        "from app.infrastructure.queries import identity\n"
        "from app.infrastructure.persistence import password_reset\n\n"
        "api = Router()\n\n"
        "@api.get('/users')\n"
        "def list_users(db: Session) -> object:\n"
        "    db.add(object())\n"
        "    db.commit()\n"
        "    return db.query(object).all()\n",
    )

    errors = check_python_boundaries(tmp_path)

    assert any(
        error.startswith(f"{relative}:3 imports app.infrastructure.queries")
        and "HTTP Presentation persistence boundary" in error
        for error in errors
    )
    assert any(
        error.startswith(f"{relative}:4 imports app.infrastructure.persistence")
        and "HTTP Presentation persistence boundary" in error
        for error in errors
    )
    assert any(
        error.startswith(f"{relative}:10 calls SQLAlchemy Session.add()") and "active domain Presentation" in error
        for error in errors
    )
    assert any(
        error.startswith(f"{relative}:11 calls SQLAlchemy Session.commit()") and "active domain Presentation" in error
        for error in errors
    )
    assert any(
        error.startswith(f"{relative}:12 calls SQLAlchemy Session.query()") and "active domain Presentation" in error
        for error in errors
    )


def test_active_domain_presentation_assignment_router_alias_keeps_boundary(
    tmp_path: Path,
) -> None:
    relative = "apps/api/app/domains/identity/http_api.py"
    write_module(
        tmp_path,
        relative,
        "from fastapi import APIRouter\n"
        "from sqlalchemy.orm import Session\n"
        "from app.infrastructure.queries import identity\n\n"
        "RouterFactory = APIRouter\n"
        "router = RouterFactory()\n\n"
        "def list_users(db: Session) -> object:\n"
        "    return db.query(object).all()\n",
    )

    errors = check_python_boundaries(tmp_path)

    assert any(
        error.startswith(f"{relative}:3 imports app.infrastructure.queries")
        and "HTTP Presentation persistence boundary" in error
        for error in errors
    )
    assert any(
        error.startswith(f"{relative}:9 calls SQLAlchemy Session.query()") and "active domain Presentation" in error
        for error in errors
    )


def test_active_domain_presentation_rejects_sqlalchemy_query_imports(tmp_path: Path) -> None:
    relative = "apps/api/app/domains/identity/http_api.py"
    write_module(
        tmp_path,
        relative,
        "from fastapi import APIRouter\n"
        "from sqlalchemy import select\n"
        "from sqlalchemy.orm import Session\n\n"
        "router = APIRouter()\n\n"
        "def list_users(db: Session) -> object:\n"
        "    return object()\n",
    )

    errors = check_python_boundaries(tmp_path)

    assert any(
        error.startswith(f"{relative}:2 imports sqlalchemy")
        and "HTTP Presentation persistence boundary" in error
        for error in errors
    )


def test_http_dependencies_rejects_persistence_orchestration_without_api_router(tmp_path: Path) -> None:
    relative = "apps/api/app/http_dependencies.py"
    write_module(
        tmp_path,
        relative,
        "from sqlalchemy.orm import Session\n"
        "from sqlalchemy import select\n"
        "from app.infrastructure.persistence import password_reset\n\n"
        "def dependency(db: Session) -> object:\n"
        "    return db.execute('SELECT 1')\n",
    )

    errors = check_python_boundaries(tmp_path)

    assert any(
        error.startswith(f"{relative}:2 imports sqlalchemy")
        and "HTTP Presentation persistence boundary" in error
        for error in errors
    )
    assert any(
        error.startswith(f"{relative}:3 imports app.infrastructure.persistence")
        and "HTTP Presentation persistence boundary" in error
        for error in errors
    )
    assert any(
        error.startswith(f"{relative}:6 calls SQLAlchemy Session.execute()")
        and "HTTP dependency composition" in error
        for error in errors
    )


def test_active_domain_presentation_allows_session_di_and_inward_delegation(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "apps/api/app/domains/identity/http_api.py",
        "from fastapi import APIRouter, Depends\n"
        "from sqlalchemy.orm import Session\n"
        "from app.core.database import get_db\n"
        "from app.domains.identity.services.account import load_account_session\n\n"
        "router = APIRouter()\n\n"
        "@router.get('/session')\n"
        "def get_session(db: Session = Depends(get_db)) -> object:\n"
        "    return load_account_session(db, user=object(), product_code=None)\n",
    )

    assert check_python_boundaries(tmp_path) == []


@pytest.mark.parametrize("relative", ("apps/api/app/integrations/cloudpayments/router.py", "apps/api/app/health.py"))
def test_non_domain_api_router_is_not_active_domain_presentation(tmp_path: Path, relative: str) -> None:
    write_module(
        tmp_path,
        relative,
        "from fastapi import APIRouter\n"
        "from sqlalchemy.orm import Session\n"
        "from app.infrastructure.queries import orders\n\n"
        "router = APIRouter()\n\n"
        "def retained_handler(db: Session) -> object:\n"
        "    return db.query(object).first()\n",
    )

    assert check_python_boundaries(tmp_path) == []


@pytest.mark.parametrize("transport_import", ("from fastapi import Request", "from starlette.requests import Request"))
def test_payment_provider_registry_rejects_transport_dependencies(tmp_path: Path, transport_import: str) -> None:
    relative = "apps/api/app/payment_providers/registry.py"
    write_module(tmp_path, relative, f"{transport_import}\n")

    errors = check_python_boundaries(tmp_path)

    assert len(errors) == 1
    assert errors[0].startswith(f"{relative}:1 imports ")
    assert "payment-provider registry transport boundary" in errors[0]
    assert "keep request-state access in app.http_dependencies" in errors[0]


def test_application_modules_must_import_sentry_through_the_adapter(tmp_path: Path) -> None:
    forbidden_imports = {
        "apps/api/app/domains/billing/application/renewal.py": "import sentry_sdk\n",
        "apps/api/app/payment_providers/errors.py": "from sentry_sdk import capture_exception\n",
        "apps/api/app/integrations/cloudpayments/client.py": ("from sentry_sdk.integrations import Integration\n"),
        "apps/api/app/domains/billing/router.py": "import sentry_sdk.client\n",
        "apps/api/app/commands/expire_subscriptions.py": ("from sentry_sdk.scope import Scope\n"),
    }
    for relative, source in forbidden_imports.items():
        write_module(tmp_path, relative, source)

    errors = check_python_boundaries(tmp_path)

    for relative in forbidden_imports:
        assert any(
            error.startswith(f"{relative}:1 imports sentry_sdk")
            and "Sentry SDK adapter boundary" in error
            and "import app.infrastructure.sentry instead" in error
            for error in errors
        )


def test_sentry_infrastructure_adapter_may_import_the_sdk(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "apps/api/app/infrastructure/sentry.py",
        "import sentry_sdk\nfrom sentry_sdk.integrations.atexit import AtexitIntegration\n",
    )

    assert check_python_boundaries(tmp_path) == []


def test_persistence_infrastructure_accepts_sqlalchemy_models_and_neutral_core(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "apps/api/app/infrastructure/queries/identity.py",
        "from sqlalchemy.orm import Session\nfrom app.models import User\nfrom app.core.time import utc_now\n",
    )
    write_module(
        tmp_path,
        "apps/api/app/infrastructure/persistence/password_reset.py",
        "from sqlalchemy import text\nfrom sqlalchemy.orm import Session\nfrom app.models import MagicLinkToken\n",
    )

    assert check_python_boundaries(tmp_path) == []


def test_persistence_infrastructure_rejects_domain_dependencies(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "apps/api/app/infrastructure/queries/legal.py",
        "from app.domains.legal import service\n",
    )

    assert check_python_boundaries(tmp_path) == [
        "apps/api/app/infrastructure/queries/legal.py:1 imports app.domains.legal; "
        "violates persistence dependency direction; keep persistence "
        "dependent only on models and neutral infrastructure (see ARCHITECTURE.md)"
    ]


def test_persistence_infrastructure_rejects_transport_dependencies(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "apps/api/app/infrastructure/queries/identity.py",
        "from fastapi import Depends\n",
    )
    write_module(
        tmp_path,
        "apps/api/app/infrastructure/persistence/password_reset.py",
        "from starlette.requests import Request\n",
    )

    errors = check_python_boundaries(tmp_path)

    assert any(
        "apps/api/app/infrastructure/queries/identity.py:1 imports fastapi" in error
        and "persistence dependency direction" in error
        for error in errors
    )
    assert any(
        "apps/api/app/infrastructure/persistence/password_reset.py:1 imports starlette.requests" in error
        and "persistence dependency direction" in error
        for error in errors
    )


def test_persistence_infrastructure_rejects_integration_and_payment_provider_dependencies(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "apps/api/app/infrastructure/queries/payments.py",
        "from app.integrations.cloudpayments import adapter\n",
    )
    write_module(
        tmp_path,
        "apps/api/app/infrastructure/persistence/orders.py",
        "from app.payment_providers import registry\n",
    )

    errors = check_python_boundaries(tmp_path)

    assert any(
        "apps/api/app/infrastructure/queries/payments.py:1 imports app.integrations.cloudpayments" in error
        and "persistence dependency direction" in error
        for error in errors
    )
    assert any(
        "apps/api/app/infrastructure/persistence/orders.py:1 imports app.payment_providers" in error
        and "persistence dependency direction" in error
        for error in errors
    )


@pytest.mark.parametrize(
    ("relative", "method"),
    (
        ("apps/api/app/infrastructure/queries/orders.py", "begin"),
        ("apps/api/app/infrastructure/queries/orders.py", "commit"),
        ("apps/api/app/infrastructure/queries/orders.py", "rollback"),
        ("apps/api/app/infrastructure/persistence/orders.py", "begin"),
        ("apps/api/app/infrastructure/persistence/orders.py", "commit"),
        ("apps/api/app/infrastructure/persistence/orders.py", "rollback"),
    ),
)
def test_persistence_helpers_reject_outer_session_transaction_ownership(
    tmp_path: Path,
    relative: str,
    method: str,
) -> None:
    write_module(
        tmp_path,
        relative,
        f"from sqlalchemy.orm import Session\n\ndef persist(db: Session) -> None:\n    db.{method}()\n",
    )

    assert check_persistence_transaction_ownership(tmp_path) == [
        f"{relative}:4 calls SQLAlchemy Session.{method}(); focused persistence "
        "helpers must not own or finalize the outer business transaction "
        "(see ARCHITECTURE.md)"
    ]


def test_persistence_transaction_guard_tracks_aliased_session_types(tmp_path: Path) -> None:
    relative = "apps/api/app/infrastructure/queries/orders.py"
    write_module(
        tmp_path,
        relative,
        "from sqlalchemy.orm import Session as DatabaseSession\n\n"
        "def persist(db: DatabaseSession) -> None:\n"
        "    db.commit()\n",
    )

    assert check_persistence_transaction_ownership(tmp_path) == [
        f"{relative}:4 calls SQLAlchemy Session.commit(); focused persistence "
        "helpers must not own or finalize the outer business transaction "
        "(see ARCHITECTURE.md)"
    ]


def test_persistence_transaction_guard_tracks_unaliased_sqlalchemy_import(tmp_path: Path) -> None:
    relative = "apps/api/app/infrastructure/queries/orders.py"
    write_module(
        tmp_path,
        relative,
        "import sqlalchemy\n\ndef persist(db: sqlalchemy.orm.Session) -> None:\n    db.commit()\n",
    )

    assert check_persistence_transaction_ownership(tmp_path) == [
        f"{relative}:4 calls SQLAlchemy Session.commit(); focused persistence "
        "helpers must not own or finalize the outer business transaction "
        "(see ARCHITECTURE.md)"
    ]


def test_persistence_transaction_guard_tracks_simple_session_assignment(tmp_path: Path) -> None:
    relative = "apps/api/app/infrastructure/queries/orders.py"
    write_module(
        tmp_path,
        relative,
        "from sqlalchemy.orm import Session\n\ndef persist(db: Session) -> None:\n    alias = db\n    alias.commit()\n",
    )

    assert check_persistence_transaction_ownership(tmp_path) == [
        f"{relative}:5 calls SQLAlchemy Session.commit(); focused persistence "
        "helpers must not own or finalize the outer business transaction "
        "(see ARCHITECTURE.md)"
    ]


def test_persistence_transaction_guard_forgets_reassigned_session_alias(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "apps/api/app/infrastructure/queries/orders.py",
        "from sqlalchemy.orm import Session\n\n"
        "class SomeOtherObject:\n"
        "    def commit(self) -> None: ...\n\n"
        "def persist(db: Session) -> None:\n"
        "    alias = db\n"
        "    alias = SomeOtherObject()\n"
        "    alias.commit()\n",
    )

    assert check_persistence_transaction_ownership(tmp_path) == []


def test_persistence_transaction_guard_allows_owned_database_mechanics(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "apps/api/app/infrastructure/persistence/orders.py",
        "from sqlalchemy import text\n"
        "from sqlalchemy.orm import Session\n\n"
        "def persist(db: Session) -> None:\n"
        "    db.flush()\n"
        "    with db.begin_nested():\n"
        "        db.execute(text('SELECT 1'))\n"
        "    db.query(object).with_for_update().first()\n",
    )

    assert check_persistence_transaction_ownership(tmp_path) == []


def test_persistence_transaction_guard_ignores_unrelated_methods_and_other_layers(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "apps/api/app/infrastructure/queries/jobs.py",
        "class Worker:\n"
        "    def begin(self) -> None: ...\n"
        "    def commit(self) -> None: ...\n"
        "    def rollback(self) -> None: ...\n\n"
        "def run(worker: Worker) -> None:\n"
        "    worker.begin()\n"
        "    worker.commit()\n"
        "    worker.rollback()\n",
    )
    write_module(
        tmp_path,
        "apps/api/app/domains/billing/application/unit_of_work.py",
        "from sqlalchemy.orm import Session\n\ndef run(db: Session) -> None:\n    with db.begin():\n        pass\n",
    )

    assert check_persistence_transaction_ownership(tmp_path) == []


def test_comments_strings_and_allowed_session_import_pass(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "apps/api/app/domains/legal/router.py",
        '"from app.integrations import provider"\n'
        "# from app.domains.identity import router\n"
        "from app.domains.identity.session import DEFAULT_REGION\n",
    )

    assert check_python_boundaries(tmp_path) == []


def test_provider_neutral_modules_reject_cloudpayments_literal(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "apps/api/app/domains/billing/service/lifecycle.py",
        'if provider == "cloudpayments":\n    pass\n',
    )
    write_module(
        tmp_path,
        "apps/api/app/payment_providers/accounts.py",
        'DEFAULT_PROVIDER = "cloudpayments"\n',
    )

    errors = check_python_boundaries(tmp_path)

    assert any(
        "apps/api/app/domains/billing/service/lifecycle.py contains CloudPayments-specific logic" in error
        for error in errors
    )
    assert any(
        "apps/api/app/payment_providers/accounts.py contains CloudPayments-specific logic" in error for error in errors
    )


def test_legacy_auth_module_reexports_session_contract() -> None:
    from app.auth import DEFAULT_REGION, DEFAULT_TENANT_ID, as_utc, get_current_session
    from app.domains.identity.services import auth
    from app.http_dependencies import get_current_session as http_get_current_session

    assert DEFAULT_REGION == "ru"
    assert DEFAULT_TENANT_ID == "anytoolai"
    assert as_utc is auth.as_utc
    assert get_current_session is http_get_current_session
