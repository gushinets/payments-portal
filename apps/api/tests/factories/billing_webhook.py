"""Synthetic LBX subscription hints, including fields that must be discarded."""

from typing import Any

from app.core.settings import Settings
from apps.api.tests.support.any709_step1 import step1_settings

AUTH_HEADER = "X-Test-LBX-Hook"
AUTH_VALUE = "synthetic-webhook-secret-canary"
PATH = "/api/billing/lbx/webhook"


def webhook_settings(**overrides: Any) -> Settings:
    return step1_settings(
        **{
            "lbx_webhook_enabled": True,
            "lbx_webhook_auth_header": AUTH_HEADER,
            "lbx_webhook_auth_value": AUTH_VALUE,
            **overrides,
        }
    )


def hint_payload(
    *, event: str = "change_subscription", subscription_id: object = 567, agreement_id: object = 456, **extra: Any
) -> dict:
    return {
        "event": event,
        "parameters": {"subscription_id": subscription_id, "agreement_id": agreement_id, **extra},
    }
