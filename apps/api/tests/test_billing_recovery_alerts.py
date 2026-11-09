"""Actual Sentry envelope/privacy boundary; no live Sentry delivery."""

import json
from dataclasses import replace
from uuid import UUID, uuid4
from unittest.mock import patch

import pytest

from app.domains.billing.work_contracts import RecoveryEscalation
from app.infrastructure import sentry
from app.infrastructure.billing_recovery_alerts import RECOVERY_RUNBOOK
from apps.api.tests.test_sentry_reporting import capture_events, event_payload


@pytest.mark.parametrize("kind", ["customer", "agreement", "subscription"])
def test_recovery_event_is_actionable_without_entity_fingerprints(kind: str) -> None:
    notice = RecoveryEscalation(uuid4(), kind, uuid4())
    with capture_events() as (transport, _):
        assert sentry.report_billing_recovery_exhausted(notice)
    event = event_payload(transport)
    context = event["contexts"]["billing_recovery"]
    assert context["operation_id"] == str(notice.operation_id)
    assert context["runbook_url"] == RECOVERY_RUNBOOK
    assert "--operation-id " + str(notice.operation_id) in context["inspect_command"]
    assert event["exception"]["values"][0]["value"] == sentry.RECOVERY_EXHAUSTED_MESSAGE
    assert event["tags"]["failure_category"] == "unknown_external_outcome"
    assert event["fingerprint"] == ["billing_recovery_exhausted"]
    assert "user_id" not in context and "purchase_id" not in context
    with capture_events() as (again, _):
        assert sentry.report_billing_recovery_exhausted(notice)
    assert event_payload(again)["fingerprint"] == event["fingerprint"]
    with capture_events() as (other, _):
        assert sentry.report_billing_recovery_exhausted(replace(notice, case_id=uuid4()))
    assert event_payload(other)["fingerprint"] == event["fingerprint"]
    assert event_payload(other)["contexts"]["billing_recovery"]["case_id"] != str(notice.case_id)


def test_recovery_context_cannot_preserve_untrusted_text_or_replace_runbook() -> None:
    marker = "PRIVATE provider-key card token canary"
    context = sentry._sanitize_billing_recovery_context(
        {
            "operation_id": str(uuid4()),
            "user_id": str(uuid4()),
            "case_id": str(uuid4()),
            "purchase_id": str(uuid4()),
            "operation_kind": "subscription",
            "runbook_url": "https://attacker.test/" + marker,
            "inspect_command": marker,
            "provider_error": marker,
            "authorization": marker,
        }
    )
    assert marker not in json.dumps(context)
    assert context["runbook_url"] == RECOVERY_RUNBOOK
    assert sentry._sanitize_billing_recovery_context({**context, "operation_kind": {}}) == {}
    assert sentry._sanitize_billing_recovery_context({**context, "operation_id": marker}) == {}


def test_recovery_envelope_keeps_only_fixed_message_and_validated_identifiers() -> None:
    marker = "PRIVATE provider password and token canary"
    user_id, purchase_id = str(uuid4()), str(uuid4())
    with capture_events() as (transport, scope):
        scope.set_context(
            "billing_recovery",
            {
                "operation_id": str(uuid4()),
                "user_id": user_id,
                "case_id": str(uuid4()),
                "purchase_id": purchase_id,
                "operation_kind": "subscription",
                "provider_payload": marker,
                "runbook_url": "https://attacker.test/" + marker,
                "inspect_command": marker,
            },
        )
        sentry.sentry_sdk.capture_exception(sentry.BillingRecoveryExhausted(marker))
    event = event_payload(transport)
    assert marker not in json.dumps(event)
    assert user_id not in json.dumps(event) and purchase_id not in json.dumps(event)
    assert event["exception"]["values"][0]["value"] == sentry.RECOVERY_EXHAUSTED_MESSAGE
    assert event["contexts"]["billing_recovery"]["runbook_url"] == RECOVERY_RUNBOOK


@pytest.mark.parametrize("raise_error", [False, True])
def test_recovery_report_failure_is_retryable(raise_error: bool) -> None:
    notice = RecoveryEscalation(UUID(int=1), "subscription", UUID(int=4))
    with patch.object(
        sentry.sentry_sdk,
        "capture_exception",
        return_value=None,
        side_effect=RuntimeError("PRIVATE sdk secret") if raise_error else None,
    ):
        assert sentry.report_billing_recovery_exhausted(notice) is False
