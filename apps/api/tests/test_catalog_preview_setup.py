from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.errors import AppError
from app.core.settings import AppEnv
from apps.api.tests.support import catalog_preview
from apps.api.tests.support.commercial_mappings import SIMULATED_UID, operator_settings
from apps.api.tests.support.lbx import ACCOUNT
from apps.api.tests.support.settings import DEFAULT_API_TEST_ENV


@pytest.mark.parametrize(
    ("runtime_changes", "operator_changes", "code"),
    [
        ({"APP_ENV": "production"}, {}, "catalog_preview_development_only"),
        ({}, {"app_env": AppEnv.TEST}, "catalog_preview_development_only"),
        (
            {},
            {
                "app_env": AppEnv.PRODUCTION,
                "app_public_base_url": "https://portal.example.com",
                "cors_allow_origins": ("https://portal.example.com",),
                "kernel_base_url": "",
                "kernel_service_token": "",
                "lbx_base_url": "",
                "lbx_external_billing_account_id": "",
                "lbx_server_username": "",
                "lbx_server_password": "",
            },
            "catalog_preview_development_only",
        ),
        ({"POSTGRES_DB": "payments_12345678_tests"}, {}, "catalog_preview_worktree_database_required"),
        ({"POSTGRES_DB": "postgres"}, {}, "catalog_preview_worktree_database_required"),
        ({"MAPPING_ACCOUNT_ID": ""}, {}, "catalog_preview_runtime_scope_mismatch"),
        ({"INSTANCE_REGION": "foreign"}, {}, "catalog_preview_runtime_scope_mismatch"),
        ({}, {"mapping_operator_uids": ()}, "mapping_operator_forbidden"),
    ],
)
def test_manual_preview_setup_refuses_unsafe_target_before_sources_or_database(
    monkeypatch: pytest.MonkeyPatch,
    runtime_changes: dict[str, str],
    operator_changes: dict[str, object],
    code: str,
) -> None:
    runtime = {
        "APP_ENV": "development",
        "POSTGRES_DB": "payments_12345678",
        "INSTANCE_TENANT_ID": "anytoolai",
        "INSTANCE_REGION": "ru",
        "MAPPING_ACCOUNT_ID": ACCOUNT,
        **runtime_changes,
    }
    configuration = operator_settings(**{"app_env": AppEnv.DEVELOPMENT, **operator_changes})
    monkeypatch.setattr(os, "geteuid", lambda: SIMULATED_UID, raising=False)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("refused manual setup must not start source reads or open a database")

    monkeypatch.setattr("apps.api.tests.support.v1_mapping_operator.fresh_mapping_evaluation", forbidden)
    monkeypatch.setattr(catalog_preview, "create_engine", forbidden)
    with pytest.raises(AppError, match=code):
        catalog_preview.publish_simulated_preview(runtime, operator=configuration, expected_previous_revision=0)


@pytest.mark.skipif(not hasattr(os, "geteuid"), reason="Manual publisher requires Unix OS identity")
@pytest.mark.parametrize(
    ("explicit_environment", "expected_code"),
    [(None, "mapping_operator_forbidden"), ("test", "catalog_preview_development_only")],
)
def test_manual_preview_cli_bootstraps_harness_scope_before_settings_import(
    tmp_path: Path, explicit_environment: str | None, expected_code: str
) -> None:
    runtime = {
        **DEFAULT_API_TEST_ENV,
        "APP_ENV": "development",
        "POSTGRES_DB": "payments_12345678",
        "MAPPING_ACCOUNT_ID": ACCOUNT,
    }
    runtime_file = tmp_path / "runtime.env"
    runtime_file.write_text("".join(f"{name}={value}\n" for name, value in runtime.items()), encoding="utf-8")
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in DEFAULT_API_TEST_ENV
        and not name.startswith(("APP_", "INSTANCE_", "MAPPING_", "KERNEL_", "LBX_", "PREFLIGHT_", "POSTGRES_"))
    }
    environment.update(PYTHONPATH="apps/api", MAPPING_OPERATOR_UIDS="[]")
    if explicit_environment is not None:
        environment["APP_ENV"] = explicit_environment
    # A fresh interpreter reproduces the import-time failure that the normal
    # pytest process hides by configuring Settings during collection. Refuse
    # before any source read or DB connection, in every case.
    bootstrap = """
import runpy
import sys
from pathlib import Path
from scripts import repo

repo.RUNTIME_ENV = Path(sys.argv[1])
repo.read_dotenv = lambda: {}
sys.argv = ["catalog_preview", "--expected-previous-revision", "0"]
runpy.run_module("apps.api.tests.support.catalog_preview", run_name="__main__")
"""
    result = subprocess.run(
        [sys.executable, "-c", bootstrap, str(runtime_file)],
        cwd=Path(__file__).resolve().parents[3],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert json.loads(result.stderr) == {"detail": {"code": expected_code}}
