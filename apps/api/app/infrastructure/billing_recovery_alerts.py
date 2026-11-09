"""Fixed recovery guidance and a strict allowlist for Sentry operator context."""

from collections.abc import Mapping
from uuid import UUID


RECOVERY_RUNBOOK = (
    "https://github.com/gushinets/payments-portal/blob/main/"
    "docs/engineering/billing-background-operations.md#unknown-create-after-two-hours"
)
RECOVERY_EXHAUSTED_MESSAGE = (
    "LBX create outcome remains unknown after two hours. Automatic discovery is paused; "
    "the original operation and duplicate-prevention hold remain. Inspect and recover the "
    "original object; do not repeat CREATE or release the hold. Runbook: " + RECOVERY_RUNBOOK
)


class BillingRecoveryExhausted(RuntimeError):
    """Fixed operator-facing text, never a provider error or request payload."""


def _canonical_uuid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = UUID(value)
    except ValueError:
        return None
    return value if str(parsed) == value else None


def sanitize_billing_recovery_context(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    context: dict[str, object] = {}
    for key in ("operation_id", "case_id"):
        identity = _canonical_uuid(value.get(key))
        if identity is None:
            return {}
        context[key] = identity
    kind = value.get("operation_kind")
    if not isinstance(kind, str) or kind not in {"customer", "agreement", "subscription"}:
        return {}
    context["operation_kind"] = kind
    context["inspect_command"] = (
        f".venv/bin/python scripts/repo.py billing-purchase inspect-operation --operation-id {context['operation_id']}"
    )
    context["recover_action"] = "Use the local lookup's inspect/recover commands; never repeat an uncertain CREATE."
    context["runbook_url"] = RECOVERY_RUNBOOK
    return context
