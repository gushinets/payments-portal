"""Explicitly simulated client test inputs; never imported by Portal runtime."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from app.core.settings import Settings
from apps.api.tests.support.settings import DEFAULT_API_TEST_ENV


CONTRACT = Path(__file__).resolve().parents[4] / "docs/contracts/kernel-capability-manifest/v1"
EXPECTED_DIGEST = "sha256:535a1cdf925b0afaa07b6d6045fd92f98dcb620dbd5fac7bf359dd3416a741fe"
TOKEN = "simulated-kernel-client-test-token"


def manifest_fixture() -> dict[str, Any]:
    return copy.deepcopy(json.loads((CONTRACT / "fixtures/valid-manifest.json").read_text(encoding="utf-8")))


def independent_digest(payload: dict[str, Any]) -> str:
    semantic = {key: payload[key] for key in ("schema_version", "tenant_id", "region", "products", "usage_metrics")}
    semantic["products"] = sorted(semantic["products"], key=lambda item: item["product_id"])
    semantic["usage_metrics"] = sorted(semantic["usage_metrics"], key=lambda item: item["metric_key"])
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


def resign(payload: dict[str, Any]) -> dict[str, Any]:
    payload["manifest_version"] = independent_digest(payload)
    return payload


def kernel_settings(**overrides: Any) -> Settings:
    values = {name.lower(): value for name, value in DEFAULT_API_TEST_ENV.items()}
    values.update(
        kernel_base_url="http://kernel-client.test",
        kernel_service_token=TOKEN,
        kernel_mock_enabled=overrides.get("app_env") != "production",
        kernel_max_retries=0,
        # Kernel-only cases must not inherit a developer's real billing pool.
        lbx_base_url="",
        lbx_server_username="",
        lbx_server_password="",
        lbx_widget_signing_secret="",
        lbx_seller_organization_id="",
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)
