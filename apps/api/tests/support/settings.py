from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


DEFAULT_API_TEST_ENV = {
    "APP_ENV": "test",
    "APP_PUBLIC_BASE_URL": "http://localhost:3000",
    "DATABASE_URL": "sqlite+pysqlite:///:memory:",
    "CLOUDPAYMENTS_ENABLED": "false",
    "CORS_ALLOW_ORIGINS": "http://localhost:3000",
    "CLOUDPAYMENTS_API_SECRET": "",
    "CLOUDPAYMENTS_PUBLIC_ID": "pk_test_provider",
    "SKIP_LEGAL_SEED": "true",
}


def api_test_environment(**overrides: str) -> dict[str, str]:
    return {**DEFAULT_API_TEST_ENV, **overrides}


def configure_api_test_environment(**overrides: str) -> None:
    os.environ.update(api_test_environment(**overrides))


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
