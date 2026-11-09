"""Polling-only build has no receiver surface, setting or deployment propagation."""

from pathlib import Path

from app.core.settings import Settings
from app.main import create_app

ROOT = Path(__file__).resolve().parents[3]


def test_polling_build_has_no_receiver_or_enablement_configuration() -> None:
    schema = create_app().openapi()
    assert "/api/billing/lbx/webhook" not in schema["paths"]
    assert not any(name.startswith("lbx_webhook_") for name in Settings.model_fields)
    for name in (
        ".env.example",
        ".env.production.example",
        "docker-compose.yml",
        "docker-compose.prod.yml",
        "docker-compose.agent.yml",
        "scripts/repo.py",
        "apps/api/tests/support/settings.py",
    ):
        assert "LBX_WEBHOOK_" not in (ROOT / name).read_text()
    for name in (
        "http/billing_webhook.py",
        "http/body.py",
        "integrations/lbx/webhook.py",
        "domains/billing/webhooks.py",
        "domains/billing/webhook_contracts.py",
        "infrastructure/queries/billing_webhooks.py",
        "infrastructure/persistence/billing_webhooks.py",
    ):
        assert not (ROOT / "apps/api/app" / name).exists()
