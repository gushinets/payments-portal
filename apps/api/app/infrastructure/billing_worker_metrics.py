"""Bounded-cardinality worker signals. No customer, product or local IDs."""

from prometheus_client import Counter, Gauge

ATTEMPTS = Counter("payment_portal_billing_worker_attempts_total", "Billing worker attempts", ("lane", "outcome"))
SLOTS = Gauge(
    "payment_portal_billing_worker_active_slots", "Occupied source slots including retained cleanup", ("lane",)
)
CLEANUP = Gauge("payment_portal_billing_worker_cleanup_pending", "Unfinished source cleanup", ("lane",))
BACKLOG = Gauge("payment_portal_billing_worker_pending", "Durable pending or running work")
INVALID = Gauge("payment_portal_billing_worker_invalid", "Quarantined historical records")
LAG = Gauge("payment_portal_billing_worker_lag_seconds", "Age of oldest overdue durable work")
PROGRESS = Gauge("payment_portal_billing_worker_last_progress_timestamp_seconds", "Last completed local or source work")
PROOFS = Counter(
    "payment_portal_billing_worker_subscription_proofs_total", "Committed subscription proof outcomes", ("outcome",)
)
LAST_PROOF = Gauge(
    "payment_portal_billing_worker_last_verified_subscription_timestamp_seconds",
    "Last complete matching subscription proof",
)
