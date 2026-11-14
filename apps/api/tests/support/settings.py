from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any


DEFAULT_API_TEST_ENV = {
    "APP_ENV": "test",
    "INSTANCE_TENANT_ID": "anytoolai",
    "INSTANCE_REGION": "ru",
    "APP_PUBLIC_BASE_URL": "http://localhost:3000",
    "DATABASE_URL": "sqlite+pysqlite:///:memory:",
    "POSTGRES_DB": "anytoolai_test",
    "POSTGRES_USER": "anytoolai",
    "POSTGRES_PASSWORD": "anytoolai",
    "POSTGRES_HOST": "postgres",
    "POSTGRES_PORT": "5432",
    "CORS_ALLOW_ORIGINS": "http://localhost:3000",
    "SENTRY_DSN": "",
    "SENTRY_RELEASE": "",
    "SKIP_LEGAL_SEED": "true",
    "BILLING_WORKER_ENABLED": "false",
    "KERNEL_MOCK_ENABLED": "0",
    "PURCHASE_TEST_TERMS_ENABLED": "false",
}


_APPLICATION_ENV_PREFIXES = (
    "APP_",
    "INSTANCE_",
    "POSTGRES_",
    "CORS_",
    "SMTP_",
    "SENTRY_",
    "KERNEL_",
    "LBX_",
    "PREFLIGHT_",
    "BILLING_",
    "MAPPING_",
    "PAID_ACCESS_",
    "PURCHASE_",
    "OTEL_",
)


def _application_variable(name: str) -> bool:
    name = name.upper()  # Pydantic settings are case-insensitive, also on Unix.
    # Explicit test connection inputs survive until the canonical launcher
    # resolves them; ordinary application connection settings never survive.
    if name.startswith("POSTGRES_") and name.endswith("_TEST"):
        return False
    return name in {"DATABASE_URL", "SKIP_LEGAL_SEED", "LOG_LEVEL"} or name.startswith(_APPLICATION_ENV_PREFIXES)


def api_test_environment(*, environ: Mapping[str, str] | None = None, **overrides: str) -> dict[str, str]:
    """Retain process tooling, replace application settings, then apply the scenario."""
    inherited = os.environ if environ is None else environ
    return {
        **{name: value for name, value in inherited.items() if not _application_variable(name)},
        **DEFAULT_API_TEST_ENV,
        "PYTHON_DOTENV_DISABLED": "1",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "",
        **overrides,
    }


def configure_api_test_environment(**overrides: str) -> None:
    environment = api_test_environment(**overrides)
    for name in tuple(os.environ):
        if _application_variable(name):
            del os.environ[name]
    os.environ.update(environment)


@contextmanager
def override_settings(settings: Any, **overrides: Any) -> Iterator[None]:
    original_values = {name: getattr(settings, name) for name in overrides}
    try:
        for name, value in overrides.items():
            object.__setattr__(settings, name, value)
        yield
    finally:
        for name, value in original_values.items():
            object.__setattr__(settings, name, value)
