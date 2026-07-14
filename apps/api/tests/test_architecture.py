from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
sys.path.insert(0, str(ROOT / "apps" / "api"))

from scripts.repo import check_python_boundaries


def write_module(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


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
        "apps/api/app/core/settings.py:1 imports app.integrations.cloudpayments"
        in error
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


def test_comments_strings_and_allowed_session_import_pass(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "apps/api/app/domains/legal/router.py",
        '"from app.integrations import provider"\n'
        "# from app.domains.identity import router\n"
        "from app.domains.identity.session import get_current_session\n",
    )

    assert check_python_boundaries(tmp_path) == []


def test_legacy_auth_module_reexports_session_contract() -> None:
    from app.auth import DEFAULT_REGION, DEFAULT_TENANT_ID, as_utc, get_current_session
    from app.domains.identity import session

    assert DEFAULT_REGION == "ru"
    assert DEFAULT_TENANT_ID == "anytoolai"
    assert as_utc is session.as_utc
    assert get_current_session is session.get_current_session
